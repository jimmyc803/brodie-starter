"""Compressed multi-day simulation of the Push-Up Challenge dispatcher (SPEC §11 P4 acceptance).

    PYTHONPATH=src:. .venv/bin/python scripts/simulate.py --users 60 --days 2 --lines 1 --seed 1
        [--dsn SERVER_DSN] [--report docs/challenge/SIMULATION_REPORT.md] [--no-report]

Drives the REAL code paths end to end against a local Postgres: a throwaway cluster from db/test/harness.py with
every migration applied, or, with --dsn, a fresh `sim_<random>` database the script creates (shim + schema + every
migration) on that LOCAL server (host localhost / 127.0.0.1 / ::1 / a unix socket; anything else is refused before
connecting) and drops afterwards. The simulation never touches an existing database: it truncates tables, so it
refuses to run in any database it did not name itself or whose clients table already has rows.
  * users text JOIN / YES / QUEUE / LEAVE / STOP / START / STATUS ... through POST /webhooks/mock of the dispatcher
    app (create_app, MESSAGING_PROVIDER=mock, CHALLENGE_ALLOW_MOCK_WEBHOOK=1) -> commands/handler -> outbox rows;
  * challenge.dispatcher.jobs.Jobs.run_due(now) runs every simulated 2 s step (ch_tick, power hours, freeze + final
    results, announcements, recap, post-call sweep, queue updates, alerts, heartbeat, messaging Outbox.run_once with
    MockProvider). Users react only to texts the MockProvider actually delivered ("you're up" -> FaceTime);
  * a fake worker posts /calls/start, /calls/event call_started / reps_committed (per-rep absolute timestamps) /
    call_ended, sometimes duplicated or reordered; some workers crash and a reconciler commits late.
Scenarios: random arrivals, JOIN (bad / taken names, never-confirmed joins), queueing, 15 % no-shows, late answers,
walk-ins, gatekeeper rejects (unregistered, not your turn, at cap, banned, frozen), STOP / LEAVE mid-queue, admin
bans, short / zero-rep / invalid / in-challenge / liveness-fail reps, reps in the reveal, calls steered to span power
hour boundaries, ET midnight and window_end, the freeze at window_end and the morning after (final results).

Time compression: Jobs.run_due runs every 2 s of simulated time whenever anything is live (a line not idle, an active
queue entry, a call in progress, a deliverable outbox row, a due user action). When fully quiescent the clock jumps to
the next user action, deferred outbox row or 5-minute boundary (job windows are >= 10 min wide), whichever is first.

Every invariant is asserted against an independent Python model (challenge.scoring for points/caps), the report is
written as markdown with metrics + PASS/FAIL per check, and the exit code is 0 iff every check passes.
Everything is seeded (--seed): agent behaviour, POWER_HOUR_SECRET, ids. The run fingerprint is printed so two runs of
the same seed can be compared.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import itertools
import os
import random
import re
import sys
import time as wall
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

STEP = timedelta(seconds=2)
IDLE_JUMP = timedelta(minutes=5)
CALL_COUNT_S, REVEAL_S, EXTRA_S = 180, 15, 60
GAP_S, CLAIM_S, CAP, MIN_COUNTED_S = 180, 90, 5, 30
NO_SHOW_P = 0.15
REPLY_TEMPLATES = {"welcome", "join_confirm_prompt", "join_bad_name", "join_taken", "queue_joined", "queue_line_open",
                   "queue_at_cap", "queue_already", "queue_in_call", "left_queue", "status", "top", "rules", "power",
                   "help", "stop_ack", "start_ack", "unknown", "not_registered"}
QUIET_OK = {"youre_up", "post_call"} | REPLY_TEMPLATES | {"alert"}


# ============================================================================ target database safety
class UnsafeTarget(Exception):
    """The simulation truncates tables: it must only ever run in a database it created on a local server."""


LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
LOCAL_ADDRS = {"127.0.0.1", "::1"}
SIM_DB = re.compile(r"^(simulation|sim_[0-9a-f]{12})$")


def check_local_dsn(dsn: str, env: dict | None = None) -> dict:
    """Refuse any DSN that could reach a non-local server (decided from the DSN + libpq env, before connecting)."""
    from psycopg import ProgrammingError
    from psycopg.conninfo import conninfo_to_dict
    env = os.environ if env is None else env
    try:
        params = conninfo_to_dict(dsn)
    except ProgrammingError as e:
        raise UnsafeTarget(f"unparseable DSN: {e}") from e
    if params.get("service") or env.get("PGSERVICE") or env.get("PGSERVICEFILE"):
        raise UnsafeTarget("pg service definitions are not allowed (the host could not be checked)")
    hosts = params.get("host") if params.get("host") is not None else env.get("PGHOST", "")
    addrs = params.get("hostaddr") if params.get("hostaddr") is not None else env.get("PGHOSTADDR", "")
    for h in str(hosts).split(","):
        h = h.strip()
        if not (h == "" or h.startswith(("/", "@")) or h.lower() in LOCAL_HOSTS):
            raise UnsafeTarget(f"host {h!r} is not localhost / 127.0.0.1 / ::1 / a unix socket")
    for a in str(addrs).split(","):
        a = a.strip()
        if a and a not in LOCAL_ADDRS:
            raise UnsafeTarget(f"hostaddr {a!r} is not a loopback address")
    return params


def check_target_db(conn) -> None:
    """Last guard before the simulation truncates anything: a database it named itself, with no clients."""
    name = conn.execute("select current_database()").fetchone()[0]
    if not SIM_DB.match(name):
        raise UnsafeTarget(f"database {name!r} was not created by the simulation")
    n = conn.execute("select count(*) from clients").fetchone()[0]
    if n:
        raise UnsafeTarget(f"database {name!r} already has {n} clients rows")


def _psql() -> str:
    import shutil

    from db.test.harness import PG_BIN
    exe = PG_BIN / "psql"
    found = str(exe) if exe.exists() else shutil.which("psql")
    if not found:
        raise RuntimeError("psql not found (set PG_BIN)")
    return found


def create_sim_database(server_dsn: str) -> tuple[str, str]:
    """Create `sim_<random>` on the local server of `server_dsn`, apply shim + schema + every migration (same as
    db/test/harness.py), and return (dsn, name). The server DSN's own database is only used to run CREATE DATABASE."""
    import secrets
    import subprocess

    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    from db.test.harness import SCHEMA, SHIM, migration_files
    check_local_dsn(server_dsn)
    name = f"sim_{secrets.token_hex(6)}"
    with psycopg.connect(server_dsn, autocommit=True) as c:
        c.execute(sql.SQL("create database {}").format(sql.Identifier(name)))
    dsn = make_conninfo(server_dsn, dbname=name)
    try:
        for path in [SHIM, SCHEMA, *migration_files()]:
            proc = subprocess.run([_psql(), "-X", "-q", "-v", "ON_ERROR_STOP=1", "-d", dsn, "-f", str(path)],
                                  capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise RuntimeError(f"applying {path.name} to {name} failed:\n{proc.stderr}")
        with psycopg.connect(dsn, autocommit=True) as c:
            check_target_db(c)
    except BaseException:
        drop_sim_database(server_dsn, name)
        raise
    return dsn, name


def drop_sim_database(server_dsn: str, name: str) -> None:
    import psycopg
    from psycopg import sql
    if not SIM_DB.match(name) or name == "simulation":
        raise UnsafeTarget(f"refusing to drop {name!r}: not a simulation database")
    check_local_dsn(server_dsn)
    with psycopg.connect(server_dsn, autocommit=True) as c:
        c.execute(sql.SQL("drop database if exists {} with (force)").format(sql.Identifier(name)))


# ============================================================================ plumbing
def line_handle(line_id: str) -> str:
    """The simulated FaceTime number of a line (lines.facetime_handle)."""
    return f"+1555010{int(line_id.rsplit('-', 1)[1]):04d}"


class ConnStore:
    """CONTRACTS C3 PgStore semantics over one persistent autocommit connection (PgStore opens one per call, which
    is too slow for ~10^5 simulated steps). Same SQL text and argument encoding as challenge.store.PgStore."""

    def __init__(self, dsn: str):
        import psycopg
        self.conn = psycopg.connect(dsn, autocommit=True)
        self.calls = 0

    def rpc(self, fn: str, args: dict | None = None) -> Any:
        import psycopg
        from psycopg.types.json import Jsonb

        from challenge.store import _IDENT, Json, StoreError, _jsonable
        args = args or {}
        if not _IDENT.match(fn) or not all(_IDENT.match(k) for k in args):
            raise StoreError(f"bad rpc identifier: {fn}")
        params = {k: Jsonb(_jsonable(v)) if isinstance(v, (dict, list, tuple, Json)) else v for k, v in args.items()}
        sql = f"select {fn}({', '.join(f'{k} => %({k})s' for k in args)}) as r"
        self.calls += 1
        try:
            row = self.conn.execute(sql, params).fetchone()
        except psycopg.Error as e:
            raise StoreError(f"{fn}: {e}") from e
        return row[0] if row else None

    def q(self, sql: str, params: Any = None) -> list[tuple]:
        return self.conn.execute(sql, params).fetchall()


@dataclass
class CallRec:
    id: str
    agent: "Agent | None"
    handle: str
    line: str
    started: datetime
    expected: str
    decision: str = ""
    reason: str = ""
    dur: int = 0
    reps: list[dict] = field(default_factory=list)
    liveness: str = "pass"
    crashed: bool = False
    kind: str = "full"
    steer: str | None = None
    counted: bool = False
    ended_at: datetime | None = None
    end_reason: str | None = None
    rep_count: int = 0
    committed: bool = False
    timed_out_at: datetime | None = None
    end_posted_at: datetime | None = None


@dataclass
class Agent:
    i: int
    name: str
    handle: str
    kind: str
    want: dict[date, int]
    active: list[tuple[int, int]]  # ET hour windows (end may exceed 24 = after midnight)
    uid: str | None = None
    joined_at: datetime | None = None
    banned_at: datetime | None = None
    opted_out: bool = False
    gone: bool = False
    patience_min: int = 180
    session_token: int = 0
    queued_at: datetime | None = None
    started: Counter = field(default_factory=Counter)  # ET day -> accepted calls
    name_attempts: list[str] = field(default_factory=list)
    stopper: bool = False
    text_line: str | None = None  # line named by the last 'you're up' text (the number to FaceTime)


class Sim:
    def __init__(self, args: argparse.Namespace, dsn: str):
        from fastapi.testclient import TestClient

        from challenge.config import Config
        from challenge.dispatcher.app import create_app
        from challenge.dispatcher.flags import Flags
        from challenge.dispatcher.jobs import Jobs
        from challenge.messaging.outbox import Outbox
        from challenge.messaging.providers import MockProvider
        from challenge.timeutil import ET, parse_ts

        self.args, self.ET = args, ET
        self.rng = random.Random(args.seed)
        check_local_dsn(dsn)
        self.st = ConnStore(dsn)
        self.n_lines = args.lines
        check_target_db(self.st.conn)  # before _setup_db truncates anything
        self._setup_db()
        cfg = {k: v for k, v in self.st.q("select key, value from competition_config")}
        self.window_start = parse_ts(cfg["window_start"])
        self.window_end = parse_ts(cfg["window_end"])
        last_day = self.window_end.astimezone(ET).date()
        self.days = [last_day - timedelta(days=args.days - 1 - k) for k in range(args.days)]
        self.t0 = datetime.combine(self.days[0], time(0), tzinfo=ET)
        self.t_end = datetime.combine(last_day + timedelta(days=1), time(10, 0), tzinfo=ET)
        self.now = self.t0
        clock = lambda: self.now  # noqa: E731
        self.provider = MockProvider()
        self.cfg = Config(self.st, ttl_s=15, clock=lambda: self.now.timestamp())
        self.outbox = Outbox(self.st, self.cfg, self.provider, clock=clock)
        self.jobs = Jobs(self.st, self.cfg, self.outbox, clock)
        self.app = create_app(self.st, None, clock=clock, flags=Flags(CALLER_ID_SOURCE="chert_meta",
                              MESSAGING_PROVIDER="mock", CARD_DELIVERY="link"), token="sim-token", rate_per_min=10 ** 9)
        self.http = TestClient(self.app)
        self.H = {"X-Brodie-Token": "sim-token"}
        self.lines = [f"line-{k}" for k in range(1, self.n_lines + 1)]

        self.events: list[tuple[datetime, int, Callable, tuple]] = []
        self.seq = itertools.count()
        self.in_seq = itertools.count(1)
        self.call_seq = itertools.count(1)
        self.agents: list[Agent] = []
        self.by_handle: dict[str, Agent] = {}
        self.by_uid: dict[str, Agent] = {}
        self.calls: dict[str, CallRec] = {}
        self.live: dict[str, CallRec] = {}  # accepted calls whose worker is still running
        self.claims: dict[str, dict] = {}  # line -> {queue_id, user_id, at, until}
        self.last_offline_until: dict[str, datetime] = {}
        self.sent_seen = 0
        self.opt_intervals: dict[str, list[list]] = defaultdict(list)  # uid -> [[start, end|None]]
        self.metrics: Counter = Counter()
        self.waits: list[float] = []
        self.youre_up_latency: list[float] = []
        self.claim_log: list[dict] = []  # every claim ch_tick made: {queue_id, user_id, line_id, at, until}
        self.youre_up_at: dict[tuple[int, datetime], datetime] = {}  # (queue_id, claimed_until) -> first delivery
        self.line_time: dict[str, Counter] = {ln: Counter() for ln in self.lines}
        self.violations: dict[str, list[str]] = defaultdict(list)
        self.vcount: Counter = Counter()
        self.boundaries: list[tuple[datetime, str]] = []
        self.aimed: set[datetime] = set()
        self.inbound: list[dict] = []
        self.run_due_calls = 0
        self.steps_skipped = 0

    # ------------------------------------------------------------------ setup
    def _setup_db(self) -> None:
        from psycopg.types.json import Jsonb
        q = self.st.conn.execute
        check_target_db(self.st.conn)
        q("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log, ch_job_state,"
          " rank_state, heartbeats restart identity cascade")
        q("delete from line_state where line_id <> 'line-1'")
        q("delete from lines where id <> 'line-1'")
        q("update lines set active = true")
        for k in range(2, self.n_lines + 1):
            q("insert into lines (id, chert_agent_name, active) values (%s, %s, true)", (f"line-{k}", f"brodie{k}"))
            q("insert into line_state (line_id, state, updated_at) values (%s, 'idle', now())", (f"line-{k}",))
        for k in range(1, self.n_lines + 1):  # each line's own FaceTime number, named in 'you're up' (C7.s)
            q("update lines set facetime_handle = %s where id = %s", (line_handle(f"line-{k}"), f"line-{k}"))
        q("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null, offline_until=null,"
          " in_call_since=null, version=0, updated_at=now()")
        q("delete from competition_config where key = 'frozen_at'")
        # production seed values (C2), restated so a reused --dsn database cannot carry stale edits
        for k, v in {"window_start": "2026-10-12T20:00:00-04:00", "window_end": "2026-10-18T23:59:59-04:00",
                     "call_count_s": CALL_COUNT_S, "call_reveal_s": REVEAL_S, "daily_call_cap": CAP,
                     "claim_window_s": CLAIM_S, "line_offline_gap_s": GAP_S, "min_counted_call_s": MIN_COUNTED_S,
                     "in_call_timeout_extra_s": EXTRA_S, "power_hour_window": [12, 22], "power_multiplier": 2,
                     "rank_drop_min": 2, "rank_drop_throttle_h": 3, "quiet_hours": [23, 9], "recap_hour": 10,
                     "streak_risk_hour": 20, "registration_open": True, "competition_frozen": False,
                     "swearing": False, "team_alert_handles": [], "outbound_rate_per_min": 20}.items():
            q("insert into competition_config (key, value, updated_by) values (%s, %s, 'sim')"
              " on conflict (key) do update set value = excluded.value", (k, Jsonb(v)))

    # ------------------------------------------------------------------ helpers
    def fail(self, check: str, msg: str) -> None:
        self.vcount[check] += 1
        if len(self.violations[check]) < 12:
            self.violations[check].append(f"[{self.fmt(self.now)}] {msg}")

    def fmt(self, t: datetime | None) -> str:
        return t.astimezone(self.ET).strftime("%a %H:%M:%S") if t else "-"

    def et_day(self, t: datetime) -> date:
        return t.astimezone(self.ET).date()

    def at(self, t: datetime, fn: Callable, *a) -> None:
        heapq.heappush(self.events, (max(t, self.now), next(self.seq), fn, a))

    def frozen(self, t: datetime) -> bool:
        return t >= self.window_end

    def rand_time(self, day: date, h0: float, h1: float) -> datetime:
        base = datetime.combine(day, time(0), tzinfo=self.ET)
        return base + timedelta(seconds=self.rng.uniform(h0 * 3600, h1 * 3600))

    # ------------------------------------------------------------------ model: caps
    def calls_today(self, uid: str, t: datetime) -> int:
        day = self.et_day(t)
        return sum(1 for c in self.calls.values()
                   if c.decision == "accept" and c.agent and c.agent.uid == uid and c.counted
                   and self.et_day(c.started) == day)

    @staticmethod
    def _counted_rule(c: CallRec, ended: datetime | None, reps: int) -> bool:
        return (ended is not None and (ended - c.started).total_seconds() >= MIN_COUNTED_S) or reps >= 1

    # ------------------------------------------------------------------ DB snapshots
    def snap_lines(self) -> dict[str, dict]:
        return {r[0]: {"state": r[1], "user_id": r[2] and str(r[2]), "call_id": r[3], "claimed_until": r[4],
                       "offline_until": r[5], "in_call_since": r[6]}
                for r in self.st.q("select ls.line_id, state, user_id, call_id, claimed_until, offline_until,"
                                   " in_call_since from line_state ls join lines l on l.id = ls.line_id"
                                   " where l.active order by ls.line_id")}

    def snap_queue(self) -> list[dict]:
        return [{"id": r[0], "user_id": str(r[1]), "status": r[2], "entered_at": r[3], "line_id": r[4]}
                for r in self.st.q("select id, user_id, status, entered_at, line_id from queue"
                                   " where status in ('waiting','notified') order by id")]

    def snap_clients(self) -> dict[str, dict]:
        return {str(r[0]): {"banned": r[1] is not None, "opted_out": r[2] is not None, "joined": r[3] is not None}
                for r in self.st.q("select id, banned_at, opted_out_at, joined_at from clients")}

    def eligible(self, queue: list[dict], clients: dict, lines: dict, t: datetime, exclude: set[int]) -> list[dict]:
        holders = {l["user_id"] for l in lines.values() if l["state"] in ("claimed", "in_call")}
        out = [q for q in queue if q["status"] == "waiting" and q["id"] not in exclude
               and not clients[q["user_id"]]["banned"] and not clients[q["user_id"]]["opted_out"]
               and self.calls_today(q["user_id"], t) < CAP and q["user_id"] not in holders]
        return sorted(out, key=lambda q: (self.calls_today(q["user_id"], t), q["entered_at"], q["id"]))

    # ------------------------------------------------------------------ texting (POST /webhooks/mock)
    def text(self, agent: Agent, body: str, dup: bool | None = None) -> str | None:
        """Send an inbound text; returns the reply template written for it (checked against the model)."""
        t = self.now
        expect = self.expect_reply(agent, body, t)
        mid = f"sim-in-{self.args.seed}-{next(self.in_seq)}"
        payload = {"messages": [{"id": mid, "handle": agent.handle, "body": body, "received_at": t.isoformat()}]}
        r = self.http.post("/webhooks/mock", json=payload)
        if r.status_code != 200 or not r.json().get("ok"):
            self.fail("webhook", f"POST /webhooks/mock {r.status_code} {r.text[:200]}")
            return None
        self.metrics["texts_in"] += 1
        self.metrics["cmd:" + body.split()[0].upper()] += 1
        if dup if dup is not None else self.rng.random() < 0.05:  # provider re-delivers the same message id
            r2 = self.http.post("/webhooks/mock", json=payload)
            self.metrics["webhook_redeliveries"] += 1
            if r2.status_code != 200 or r2.json().get("handled") != 0:
                self.fail("dup_texts", f"redelivered inbound {mid} was handled again: {r2.text[:120]}")
        rows = self.st.q("select template, ctx from messages where dedupe_key = %s", (f"reply:{mid}",))
        if len(rows) != 1:
            self.fail("dup_texts", f"inbound {mid} produced {len(rows)} replies")
            return None
        tpl, ctx = rows[0]
        self.inbound.append({"id": mid, "agent": agent.i, "body": body, "reply": tpl, "at": t})
        if expect is not None and tpl != expect:
            self.fail("queue_replies", f"{agent.name} '{body}' -> {tpl}, model expected {expect} ({ctx})")
        self.after_reply(agent, body, tpl, t)
        return tpl

    def expect_reply(self, agent: Agent, body: str, t: datetime) -> str | None:
        """Model of the QUEUE reply (C2 ch_queue_join + handler mapping); other commands are not modelled."""
        if body.split()[0].upper() not in ("QUEUE", "Q", "LINE"):
            return None
        if not agent.uid:
            return "not_registered"
        lines, queue, clients = self.snap_lines(), self.snap_queue(), self.snap_clients()
        uid, cl = agent.uid, clients[agent.uid]
        ct = self.calls_today(uid, t)
        mine = [q for q in queue if q["user_id"] == uid]
        if cl["banned"] or self.frozen(t):
            return "help"
        if mine or any(l["user_id"] == uid and l["state"] == "claimed" for l in lines.values()):
            reason = "already"
        elif any(l["user_id"] == uid and l["state"] == "in_call" for l in lines.values()):
            return "queue_in_call"
        elif ct >= CAP:
            return "queue_at_cap"
        else:
            reason = "ok"
        line_open = (ct < CAP and any(l["state"] == "idle" for l in lines.values())
                     and not any(q["user_id"] != uid for q in queue)
                     and not any(l["user_id"] == uid and (l["state"] == "in_call" or (
                         l["state"] == "claimed" and l["claimed_until"] > t)) for l in lines.values()))
        if line_open:
            return "queue_line_open"
        return "queue_already" if reason == "already" else "queue_joined"

    def after_reply(self, agent: Agent, body: str, tpl: str, t: datetime) -> None:
        word = body.split()[0].upper()
        if tpl == "welcome":
            row = self.st.rpc("ch_user_by_handle", {"p_handle": agent.handle})
            agent.uid, agent.joined_at = row["user_id"], t
            self.by_uid[agent.uid] = agent
            self.metrics["joined"] += 1
        if agent.uid and word in ("STOP",):
            agent.opted_out = True
            self.opt_intervals[agent.uid].append([t, None])
        if agent.uid and (word == "START" or (tpl in ("queue_joined", "queue_line_open") and agent.opted_out)):
            if agent.opted_out:
                agent.opted_out = False
                self.opt_intervals[agent.uid][-1][1] = t
        if tpl in ("queue_joined", "queue_line_open", "queue_already"):
            agent.queued_at = agent.queued_at or t
            token = agent.session_token
            self.at(t + timedelta(minutes=agent.patience_min), self.patience_check, agent, token)
        self.metrics["reply:" + tpl] += 1

    # ------------------------------------------------------------------ agent behaviour
    def next_active(self, agent: Agent, t: datetime, min_gap_s: float = 0) -> datetime | None:
        """Earliest time >= t + gap inside one of the agent's ET activity windows, within the sim."""
        t = t + timedelta(seconds=min_gap_s)
        for d in [self.et_day(t) - timedelta(days=1), *(self.et_day(t) + timedelta(days=k) for k in range(3))]:
            for h0, h1 in agent.active:
                a = datetime.combine(d, time(0), tzinfo=self.ET) + timedelta(hours=h0)
                b = datetime.combine(d, time(0), tzinfo=self.ET) + timedelta(hours=h1)
                if b > t and a < self.t_end:
                    return max(a, t) + timedelta(seconds=self.rng.uniform(0, 240))
        return None

    def plan_session(self, agent: Agent, gap_min: tuple[float, float]) -> None:
        if agent.gone or agent.banned_at:
            return
        agent.session_token += 1
        t = self.next_active(agent, self.now, self.rng.uniform(*gap_min) * 60)
        if t is not None and t < self.window_end + timedelta(minutes=40):
            self.at(t, self.session, agent, agent.session_token)

    def session(self, agent: Agent, token: int) -> None:
        if token != agent.session_token or agent.gone or not agent.uid:
            return
        day = self.et_day(self.now)
        if agent.started[day] >= agent.want.get(day, 0) and not self.frozen(self.now):
            nxt = datetime.combine(day + timedelta(days=1), time(0), tzinfo=self.ET)
            if nxt < self.t_end:
                agent.session_token += 1
                t = self.next_active(agent, nxt)
                if t:
                    self.at(t, self.session, agent, agent.session_token)
            return
        agent.queued_at = None
        tpl = self.text(agent, self.rng.choice(["QUEUE", "QUEUE", "Q", "queue", "line"]))
        if tpl == "queue_at_cap":
            self.metrics["at_cap_queue_replies"] += 1
            if self.rng.random() < 0.3:  # tries to call anyway
                self.at(self.now + timedelta(seconds=40), self.facetime, agent, "capped")
            nxt = datetime.combine(day + timedelta(days=1), time(0), tzinfo=self.ET)
            agent.session_token += 1
            t = self.next_active(agent, nxt)
            if t:
                self.at(t, self.session, agent, agent.session_token)
        elif tpl == "help" and self.frozen(self.now):
            agent.gone = True
        elif tpl == "queue_in_call":
            pass

    def patience_check(self, agent: Agent, token: int) -> None:
        if token != agent.session_token or not agent.uid or agent.gone:
            return
        mine = [q for q in self.snap_queue() if q["user_id"] == agent.uid and q["status"] == "waiting"]
        if mine and self.rng.random() < 0.7:
            self.text(agent, "LEAVE")
            self.metrics["leave_impatient"] += 1
            self.plan_session(agent, (30, 120))

    def on_delivered(self, agent: Agent, tpl: str, ctx: dict, sent_at: datetime) -> None:
        self.metrics["delivered:" + tpl] += 1
        if tpl == "youre_up" and ctx.get("queue_id") is not None and ctx.get("claimed_until"):
            # per claim ATTEMPT: a re-popped entry keeps its queue id but gets a new claimed_until
            self.youre_up_at.setdefault((int(ctx["queue_id"]), datetime.fromisoformat(ctx["claimed_until"])), self.now)
        if tpl == "youre_up" and ctx.get("claimed_until"):
            until = datetime.fromisoformat(ctx["claimed_until"])
            self.youre_up_latency.append((self.now - (until - timedelta(seconds=CLAIM_S))).total_seconds())
            # on-time / late is judged per claim attempt in verify_youre_up
        if tpl == "join_confirm_prompt" and agent.kind != "pending":
            self.at(self.now + timedelta(seconds=self.rng.uniform(5, 60)), self.text, agent, "YES")
        elif tpl in ("join_bad_name", "join_taken"):
            agent.name = f"{agent.name.split('_')[0]}_{agent.i}x"
            self.at(self.now + timedelta(seconds=self.rng.uniform(10, 50)), self.text, agent, f"JOIN {agent.name}")
        elif tpl == "welcome":
            self.plan_session(agent, (1, 20))
        if agent.stopper and tpl in ("queue_joined", "youre_up"):
            agent.stopper = False
            self.at(self.now + timedelta(seconds=self.rng.uniform(3, 30)), self.try_stop, agent, 0)
            return
        if tpl == "queue_line_open":
            ahead = self.boundary_ahead(self.now)
            if ahead and ahead[0] < 234 and not self.frozen(self.now):  # time the walk-in to straddle it
                plan = {"delay": max(ahead[0] - 90, 2), "dur": CALL_COUNT_S + REVEAL_S, "steer": ahead[1]}
                self.metrics["steered_answers"] += 1
                self.at(self.now + timedelta(seconds=plan["delay"]), self.facetime, agent, "walk_in", plan)
            else:
                self.at(self.now + timedelta(seconds=self.rng.uniform(2, 15)), self.facetime, agent, "walk_in")
        elif tpl == "youre_up":
            self.on_youre_up(agent, ctx)
        elif tpl == "missed_slot":
            if self.rng.random() < 0.6:
                self.plan_session(agent, (2, 25))
        elif tpl == "start_ack":
            self.plan_session(agent, (1, 15))

    def boundary_ahead(self, t: datetime) -> tuple[float, str] | None:
        for b, kind in self.boundaries:
            if b > t:
                return (b - t).total_seconds(), kind
        return None

    def on_youre_up(self, agent: Agent, ctx: dict) -> None:
        claim = self.claims.get(ctx.get("line_id"))
        if agent.queued_at:
            self.waits.append((self.now - agent.queued_at).total_seconds() / 60)
            agent.queued_at = None
        ahead = self.boundary_ahead(self.now)
        plan: dict[str, Any] = {}
        if ahead and ahead[0] < 860 and not self.frozen(self.now) and claim and claim["user_id"] == agent.uid:
            r, kind = ahead
            if r < 234:  # connect ~90 s before the boundary so the 180 s counting window straddles it
                plan = {"delay": min(max(r - 90, 2), 84), "dur": CALL_COUNT_S + REVEAL_S, "steer": kind}
            else:  # time this call (answer delay + length) so the line's next pop lands ~150 s before it
                x = min(max(r - 330, 12), 279) if r < 693 else r - 640
                d = max(x - (CALL_COUNT_S + REVEAL_S), self.rng.uniform(2, 15))
                d = min(d, x - 10, 84)
                plan = {"delay": d, "dur": int(x - d), "steer": None}
            self.metrics["steered_answers"] += 1
            self.at(self.now + timedelta(seconds=plan["delay"]), self.facetime, agent, "claim", plan)
            return
        u = self.rng.random()
        if u < NO_SHOW_P:
            self.metrics["no_show_chosen"] += 1
            return
        if u < NO_SHOW_P + 0.04:
            self.metrics["late_answer"] += 1
            self.at(self.now + timedelta(seconds=self.rng.uniform(95, 140)), self.facetime, agent, "late")
            return
        self.at(self.now + timedelta(seconds=self.rng.uniform(3, 60)), self.facetime, agent, "claim")

    # ------------------------------------------------------------------ calls (Chert router + fake worker)
    def route(self, agent: Agent | None, lines: dict) -> str:
        if agent and agent.text_line in lines:  # FaceTime the number the 'you're up' text named
            lid, agent.text_line = agent.text_line, None
            return lid
        uid = agent.uid if agent else None
        for lid, l in lines.items():
            if uid and l["user_id"] == uid and l["state"] == "claimed":
                return lid
        idle = [lid for lid, l in lines.items() if l["state"] == "idle"]
        return self.rng.choice(idle) if idle else self.rng.choice(sorted(lines))

    def expect_start(self, uid: str | None, lid: str, lines: dict, queue: list[dict], clients: dict,
                     t: datetime) -> str:
        """Model of ch_call_start in chert_meta mode (C2/C7, D-13)."""
        if t < self.window_start or self.frozen(t):
            return "frozen" if self.frozen(t) else "not_started"
        if not uid or not clients.get(uid, {}).get("joined"):
            return "not_registered"
        if clients[uid]["banned"]:
            return "banned"
        if any(k != lid and l["user_id"] == uid and (l["state"] == "in_call" or (
                l["state"] == "claimed" and l["claimed_until"] > t)) for k, l in lines.items()):
            return "not_your_turn"
        if self.calls_today(uid, t) >= CAP:
            return "at_cap"
        ls = lines[lid]
        if ls["state"] == "claimed" and ls["claimed_until"] > t and ls["user_id"] == uid:
            return "ok"
        if ls["state"] == "idle" and not any(q["user_id"] != uid for q in queue):
            return "ok"
        return "not_your_turn"

    def facetime(self, agent: Agent | None, why: str, plan: dict | None = None, handle: str | None = None) -> None:
        t = self.now
        lines, queue, clients = self.snap_lines(), self.snap_queue(), self.snap_clients()
        lid = self.route(agent, lines)
        uid = agent.uid if agent else None
        expected = self.expect_start(uid, lid, lines, queue, clients, t)
        cid = f"sim-{self.args.seed}-{next(self.call_seq)}"
        handle = handle or (agent.handle if agent else "+19995550000")
        rec = CallRec(cid, agent, handle, lid, t, expected)
        r = self.http.post("/calls/start", headers=self.H, json={"call_id": cid, "line_id": lid, "handle": handle})
        if r.status_code != 200:
            self.fail("gatekeeper", f"/calls/start {r.status_code}")
            return
        j = r.json()
        rec.decision, rec.reason = j["decision"], j["reason"]
        self.calls[cid] = rec
        self.metrics[f"start:{why}:{j['reason']}"] += 1
        if j["reason"] != expected:
            self.fail("gatekeeper", f"{cid} {why} {agent.name if agent else handle} on {lid}: got {j['reason']}, "
                      f"model {expected}; line={lines[lid]['state']}")
        if j["decision"] == "accept" and j.get("user_id") != uid:
            self.fail("gatekeeper", f"{cid} attributed to {j.get('user_id')} not {uid}")
        if self.rng.random() < 0.03:  # worker retries /calls/start: must be idempotent
            if self.http.post("/calls/start", headers=self.H,
                              json={"call_id": cid, "line_id": lid, "handle": handle}).json() != j:
                self.fail("events_idem", f"/calls/start replay of {cid} differs")
            self.metrics["start_replays"] += 1
        if j["decision"] != "accept":
            self.metrics["rejected:" + j["reason"]] += 1
            if agent and why in ("claim", "late") and not self.frozen(t):
                self.plan_session(agent, (3, 30))
            return
        self.metrics["accepted"] += 1
        self.metrics["walk_ins"] += lines[lid]["state"] == "idle"
        self.live[cid] = rec
        if agent:
            agent.started[self.et_day(t)] += 1
            agent.session_token += 1  # an accepted call ends the current waiting session
        self.post_event(rec, "call_started", f"{cid}:call_started", {})
        self.build_call(rec, plan or {})
        if rec.crashed:
            self.metrics["worker_crashes"] += 1
            last = max((rp["at"] for rp in rec.reps), default=t.isoformat())
            self.at(t + timedelta(seconds=CALL_COUNT_S + REVEAL_S + 120 + self.rng.uniform(5, 300)),
                    self.reconcile, rec, datetime.fromisoformat(last))
        else:
            self.at(t + timedelta(seconds=rec.dur), self.worker_end, rec)

    def build_call(self, rec: CallRec, plan: dict) -> None:
        rng, C = self.rng, rec.started
        u = rng.random()
        if plan.get("dur") is not None:
            rec.dur, rec.kind, rec.steer = int(plan["dur"]), "steered" if plan.get("steer") else "timed", plan.get("steer")
        elif u < 0.07:
            rec.dur, rec.kind = rng.randint(6, 25), "short"
        elif u < 0.11:
            rec.dur, rec.kind = rng.randint(35, 195), "zero_reps"
        elif u < 0.20:
            rec.dur, rec.kind = rng.randint(60, 179), "early_leave"
        else:
            rec.dur, rec.kind = CALL_COUNT_S + REVEAL_S, "full"
        rec.crashed = rec.kind in ("full", "early_leave") and rng.random() < 0.04
        rec.liveness = rng.choices(["pass", "skipped", "fail"], [90, 6, 4])[0]
        count_end = min(rec.dur, CALL_COUNT_S)
        if rec.kind == "zero_reps":
            n = 0
        elif rec.kind == "short":
            n = rng.choice([0, 0, 0, 1, 2])
        elif rec.steer:
            n = rng.randint(25, 45)
        else:
            n = max(0, int(count_end / 180 * rng.randint(5, 50)))
        lo = 8.0 if count_end > 10 else 1.0
        offs = sorted(rng.uniform(lo, max(lo + 0.5, count_end - 0.3)) for _ in range(n))
        if rec.dur > CALL_COUNT_S and rng.random() < 0.08:  # the worker leaks a rep from the reveal window
            offs.append(rng.uniform(CALL_COUNT_S + 0.1, rec.dur - 0.5))
        for k, off in enumerate(offs, 1):
            valid = rng.random() < 0.8
            rec.reps.append({
                "n": k, "t": round(off, 3), "at": (C + timedelta(seconds=round(off, 3))).isoformat(),
                "valid": valid, "reject_reasons": [] if valid else [rng.choice(["too_shallow", "hips_sag", "no_lockout"])],
                "faults": [], "in_challenge": rng.random() < 0.03, "min_elbow_deg_l": 80.0, "persons_in_frame": 1,
                "torso_ok": True, "side": "left", "classifier_labels": ["pushups - correct"]})

    def post_event(self, rec: CallRec, kind: str, idem: str, payload: dict) -> dict | None:
        body = {"kind": kind, "call_id": rec.id, "idem_key": idem, "at": self.now.isoformat(), "payload": payload}
        r = self.http.post("/calls/event", headers=self.H, json=body)
        if r.status_code != 200:
            self.fail("events_idem", f"/calls/event {kind} {rec.id}: {r.status_code} {r.text[:120]}")
            return None
        j = r.json()
        if not j.get("ok"):
            self.fail("events_idem", f"/calls/event {kind} {rec.id} not ok: {j}")
        if j.get("duplicate"):
            self.fail("events_idem", f"first post of {idem} reported duplicate")
        if self.rng.random() < 0.05:  # network retry of the same event: stored result, no second effect
            j2 = self.http.post("/calls/event", headers=self.H, json=body).json()
            self.metrics["event_replays"] += 1
            if not j2.get("duplicate") or j2.get("ok") != j.get("ok"):
                self.fail("events_idem", f"replay of {idem} not deduplicated: {j2}")
        return j

    def commit_payload(self, rec: CallRec, ended: datetime) -> dict:
        return {"started_at": rec.started.isoformat(), "ended_at": ended.isoformat(), "liveness_result": rec.liveness,
                "judge_version": "j1", "reps": rec.reps}

    def worker_end(self, rec: CallRec) -> None:
        ended = rec.started + timedelta(seconds=rec.dur)
        count_end = rec.started + timedelta(seconds=min(rec.dur, CALL_COUNT_S))
        end_payload = {"ended_at": ended.isoformat(), "count_end_at": count_end.isoformat(), "rep_count": len(rec.reps)}
        steps = [("reps_committed", self.commit_payload(rec, ended)), ("call_ended", end_payload)]
        if self.rng.random() < 0.2:
            steps.reverse()
        for kind, payload in steps:
            self.post_event(rec, kind, f"{rec.id}:{kind}", payload)
            if kind == "call_ended":
                self.model_end(rec, ended, len(rec.reps))
                self.check_offline(rec.line, rec.id)
            else:
                self.model_commit(rec, ended)
        self.live.pop(rec.id, None)
        self.after_call(rec)

    def reconcile(self, rec: CallRec, last_rep: datetime) -> None:
        """Reconciler for a crashed worker (C7): commits the checkpoint with ended_at = last rep time."""
        ended = max(last_rep, rec.started) if rec.reps else rec.started
        self.post_event(rec, "reps_committed", f"{rec.id}:reps_committed", self.commit_payload(rec, ended))
        self.model_commit(rec, ended)
        self.live.pop(rec.id, None)
        self.metrics["reconciled"] += 1
        self.after_call(rec)

    def after_call(self, rec: CallRec) -> None:
        a = rec.agent
        if a and not self.frozen(self.now):
            if a.kind == "grinder":
                self.plan_session(a, (1, 10))
            else:
                self.plan_session(a, (5, 60))

    # model of the end/commit rules (C2 counted_toward_cap, C7.x first end wins / timeout reconcile)
    def model_end(self, rec: CallRec, ended: datetime, reps: int) -> None:
        rec.end_posted_at = self.now
        reps = max(reps, rec.rep_count)
        if rec.ended_at is not None and rec.end_reason == "timeout":
            rec.ended_at, rec.end_reason, rec.rep_count = max(ended, rec.started), "end", reps
            rec.counted = self._counted_rule(rec, rec.ended_at, reps)
        else:
            rec.ended_at = rec.ended_at or max(ended, rec.started)
            rec.end_reason = rec.end_reason or "end"
            rec.rep_count = reps
            rec.counted = rec.counted or self._counted_rule(rec, rec.ended_at, reps)

    def model_commit(self, rec: CallRec, ended: datetime) -> None:
        rec.committed = True
        reps = max(rec.rep_count, len(rec.reps))
        if rec.end_reason == "timeout":
            rec.ended_at, rec.end_reason, rec.rep_count = max(ended, rec.started), "commit", reps
            rec.counted = self._counted_rule(rec, rec.ended_at, reps)
        else:
            rec.rep_count = reps
            rec.counted = rec.counted or self._counted_rule(rec, rec.ended_at, reps)

    def model_timeout(self, rec: CallRec) -> None:
        rec.timed_out_at = self.now
        if rec.ended_at is None:
            rec.ended_at = min(rec.started + timedelta(seconds=CALL_COUNT_S + REVEAL_S), self.now)
            rec.end_reason = "timeout"
        rec.counted = rec.counted or self._counted_rule(rec, rec.ended_at, rec.rep_count)

    def check_offline(self, lid: str, cid: str) -> None:
        l = self.snap_lines()[lid]
        if l["state"] != "offline" or l["offline_until"] != self.now + timedelta(seconds=GAP_S):
            # the line may already have been timed out by the tick (crash path) and be offline from then
            rec = self.calls[cid]
            if not (rec.timed_out_at and l["state"] in ("offline", "idle", "claimed", "in_call")):
                self.fail("offline_gap", f"{lid} after call_end {cid}: {l['state']} until {l['offline_until']}")
                return
        if l["state"] == "offline":
            self.last_offline_until[lid] = l["offline_until"]

    # ------------------------------------------------------------------ scripted background scenarios
    def schedule_world(self) -> None:
        rng, n = self.rng, self.args.users
        d1, dl = self.days[0], self.days[-1]
        kinds = ["pending"] * max(1, n // 30)
        kinds += ["nightowl"] * max(2, n * 12 // 100) + ["grinder"] * max(2, n // 10) + ["casual"] * (n // 5)
        kinds += ["normal"] * (n - len(kinds))
        rng.shuffle(kinds)
        taken_name = None
        for i, kind in enumerate(kinds[:n]):
            name = f"Lifter_{i:02d}"
            handle = f"+1202555{i:04d}"
            want = {}
            for d in self.days:
                want[d] = {"grinder": rng.randint(6, 7), "casual": 1, "nightowl": rng.randint(3, 5),
                           "normal": rng.randint(2, 4), "pending": 1}[kind]
            active = {"nightowl": [(21, 26.5)], "grinder": [(8, 23)], "casual": [(11, 21)],
                      "normal": [(9, 13), (16, 22.5)], "pending": [(12, 20)]}[kind]
            a = Agent(i, name, handle, kind, want, active, patience_min=rng.randint(90, 300))
            self.agents.append(a)
            self.by_handle[handle] = a
            if kind == "nightowl":
                join_t = self.rand_time(d1, 9, 20)
            elif rng.random() < 0.85 or len(self.days) == 1:
                join_t = self.rand_time(d1, 7, 15) if rng.random() < 0.8 else self.rand_time(d1, 15, 21)
            else:
                join_t = self.rand_time(self.days[1], 8, 14)
            first = name
            u = rng.random()
            if i > 3 and u < 0.04 and taken_name:
                first = taken_name  # tries a taken name first
            elif u < 0.08:
                first = "x!"  # bad name first
            taken_name = taken_name or name
            self.at(join_t, self.text, a, f"JOIN {first}")
            a.name_attempts.append(first)
        # final push on the last day + late-night stragglers after window_end
        for a in self.agents:
            if a.kind in ("normal", "grinder") and rng.random() < 0.5:
                a.active = a.active + [(22.5, 24.5)]
                a.want[dl] += 2  # one more push before the freeze
        for a in rng.sample(self.agents, min(6, n)):
            self.at(self.window_end + timedelta(minutes=rng.uniform(1, 40)), self.post_freeze_try, a)
        # late-evening crowds: one more call before each ET midnight (cap reset) and before the freeze
        for d in self.days:
            for a in rng.sample(self.agents, max(4, n // 5)):
                self.at(self.rand_time(d, 23.15, 23.8), self.late_push, a)
        # STOP / LEAVE mid-queue, noise texts, rogue calls, bans
        for a in rng.sample(self.agents, max(3, n // 8)):
            a.stopper = True  # texts STOP while queued (waiting or holding a claim)
        for a in rng.sample(self.agents, max(2, n // 15)):
            self.at(self.rand_time(rng.choice(self.days), 10, 21), self.try_leave, a, 0)
        noise = ["STATUS", "S", "me", "TOP", "lb", "RULES", "POWER", "HELP", "queu", "hey brodie", "statuss"]
        for _ in range(max(10, n * 2)):
            a = rng.choice(self.agents)
            self.at(self.rand_time(rng.choice(self.days), 8, 23.5), self.noise_text, a, rng.choice(noise))
        for k in range(max(5, n // 3)):  # unregistered numbers FaceTime the line
            self.at(self.rand_time(rng.choice(self.days), 9, 23.9), self.facetime, None, "unregistered", None,
                    f"+1303555{k:04d}")
        for d in self.days:  # early risers FaceTime straight away (walk-in when the line is idle and nobody waits)
            for _ in range(6):
                self.at(self.rand_time(d, 7.5, 9.5), self.impatient, rng.choice(self.agents))
        for _ in range(max(10, n // 2)):  # impatient callers without a claim
            self.at(self.rand_time(rng.choice(self.days), 9, 23.9), self.impatient, rng.choice(self.agents))
        self.at(datetime.combine(d1, time(15), tzinfo=self.ET), self.ban, "waiting", 0)
        self.at(datetime.combine(dl, time(13), tzinfo=self.ET), self.ban, "claimed", 0)

    def noise_text(self, a: Agent, body: str) -> None:
        if a.uid or self.rng.random() < 0.3:
            self.text(a, body)

    def late_push(self, a: Agent) -> None:
        ok = lambda x: x.uid and not x.gone and not x.banned_at and not x.opted_out  # noqa: E731
        if not ok(a):
            pool = [x for x in self.agents if ok(x)]
            if not pool:
                return
            a = self.rng.choice(pool)
        day = self.et_day(self.now)
        a.want[day] = max(a.want.get(day, 0), a.started[day] + 1)
        a.session_token += 1
        self.session(a, a.session_token)

    def impatient(self, a: Agent) -> None:
        if a.uid and not a.gone and not any(r.agent is a for r in self.live.values()):
            self.facetime(a, "impatient")

    def post_freeze_try(self, a: Agent) -> None:
        if a.uid:
            self.text(a, "QUEUE")
            self.at(self.now + timedelta(seconds=20), self.facetime, a, "after_freeze")

    def try_stop(self, a: Agent, n: int = 0) -> None:
        if not a.uid or a.banned_at:
            return
        mine = [q for q in self.snap_queue() if q["user_id"] == a.uid]
        if not mine:  # already popped and called: try again on the next queue
            a.stopper = True
            return
        self.metrics["stop_mid_queue"] += 1
        self.metrics["stop_while_" + mine[0]["status"]] += 1
        self.text(a, self.rng.choice(["STOP", "stop", "Stop texting me"]))
        lines, queue = self.snap_lines(), self.snap_queue()
        if any(q["user_id"] == a.uid for q in queue) or any(
                l["user_id"] == a.uid and l["state"] == "claimed" for l in lines.values()):
            self.fail("opt_out_ban", f"{a.name} still queued/claimed right after STOP")
        a.session_token += 1
        u = self.rng.random()
        if u < 0.5:
            self.at(self.now + timedelta(minutes=self.rng.uniform(30, 90)), self.text, a, "START")
        elif u < 0.75:
            a.session_token += 1
            self.at(self.now + timedelta(minutes=self.rng.uniform(30, 90)), self.session, a, a.session_token)
        else:
            a.gone = True

    def try_leave(self, a: Agent, n: int) -> None:
        if not a.uid or n > 40:
            return
        mine = [q for q in self.snap_queue() if q["user_id"] == a.uid]
        if not mine:
            self.at(self.now + timedelta(minutes=9), self.try_leave, a, n + 1)
            return
        self.metrics["leave_mid_queue"] += 1
        self.text(a, "LEAVE")
        if any(q["user_id"] == a.uid for q in self.snap_queue()):
            self.fail("one_active", f"{a.name} still queued right after LEAVE")
        self.plan_session(a, (20, 60))

    def ban(self, where: str, n: int) -> None:
        lines, queue = self.snap_lines(), self.snap_queue()
        if where == "waiting":
            pool = [q["user_id"] for q in queue if q["status"] == "waiting"]
        else:
            pool = [l["user_id"] for l in lines.values() if l["state"] == "claimed"]
        pool = [u for u in pool if u in self.by_uid and not self.by_uid[u].banned_at]
        if not pool:
            if n < 60:
                self.at(self.now + timedelta(minutes=2), self.ban, where, n + 1)
            return
        a = self.by_uid[pool[0]]
        r = self.st.rpc("ch_admin_ban", {"p_user_id": a.uid, "p_reason": f"sim: ban while {where}",
                                         "p_actor": "admin@sim.test"})
        if not r.get("ok"):
            self.fail("opt_out_ban", f"ban failed {r}")
            return
        a.banned_at = self.now
        self.metrics["bans"] += 1
        self.metrics["ban_while_" + where] += 1
        # the banned user keeps trying
        self.at(self.now + timedelta(seconds=30), self.facetime, a, "banned")
        self.at(self.now + timedelta(minutes=5), self.text, a, "QUEUE")

    # ------------------------------------------------------------------ main loop
    def refresh_boundaries(self) -> None:
        rows = self.st.q("select starts_at, ends_at from power_hours order by date_et")
        b = [(s, "ph_start") for s, _ in rows] + [(e, "ph_end") for _, e in rows]
        b += [(datetime.combine(d + timedelta(days=1), time(0), tzinfo=self.ET), "midnight") for d in self.days[:-1]]
        b.append((self.window_end, "window_end"))
        self.boundaries = sorted(x for x in b if self.t0 <= x[0] <= self.window_end)
        for bt, _ in self.boundaries:
            # a few users aim a call at each boundary they know about (power hour from the recap / POWER, midnight
            # cap reset, the freeze): they text QUEUE ~2 min before and FaceTime as soon as they are told to
            if bt not in self.aimed and bt - timedelta(minutes=3) > self.now:
                self.aimed.add(bt)
                for a in self.rng.sample(self.agents, 3):
                    self.at(bt - timedelta(seconds=self.rng.uniform(100, 150)), self.late_push, a)

    def quiescent(self, lines: dict, queue: list[dict]) -> datetime | None:
        """None if anything is live; otherwise the time to jump to."""
        if self.live or queue or any(l["state"] != "idle" for l in lines.values()):
            return None
        nb = self.st.q("select min(coalesce(not_before, created_at)) from messages where direction = 'out'"
                       " and status in ('queued', 'sending')")[0][0]
        if nb is not None and nb <= self.now:
            return None
        nxt = self.now + IDLE_JUMP
        nxt = nxt - timedelta(seconds=(nxt - self.t0).total_seconds() % IDLE_JUMP.total_seconds())
        cands = [nxt]
        if self.events:
            cands.append(self.events[0][0])
        if nb is not None:
            cands.append(nb)
        if self.now < self.window_end:
            cands.append(self.window_end)
        target = min(cands)
        # stay on the 2 s grid
        k = -(-(target - self.t0).total_seconds() // STEP.total_seconds())
        return self.t0 + STEP * int(k)

    def step_checks_before(self) -> tuple[dict, list[dict], dict]:
        return self.snap_lines(), self.snap_queue(), self.snap_clients()

    def run(self) -> None:
        self.schedule_world()
        t_wall = wall.monotonic()
        day_seen: set[date] = set()
        while self.now < self.t_end:
            while self.events and self.events[0][0] <= self.now:
                _, _, fn, a = heapq.heappop(self.events)
                fn(*a)
            lines_b, queue_b, clients_b = self.step_checks_before()
            out = self.jobs.run_due(self.now)
            self.run_due_calls += 1
            for name, v in out.items():
                if isinstance(v, dict) and set(v) == {"error"}:
                    self.fail("jobs_errors", f"step {name}: {v['error']}")
            if self.et_day(self.now) not in day_seen:
                day_seen.add(self.et_day(self.now))
                self.refresh_boundaries()
            self.after_tick(out.get("tick") or {}, lines_b, queue_b, clients_b)
            self.deliver()
            lines, queue = self.snap_lines(), self.snap_queue()
            for lid, l in lines.items():
                self.line_time[lid][l["state"]] += 1
            jump = self.quiescent(lines, queue)
            if jump is not None and jump > self.now + STEP:
                self.steps_skipped += int((jump - self.now) / STEP) - 1
                for lid in self.lines:
                    self.line_time[lid]["idle"] += int((jump - self.now) / STEP) - 1
                self.now = jump
            else:
                self.now += STEP
        self.wall_s = wall.monotonic() - t_wall

    def after_tick(self, tick: dict, lines_b: dict, queue_b: list[dict], clients_b: dict) -> None:
        t = self.now
        for cid in tick.get("timeouts", []):
            rec = self.calls.get(cid)
            if rec:
                self.model_timeout(rec)
                self.metrics["tick_timeouts"] += 1
        for ns in tick.get("no_shows", []):
            self.metrics["no_shows"] += 1
        lines = self.snap_lines()
        new = {c["line_id"] for c in tick.get("claims", [])}
        pre = {k: ({**v, "state": "idle", "user_id": None} if k in new else v) for k, v in lines.items()}
        popped: set[int] = set()
        for c in tick.get("claims", []):
            self.metrics["pops"] += 1
            if self.frozen(t):
                self.fail("freeze", f"pop on {c['line_id']} at/after window_end")
            cands = self.eligible(queue_b, clients_b, pre, t, popped)
            if not cands or cands[0]["id"] != c["queue_id"]:
                self.fail("priority", f"popped q{c['queue_id']} on {c['line_id']}; model wanted "
                          f"{[(q['id'], self.calls_today(q['user_id'], t)) for q in cands[:4]]}")
            popped.add(c["queue_id"])
            until = datetime.fromisoformat(c["claimed_until"]) if isinstance(c["claimed_until"], str) else c["claimed_until"]
            if abs((until - t).total_seconds() - CLAIM_S) > 0.001:
                self.fail("claim_window", f"claim on {c['line_id']} lasts {(until - t).total_seconds()} s")
            lo = self.last_offline_until.get(c["line_id"])
            if lo is not None and t < lo:
                self.fail("offline_gap", f"claim on {c['line_id']} at {self.fmt(t)} before offline_until {self.fmt(lo)}")
            a = self.by_uid.get(c["user_id"])
            if a and a.banned_at:
                self.fail("opt_out_ban", f"banned {a.name} popped")
            self.claims[c["line_id"]] = {"queue_id": c["queue_id"], "user_id": c["user_id"], "at": t, "until": until}
            self.claim_log.append({"queue_id": c["queue_id"], "user_id": c["user_id"], "line_id": c["line_id"],
                                   "at": t, "until": until})
        for lid, l in lines.items():
            if l["state"] == "claimed" and l["claimed_until"] <= t:
                self.fail("stuck_lines", f"{lid} claimed past claimed_until after tick")
            if l["state"] == "in_call" and l["in_call_since"] + timedelta(seconds=CALL_COUNT_S + REVEAL_S + EXTRA_S) <= t:
                self.fail("stuck_lines", f"{lid} in_call past the timeout after tick")
            if l["state"] == "offline":
                if l["offline_until"] <= t:
                    self.fail("stuck_lines", f"{lid} offline past offline_until after tick")
                self.last_offline_until[lid] = l["offline_until"]
        queue, clients = self.snap_queue(), self.snap_clients()
        if not self.frozen(t) and t >= self.window_start and any(l["state"] == "idle" for l in lines.values()):
            left = self.eligible(queue, clients, lines, t, set())
            if left:
                self.fail("idle_with_waiting", f"idle line while {len(left)} eligible users wait")
        per: Counter = Counter(q["user_id"] for q in queue)
        if any(v > 1 for v in per.values()):
            self.fail("one_active", "a user has >1 active queue entries")
        held = Counter(l["user_id"] for l in lines.values() if l["state"] in ("claimed", "in_call"))
        if any(v > 1 for v in held.values()):
            self.fail("one_active", "a user holds two lines")
        for q in queue:
            if q["status"] == "notified":
                l = lines.get(q["line_id"])
                if not l or l["state"] != "claimed" or l["user_id"] != q["user_id"]:
                    self.fail("one_active", f"notified entry q{q['id']} without matching claim")
            elif held.get(q["user_id"]):
                self.fail("one_active", f"user waiting while holding a line (q{q['id']})")

    def deliver(self) -> None:
        sent = self.provider.sent[self.sent_seen:]
        self.sent_seen = len(self.provider.sent)
        if not sent:
            return
        ids = [s["id"] for s in sent]
        rows = {r[0]: r for r in self.st.q("select provider_message_id, template, ctx, handle, sent_at from messages"
                                           " where provider_message_id = any(%s)", (ids,))}
        for s in sent:
            row = rows.get(s["id"])
            if row is None:
                self.fail("dup_texts", f"provider sent {s['id']} with no messages row")
                continue
            a = self.by_handle.get(s["handle"])
            if row[1] == "youre_up":
                ctx = row[2] or {}
                named = [lid for lid in self.lines if line_handle(lid) in s["body"]]
                if named != [ctx.get("line_id")]:
                    self.fail("youre_up_line", f"'you're up' for {ctx.get('line_id')} names {named}: {s['body']!r}")
                if a and len(named) == 1:
                    a.text_line = named[0]
            if a:
                self.on_delivered(a, row[1], row[2] or {}, row[4])

    # ================================================================== final verification
    def verify_youre_up(self) -> None:
        """Reconcile EVERY claim with a delivered 'you're up' before its claimed_until. A missing, suppressed, failed
        or late text is a FAIL, unless the user gave the claim up first (LEAVE / connected / STOP / banned, i.e. the
        entry left 'notified' by the user's or an admin's action, or the outbox dropped it as opted_out_or_banned)."""
        q = self.st.q
        status = {r[0]: r[1] for r in q("select id, status from queue where id = any(%s::bigint[])",
                                        ([c["queue_id"] for c in self.claim_log],))}
        opted = {int(r[0]) for r in q("select target from audit_log where action = 'opt_out_queue_remove'")}
        msg = {r[0]: (r[1], r[2]) for r in q("select dedupe_key, status, last_error from messages"
                                             " where template = 'youre_up'")}
        for c in self.claim_log:
            qid = c["queue_id"]
            got = self.youre_up_at.get((qid, c["until"]))
            if got is not None:
                if c["at"] <= got < c["until"]:
                    self.metrics["youre_up_on_time"] += 1
                    continue
                self.metrics["youre_up_late"] += 1
                self.fail("youre_up_latency", f"claim q{qid} on {c['line_id']} ({self.fmt(c['at'])}..{self.fmt(c['until'])})"
                          f" got its 'you're up' at {self.fmt(got)}, outside the claim")
                continue
            m_status, m_err = msg.get(f"youre_up:{qid}", (None, None))
            if status.get(qid) in ("connected", "left") or qid in opted or m_err == "opted_out_or_banned":
                self.metrics["youre_up_excused"] += 1
                continue
            self.metrics["youre_up_missing"] += 1
            a = self.by_uid.get(c["user_id"])
            self.fail("youre_up_latency", f"claim q{qid} on {c['line_id']} for {a.name if a else c['user_id']} "
                      f"({self.fmt(c['at'])}..{self.fmt(c['until'])}) never got 'you're up': message "
                      f"{m_status or 'missing'}{f' ({m_err})' if m_err else ''}, entry {status.get(qid)}")

    def verify(self) -> None:
        from challenge.scoring import rank_order, rep_points
        from challenge.timeutil import in_quiet_hours, parse_ts
        q = self.st.q
        end = self.now
        # ---------------- end state: nothing stuck
        lines = self.snap_lines()
        if any(l["state"] != "idle" for l in lines.values()):
            self.fail("end_state", f"lines not idle at end: {[(k, v['state']) for k, v in lines.items()]}")
        self.verify_youre_up()
        left = q("select id, status, entered_at from queue where status in ('waiting','notified')")
        if left:
            self.fail("freeze", f"queue not closed after freeze: {len(left)} active entries remain "
                      f"(e.g. q{left[0][0]} {left[0][1]} since {self.fmt(left[0][2])})")
        open_calls = q("select id from calls where decision='accept' and (ended_at is null or session_id is null"
                       " or postcall_done_at is null)")
        if open_calls:
            self.fail("end_state", f"{len(open_calls)} accepted calls not ended/committed/post-processed: "
                      f"{[r[0] for r in open_calls[:5]]}")
        stuck = q("select status, count(*) from messages where direction='out' and (status in ('sending','failed')"
                  " or (status='queued' and coalesce(not_before, created_at) <= %s)) group by status", (end,))
        if stuck:
            self.fail("end_state", f"outbox not drained: {stuck}")
        # ---------------- caps & counted_toward_cap
        db_calls = {r[0]: r for r in q("select id, decision, counted_toward_cap, user_id, connected_at, ended_at,"
                                       " end_reason from calls")}
        per_day: Counter = Counter()
        for cid, rec in self.calls.items():
            r = db_calls.get(cid)
            if r is None:
                self.fail("cap", f"{cid} missing in calls")
                continue
            if r[1] != rec.decision:
                self.fail("cap", f"{cid} decision {r[1]} vs {rec.decision}")
            if r[1] == "reject" and r[2]:
                self.fail("cap", f"rejected call {cid} counted")
            if r[2] != rec.counted:
                self.fail("cap", f"{cid} counted_toward_cap db={r[2]} model={rec.counted} kind={rec.kind} "
                          f"crashed={rec.crashed} reps={len(rec.reps)} dur={rec.dur}")
            if r[2]:
                per_day[(str(r[3]), self.et_day(r[4]))] += 1
        over = {k: v for k, v in per_day.items() if v > CAP}
        if over:
            self.fail("cap", f"users over the daily cap: {list(over.items())[:3]}")
        self.metrics["max_counted_per_user_day"] = max(per_day.values(), default=0)
        capped_days = {k for k, v in per_day.items() if v >= CAP}
        self.metrics["user_days_at_cap"] = len(capped_days)
        cross = 0
        for (uid, d) in capped_days:
            if any(c.decision == "accept" and c.agent and c.agent.uid == uid and self.et_day(c.started) == d + timedelta(days=1)
                   for c in self.calls.values()):
                cross += 1
        self.metrics["capped_then_called_next_day"] = cross
        # ---------------- points: per rep, independently recomputed with challenge.scoring
        ph = {r[0]: (r[1], r[2]) for r in q("select date_et, starts_at, ends_at from power_hours")}
        fz = q("select value #>> '{}' from competition_config where key='frozen_at'")
        frozen_flag = q("select value from competition_config where key='competition_frozen'")[0][0]
        if frozen_flag is not True:
            self.fail("freeze", f"competition_frozen = {frozen_flag} after window_end")
        if not fz or parse_ts(fz[0][0]) != self.window_end:
            self.fail("freeze", f"frozen_at = {fz} != window_end {self.window_end}")
        cutoff = min(self.window_end, parse_ts(fz[0][0])) if fz else self.window_end
        db_reps: dict[str, list] = defaultdict(list)
        for r in q("select c.id, rp.rep_number, rp.valid, rp.multiplier, rp.points, rp.at, rp.reject_reasons"
                   " from calls c join sets s on s.session_id = c.session_id join reps rp on rp.set_id = s.id"
                   " order by c.id, rp.rep_number"):
            db_reps[r[0]].append(r)
        totals: dict[str, dict] = {}
        m = self.metrics
        for cid, rec in self.calls.items():
            if rec.decision != "accept":
                continue
            got = db_reps.get(cid, [])
            if len(got) != len(rec.reps):
                self.fail("points", f"{cid}: {len(got)} reps stored, {len(rec.reps)} sent")
                continue
            uid = rec.agent.uid
            tot = totals.setdefault(uid, {"points": 0, "valid": 0, "reached": None})
            pts_call = 0
            ats = []
            for rp, row in zip(sorted(rec.reps, key=lambda x: x["n"]), got):
                at = parse_ts(rp["at"])
                ats.append(at)
                day = self.et_day(at)
                vf, mult, pts, extra = rep_points(
                    at, rp["valid"], rp["in_challenge"], rec.liveness == "fail", cutoff, ph.get(day), 2,
                    window_start=self.window_start, count_end_at=rec.started + timedelta(seconds=CALL_COUNT_S))
                if (row[2], row[3], row[4]) != (vf, mult, pts) or (extra and extra not in (row[6] or [])):
                    self.fail("points", f"{cid} rep {row[1]} at {self.fmt(at)}: db valid/mult/pts="
                              f"{row[2]}/{row[3]}/{row[4]} reasons={row[6]}, model {vf}/{mult}/{pts} extra={extra}")
                tot["points"] += pts
                tot["valid"] += vf
                pts_call += pts
                if pts > 0 and (tot["reached"] is None or at > tot["reached"]):
                    tot["reached"] = at
                m["reps_total"] += 1
                m["reps_valid"] += vf
                m["reps_2x"] += vf and mult == 2
                m["points_total"] += pts
                if extra:
                    m["reps_rejected:" + extra] += 1
                elif not rp["valid"]:
                    m["reps_rejected:judge"] += 1
                elif rp["in_challenge"]:
                    m["reps_rejected:in_challenge"] += 1
            if ats:
                lo, hi = min(ats), max(ats)
                mults = {r[3] for r in got}
                for b, kind in self.boundaries:
                    if lo < b <= hi:
                        m["span:" + kind] += 1
                        if kind.startswith("ph") and mults == {1, 2}:
                            m["span:ph_mixed_multiplier"] += 1
                        if kind == "window_end":
                            after = [r for r in got if r[5] >= self.window_end]
                            before = [r for r in got if r[5] < self.window_end]
                            if any(r[4] for r in after):
                                self.fail("freeze", f"{cid}: rep at/after window_end scored")
                            m["span_window_end_reps_before"] += len(before)
                            m["span_window_end_reps_after"] += len(after)
        bad_after = q("select count(*) from reps where at >= %s and points > 0", (self.window_end,))[0][0]
        if bad_after:
            self.fail("freeze", f"{bad_after} reps at/after window_end scored points")
        late = q("select count(*) from calls where decision='accept' and connected_at >= %s", (self.window_end,))[0][0]
        if late:
            self.fail("freeze", f"{late} calls accepted at/after window_end")
        late_pop = q("select count(*) from audit_log where action = 'line:idle->claimed' and at >= %s",
                     (self.window_end,))[0][0]
        if late_pop:
            self.fail("freeze", f"{late_pop} pops at/after window_end")
        # ---------------- leaderboard vs recomputation
        lb = self.st.rpc("ch_leaderboard", {"p_limit": 10000, "p_now": end})
        listed = [a for a in self.agents if a.uid and not a.banned_at]
        rows = [{"user_id": a.uid, "points": totals.get(a.uid, {}).get("points", 0),
                 "valid": totals.get(a.uid, {}).get("valid", 0), "reached_at": totals.get(a.uid, {}).get("reached"),
                 "joined_at": a.joined_at} for a in listed]
        want = rank_order(rows)
        if [r["user_id"] for r in lb] != [r["user_id"] for r in want]:
            first = next((k for k, (x, y) in enumerate(zip(lb, want)) if x["user_id"] != y["user_id"]), None)
            self.fail("totals", f"leaderboard order differs from recomputation at rank {first}"
                      f" ({len(lb)} vs {len(want)} listed)")
        lbm = {r["user_id"]: r for r in lb}
        for r in want:
            got = lbm.get(r["user_id"])
            if not got or got["points"] != r["points"] or got["valid_reps"] != r["valid"]:
                self.fail("totals", f"user {self.by_uid[r['user_id']].name}: db {got and (got['points'], got['valid_reps'])}"
                          f" model {(r['points'], r['valid'])}")
        self.leader = [(self.by_uid[r["user_id"]].name, r["points"], r["valid"]) for r in want[:5]]
        # ---------------- texts: duplicates, quiet hours, opt-out/ban, throttle
        sent = q("select id, user_id, handle, template, ctx, dedupe_key, sent_at, provider_message_id from messages"
                 " where direction='out' and status='sent' order by id")
        dk = q("select count(*), count(distinct dedupe_key) from messages where dedupe_key is not null")[0]
        if dk[0] != dk[1]:
            self.fail("dup_texts", f"dedupe keys not unique {dk}")
        prov_ids = Counter(s["id"] for s in self.provider.sent)
        if len(prov_ids) != len(self.provider.sent) or set(prov_ids) != {r[7] for r in sent} or len(sent) != len(prov_ids):
            self.fail("dup_texts", f"provider sends ({len(self.provider.sent)}) != sent rows ({len(sent)})")
        logical: Counter = Counter()
        for r in sent:
            uid, tpl, ctx, key, at = r[1], r[3], r[4] or {}, r[5] or "", r[6]
            who = str(uid) if uid else r[2]
            if tpl == "youre_up":
                ev = (ctx.get("queue_id"), ctx.get("claimed_until"))  # one per claim attempt
            elif tpl == "missed_slot":
                ev = ctx.get("queue_id")
            elif tpl == "post_call":
                ev = ctx.get("call_id")
            elif tpl in ("daily_recap", "ph_warn", "ph_start", "streak_risk", "ph_announce"):
                ev = str(self.et_day(at))
            elif tpl in ("final_results", "ending_soon"):
                ev = "once"
            elif tpl in REPLY_TEMPLATES:
                ev = key  # one reply per inbound provider message id (checked at send time too)
            elif tpl == "queue_update":
                ev = int(at.timestamp() // 600)
            elif tpl == "rank_drop":
                ev = key.split(":")[-1]
            else:
                ev = key
            logical[(who, tpl, ev)] += 1
            m["sent:" + tpl] += 1
            if tpl not in QUIET_OK and in_quiet_hours(at, (23, 9)):
                self.fail("quiet_hours", f"{tpl} sent in quiet hours at {self.fmt(at)}")
            a = self.by_uid.get(str(uid)) if uid else None
            if a and tpl not in REPLY_TEMPLATES and tpl != "alert":
                if a.banned_at and at >= a.banned_at:
                    self.fail("opt_out_ban", f"{tpl} sent to banned {a.name} at {self.fmt(at)}")
                for s0, s1 in self.opt_intervals.get(a.uid, []):
                    if s0 <= at and (s1 is None or at < s1):
                        self.fail("opt_out_ban", f"{tpl} sent to opted-out {a.name} at {self.fmt(at)}")
        dups = {k: v for k, v in logical.items() if v > 1}
        if dups:
            self.fail("dup_texts", f"{len(dups)} duplicate logical texts, e.g. {list(dups.items())[:3]}")
        drops: dict[str, list] = defaultdict(list)
        for r in sent:
            if r[3] == "rank_drop":
                drops[str(r[1])].append(r[6])
        for uid, ts in drops.items():
            ts.sort()
            if any((b - a).total_seconds() < 3 * 3600 for a, b in zip(ts, ts[1:])):
                self.fail("quiet_hours", f"rank_drop throttle violated for {uid}")
        audience = {str(r[0]) for r in q("select id from clients where joined_at is not null and banned_at is null"
                                         " and opted_out_at is null")}
        finals = Counter(str(r[1]) for r in sent if r[3] == "final_results")
        if set(finals) != audience or any(v != 1 for v in finals.values()):
            self.fail("freeze", f"final_results: {len(finals)} users got it, audience {len(audience)}")
        if any(r[6] < datetime.combine(self.days[-1] + timedelta(days=1), time(9), tzinfo=self.ET)
               for r in sent if r[3] == "final_results"):
            self.fail("quiet_hours", "final_results sent before 09:00 ET (D-21)")
        replies_in = Counter(x["id"] for x in self.inbound)
        if any(v != 1 for v in replies_in.values()):
            self.fail("dup_texts", "an inbound message was recorded twice")
        m["texts_out_sent"] = len(sent)
        m["texts_suppressed"] = q("select count(*) from messages where status='suppressed'")[0][0]
        m["texts_deferred_by_quiet_hours"] = q(
            "select count(*) from messages where direction='out' and status='sent' and not_before > created_at")[0][0]
        # ---------------- power hours
        days = sorted(ph)
        for d in days:
            s, e = ph[d]
            h = s.astimezone(self.ET).hour
            if not (12 <= h <= 21) or e - s != timedelta(hours=1) or s.astimezone(self.ET).minute:
                self.fail("power_hours", f"{d}: {self.fmt(s)}–{self.fmt(e)}")
        for d0, d1 in zip(days, days[1:]):
            if (d1 - d0).days == 1 and ph[d0][0].astimezone(self.ET).hour == ph[d1][0].astimezone(self.ET).hour:
                self.fail("power_hours", f"same hour on {d0} and {d1}")
        self.ph = {str(d): f"{ph[d][0].astimezone(self.ET):%H:%M}–{ph[d][1].astimezone(self.ET):%H:%M}" for d in days}
        # ---------------- coverage of required scenarios
        need = {"span:ph_start": 1, "span:ph_end": 1, "span:ph_mixed_multiplier": 1, "span:window_end": 1,
                "no_shows": 1, "walk_ins": 1, "rejected:not_registered": 1, "rejected:not_your_turn": 1,
                "rejected:at_cap": 1, "rejected:banned": 1, "rejected:frozen": 1, "stop_mid_queue": 1,
                "ban_while_waiting": 1, "ban_while_claimed": 1, "reconciled": 1, "at_cap_queue_replies": 1,
                "reps_2x": 1, "tick_timeouts": 1, "reps_rejected:after_freeze": 1, "reps_rejected:after_count": 1,
                "reps_rejected:liveness_fail": 1, "event_replays": 1, "webhook_redeliveries": 1,
                "capped_then_called_next_day": 1 if len(self.days) > 1 else 0,
                "span:midnight": 1 if len(self.days) > 1 else 0}
        for k, v in need.items():
            if m[k] < v:
                self.fail("coverage", f"scenario '{k}' occurred {m[k]}x (< {v})")


# ============================================================================ report
CHECKS = [
    ("priority", "Pop priority: every claim went to the eligible waiting entry with the fewest counted calls today, FIFO within the tier"),
    ("idle_with_waiting", "No active line left idle after a tick while an eligible user was waiting (window open)"),
    ("stuck_lines", "No stuck states: after every tick no line is past claimed_until / in_call timeout / offline_until"),
    ("claim_window", "Every claim lasts exactly claim_window_s (90 s); no-shows release the line on the next tick"),
    ("offline_gap", "Line offline gap: offline_until = call end + line_offline_gap_s and no pop before it"),
    ("one_active", "<=1 active queue entry per user; <=1 line per user; notified entries <-> claims; LEAVE immediate"),
    ("gatekeeper", "Every /calls/start decision equals the independent model (walk-in, claim, not_your_turn, at_cap, banned, frozen, unregistered)"),
    ("queue_replies", "Every QUEUE reply equals the model (joined / already / line open / at cap / in call / frozen)"),
    ("cap", "Caps across ET midnight: <=5 counted calls per user per ET day; counted_toward_cap equals the model for every call; rejected calls never count"),
    ("points", "Every rep's valid/multiplier/points equal challenge.scoring.rep_points (power hour 2x per rep, after_count, liveness, freeze)"),
    ("totals", "Leaderboard points, valid reps and order equal the Python recomputation (challenge.scoring.rank_order)"),
    ("dup_texts", "No duplicate texts: unique dedupe keys, provider sends <-> sent rows 1:1, <=1 per (user, template, logical event), one reply per inbound (re-deliveries ignored)"),
    ("quiet_hours", "Quiet hours: only replies / you're up / post-call between 23:00 and 09:00 ET; rank-drop throttle 3 h; final results after 09:00"),
    ("opt_out_ban", "STOP leaves the queue immediately; no proactive text to opted-out or banned users; banned users never popped"),
    ("freeze", "Freeze at window_end: no pops/accepts after, reps at/after window_end score 0, frozen_at = window_end, queue closed, final results once per user"),
    ("events_idem", "Worker events and /calls/start are idempotent (replays return the stored result, no double effect)"),
    ("end_state", "End state: lines idle, every accepted call ended + committed + post-processed, outbox drained, nothing failed"),
    ("power_hours", "Power hours: one per ET day, whole hour inside 12:00-22:00 ET, different hour on consecutive days"),
    ("youre_up_latency", "Every claim's 'You're up' delivered before the claim expired (missing / suppressed / late = FAIL unless the user left, connected, STOPped or was banned first)"),
    ("youre_up_line", "Every 'You're up' names the FaceTime number of exactly the line the user was popped on (users call that number)"),
    ("jobs_errors", "No Jobs.run_due step raised"),
    ("webhook", "Every inbound webhook accepted"),
    ("coverage", "Required scenarios occurred (spans of power hour / midnight / window_end, no-shows, walk-ins, every reject reason, STOP, bans, crash reconcile, ...)"),
]


def render_section(sim: Sim, args: argparse.Namespace, fingerprint: str) -> tuple[str, bool]:
    m = sim.metrics
    ok_all = all(sim.vcount[k] == 0 for k, _ in CHECKS) and not (set(sim.vcount) - {k for k, _ in CHECKS})
    lines = [f"## Run: --users {args.users} --days {args.days} --lines {args.lines} --seed {args.seed} — "
             f"{'PASS' if ok_all else 'FAIL'}", ""]
    lines += [f"Simulated {sim.fmt(sim.t0)} → {sim.fmt(sim.t_end)} ET ({', '.join(str(d) for d in sim.days)}; "
              f"window_end {sim.window_end.astimezone(sim.ET):%a %Y-%m-%d %H:%M:%S} ET). "
              f"Jobs.run_due calls: {sim.run_due_calls:,}; 2 s steps skipped while quiescent: {sim.steps_skipped:,}; "
              f"RPCs: {sim.st.calls:,}; wall clock {sim.wall_s:.0f} s. Fingerprint `{fingerprint}`.", ""]
    lines += ["| Check | Result | Violations |", "|---|---|---|"]
    for k, desc in CHECKS:
        lines.append(f"| {desc} | {'PASS' if sim.vcount[k] == 0 else 'FAIL'} | {sim.vcount[k]} |")
    for k in sorted(set(sim.vcount) - {c for c, _ in CHECKS}):
        lines.append(f"| {k} | FAIL | {sim.vcount[k]} |")
    viol = [(k, v) for k, v in sim.violations.items() if v]
    if viol:
        lines += ["", "Violations (first per check):", ""]
        for k, v in viol:
            for msg in v[:5]:
                lines.append(f"- `{k}` {msg}")
    att = sum(v for k, v in m.items() if k.startswith("start:"))
    rej = Counter({k.split(":", 1)[1]: v for k, v in m.items() if k.startswith("rejected:")})
    calls_acc = [c for c in sim.calls.values() if c.decision == "accept"]
    kinds = Counter(c.kind for c in calls_acc)
    sent = Counter({k.split(":", 1)[1]: v for k, v in m.items() if k.startswith("sent:")})
    util = []
    for lid, c in sim.line_time.items():
        tot = sum(c.values()) or 1
        util.append(f"{lid}: " + ", ".join(f"{s} {100 * c[s] / tot:.0f}%" for s in ("in_call", "offline", "claimed", "idle")))
    w = sorted(sim.waits)
    lat = sorted(sim.youre_up_latency)
    pct = lambda xs, p: xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0  # noqa: E731
    reps_rej = ", ".join(f"{k.split(':', 1)[1]} {v}" for k, v in sorted(m.items()) if k.startswith("reps_rejected:"))
    lines += ["", "| Metric | Value |", "|---|---|",
              f"| Users (joined / never confirmed) | {m['joined']} / {sum(1 for a in sim.agents if not a.uid)} |",
              f"| Inbound texts (webhook re-deliveries) | {m['texts_in']} ({m['webhook_redeliveries']}) |",
              f"| QUEUE replies: joined / already / line open / at cap / in call | {m['reply:queue_joined']} / "
              f"{m['reply:queue_already']} / {m['reply:queue_line_open']} / {m['reply:queue_at_cap']} / {m['reply:queue_in_call']} |",
              f"| Pops (you're up) / no-shows ({100 * m['no_shows'] / max(m['pops'], 1):.1f}%) | {m['pops']} / {m['no_shows']} |",
              f"| /calls/start attempts / accepted / walk-ins | {att} / {m['accepted']} / {m['walk_ins']} |",
              f"| Gatekeeper rejects | {', '.join(f'{k} {v}' for k, v in sorted(rej.items()))} |",
              f"| Accepted call kinds | {', '.join(f'{k} {v}' for k, v in sorted(kinds.items()))} |",
              f"| Counted calls / max per user per ET day / user-days at cap / capped then called next day | "
              f"{sum(1 for c in calls_acc if c.counted)} / {m['max_counted_per_user_day']} / {m['user_days_at_cap']} / "
              f"{m['capped_then_called_next_day']} |",
              f"| Worker crashes (tick timeouts / reconciled) | {m['worker_crashes']} ({m['tick_timeouts']} / {m['reconciled']}) |",
              f"| Event replays / /calls/start replays | {m['event_replays']} / {m['start_replays']} |",
              f"| Reps total / valid / 2x (power hour) / points | {m['reps_total']} / {m['reps_valid']} / {m['reps_2x']} / {m['points_total']} |",
              f"| Rejected reps by reason | {reps_rej} |",
              f"| Calls spanning power-hour start / end / with 1x+2x reps | {m['span:ph_start']} / {m['span:ph_end']} / {m['span:ph_mixed_multiplier']} |",
              f"| Calls spanning ET midnight / window_end (reps before / after) | {m['span:midnight']} / {m['span:window_end']} "
              f"({m['span_window_end_reps_before']} / {m['span_window_end_reps_after']}) |",
              f"| STOP mid-queue (waiting / claimed) / LEAVE mid-queue / impatient LEAVE | {m['stop_mid_queue']} "
              f"({m['stop_while_waiting']} / {m['stop_while_notified']}) / {m['leave_mid_queue']} / {m['leave_impatient']} |",
              f"| Bans (while waiting / while holding a claim) | {m['bans']} ({m['ban_while_waiting']} / {m['ban_while_claimed']}) |",
              f"| Queue wait to you're up, min (median / p90 / max) | {pct(w, .5):.0f} / {pct(w, .9):.0f} / {(w[-1] if w else 0):.0f} |",
              f"| You're up delivery latency, s (median / p99 / max) | {pct(lat, .5):.0f} / {pct(lat, .99):.0f} / {(lat[-1] if lat else 0):.0f} |",
              f"| Claims reconciled: you're up on time / late / excused (user gave it up first) / missing | "
              f"{m['youre_up_on_time']} / {m['youre_up_late']} / {m['youre_up_excused']} / {m['youre_up_missing']} |",
              f"| Texts sent / suppressed / held by quiet hours | {m['texts_out_sent']} / {m['texts_suppressed']} / {m['texts_deferred_by_quiet_hours']} |",
              f"| Texts sent by template | {', '.join(f'{k} {v}' for k, v in sorted(sent.items()))} |",
              f"| Power hours (ET) | {', '.join(f'{k} {v}' for k, v in sim.ph.items())} |",
              f"| Line time share | {'; '.join(util)} |",
              f"| Top 5 (name, points, valid reps) | {', '.join(f'{n} {p}/{v}' for n, p, v in sim.leader)} |",
              ""]
    return "\n".join(lines), ok_all


HEADER = """# Push-Up Challenge — 2-day compressed simulation report (P4 acceptance)

Generated by `scripts/simulate.py` (see its docstring for the method). Each run drives the real dispatcher app
(`create_app`: `/webhooks/mock`, `/calls/start`, `/calls/event`), `Jobs.run_due` every simulated 2 s step (with the
messaging `Outbox` + `MockProvider`) and every migration against a throwaway local Postgres 17, then checks each
invariant against an independent Python model (`challenge.scoring`). Production config values (C2) are used:
cap 5/day, claim window 90 s, call 180 + 15 s, offline gap 180 s, quiet hours 23–09 ET, power hour 2x,
window_end Sun 2026-10-18 23:59:59 ET; the last `--days` ET days of the window are simulated plus the morning after.
Users behave as seeded random agents (arrivals, JOIN/YES, QUEUE, 15 % no-shows, late answers, walk-ins, rogue and
capped callers, STOP / LEAVE mid-queue, admin bans, short / zero-rep / crashed calls, reps in the reveal, power-hour
and midnight / window_end spanning calls). The raffle is cancelled (D-22) and not simulated.

Reproduce: `PYTHONPATH=src:. .venv/bin/python scripts/simulate.py --users 60 --days 2 --lines 1 --seed 1`
(and `--lines 2`). Exit code 0 iff every check passes.

Hypothesis property tests for the scheduler/state machine: `tests/challenge/test_scheduler_properties.py`
(1-line and 2-line RuleBasedStateMachine, 250 examples each, plus
variants that toggle the admin pause).

## Findings

Bugs found by the simulation and fixed in `db/migrations/20261019_challenge_sim_fixes.sql` (CONTRACTS C7.s; regression
tests in `tests/challenge/test_scheduler_properties.py` and `tests/challenge/test_db_sim_fixes.py`):

1. **window_end did not close the queue** (SPEC §7 "Freeze at window_end: stop popping, close queue"). `ch_tick`
   stopped popping but left entries `waiting` forever. Now every waiting entry is expired once p_now >= window_end
   (audit reason `frozen`). A manual `competition_frozen` (admin pause) only stops popping and keeps the queue; a
   claim that expires during a pause goes back to `waiting` with its place kept (`test_freeze_closes_queue`,
   `test_admin_pause_keeps_queue_window_end_closes_it_without_missed_slot`, stateful pause/close invariants).
2. **'You're up' starved behind bulk texts.** `ch_outbox_claim` was strict FIFO. A pop during a bulk send (power-hour
   start + ending-soon to every user at `outbound_rate_per_min` 20) delivered 'you're up' 158 s late, after the
   90 s claim had expired. The outbox now reserves capacity: live 'you're up' rows go first, but while ordinary
   texts are due no two 'you're up' are claimed back to back, so a claim waits for at most one ordinary send and
   ordinary texts keep at least half the rate. A 'you're up' whose claim attempt is gone, and queue-flow texts once
   frozen, are suppressed instead of sent late; each claim attempt has its own 'you're up'
   (`test_youre_up_not_starved_by_bulk_texts`, `test_youre_up_beats_a_120_text_backlog`,
   `test_sustained_claims_never_starve_ordinary_texts`). The run reconciles every claim attempt against a
   'you're up' delivered inside that claim.
3. **'You're up' did not say which line to call.** The text now names the line's FaceTime number
   (`lines.facetime_handle`; with one line `brodie_number`). Simulated users FaceTime the number in the text.
4. **A claim that expired at the freeze still sent missed_slot** ("Text QUEUE…") when QUEUE is refused. No longer.
5. `ch_set_opt` (STOP) and `ch_admin_queue_remove` freed claimed lines without the `line:claimed->idle` audit row;
   they now go through `ch_calls_line_set`. `ch_admin_ban/unban` gained a `p_now` overload (the simulation and
   property tests pass the simulated clock; the 3-arg admin-site form keeps `now()`).

Observation, not fixed (product decision): queue-position updates are about 40 % of all outbound texts and share
the 20/min outbox with everything else.

Safety: the script only runs in a database it creates (`sim_<random>` on a localhost / unix-socket server given by
`--dsn`, dropped afterwards, or a throwaway cluster) and refuses a non-empty `clients` table
(`tests/challenge/test_simulate_safety.py`).
"""


def write_report(path: Path, key: str, section: str) -> None:
    text = path.read_text() if path.exists() else ""
    sections: dict[str, str] = {}
    order: list[str] = []
    for m in re.finditer(r"<!-- run:(.+?) -->\n(.*?)<!-- /run -->\n", text, re.S):
        sections[m.group(1)] = m.group(2)
        order.append(m.group(1))
    if key not in sections:
        order.append(key)
    sections[key] = section
    body = HEADER + "\n" + "".join(f"<!-- run:{k} -->\n{sections[k]}<!-- /run -->\n" for k in sorted(order))
    path.write_text(body)


def fingerprint(sim: Sim) -> str:
    h = hashlib.sha256()
    for cid in sorted(sim.calls):
        c = sim.calls[cid]
        h.update(f"{cid}|{c.decision}|{c.reason}|{c.started.isoformat()}|{c.counted}|{len(c.reps)}\n".encode())
    for k in sorted(sim.metrics):
        h.update(f"{k}={sim.metrics[k]}\n".encode())
    return h.hexdigest()[:16]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--users", type=int, default=60)
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--lines", type=int, choices=(1, 2), default=1)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--dsn", help="LOCAL server to create (and drop) a fresh sim_<random> database on, e.g. "
                    "'host=/tmp dbname=postgres' or postgresql://postgres@127.0.0.1/postgres (default: throwaway "
                    "cluster). Non-local hosts are refused; an existing database is never used.")
    ap.add_argument("--report", default=str(ROOT / "docs" / "challenge" / "SIMULATION_REPORT.md"))
    ap.add_argument("--no-report", action="store_true")
    args = ap.parse_args(argv)
    if args.days < 1 or args.days > 6 or args.users < 10:
        ap.error("--days must be 1..6 and --users >= 10")
    if args.dsn:
        try:
            check_local_dsn(args.dsn)  # refuse before connecting or touching the environment
        except UnsafeTarget as e:
            print(f"simulate: refusing --dsn: {e}", file=sys.stderr)
            return 2

    os.environ.update({"JOBS_ENABLED": "0", "MESSAGING_PROVIDER": "mock", "CHALLENGE_ALLOW_MOCK_WEBHOOK": "1",
                       "CHALLENGE_MODE": "test", "POWER_HOUR_SECRET": f"simulation-seed-{args.seed:08d}",
                       "CARD_DELIVERY": "link", "CALLER_ID_SOURCE": "chert_meta"})
    for k in ("OUTBOUND_RATE_PER_MIN", "LINE_OFFLINE_GAP_S", "CHALLENGE_DB_DSN"):
        os.environ.pop(k, None)
    import logging
    logging.disable(logging.CRITICAL)  # the run is judged by its checks, not by log noise

    cluster = None
    created = None
    if args.dsn:
        try:
            dsn, created = create_sim_database(args.dsn)
        except UnsafeTarget as e:
            print(f"simulate: refusing --dsn: {e}", file=sys.stderr)
            return 2
    else:
        from db.test.harness import PgCluster
        cluster = PgCluster.start()
        cluster.build_template()
        dsn = cluster.clone("simulation")
    try:
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):  # create_app prints its startup flags
            sim = Sim(args, dsn)
        sim.run()
        sim.verify()
        fp = fingerprint(sim)
        section, ok = render_section(sim, args, fp)
        print(section)
        if not args.no_report:
            write_report(Path(args.report), f"users={args.users},days={args.days},lines={args.lines},seed={args.seed}",
                         section)
        print(f"{'PASS' if ok else 'FAIL'} fingerprint={fp}")
        return 0 if ok else 1
    finally:
        if created:
            drop_sim_database(args.dsn, created)  # with (force): closes the simulation's own connections
        if cluster:
            cluster.stop()


if __name__ == "__main__":
    sys.exit(main())
