"""Stateful property tests for the queue scheduler + line state machine (SPEC §7, CONTRACTS C2/C7).

A hypothesis RuleBasedStateMachine drives the real SQL RPCs (ch_queue_join/leave, ch_call_start/end, ch_tick,
ch_set_opt, ch_admin_ban) against the migrated local Postgres with a monotonically advancing p_now, on a 1-line and
a 2-line setup. Every RPC result is checked against an independent Python model of the rules built from a fresh
table snapshot (calls_today is recomputed in Python from calls rows, not with ch_calls_today), and the scheduler
invariants are checked after every step:

  * pop priority: each claim made by ch_tick goes to the eligible waiting entry with the smallest
    (calls_today, entered_at, id) -> nobody with fewer calls today waits behind someone with more; FIFO within tier;
  * after a tick (window open) no active line is idle while an eligible user is waiting;
  * <=1 active (waiting/notified) entry per user; a user is in at most one of {waiting entry, claim, in_call} and
    never claimed/in_call on two lines; notified entries and claims correspond 1:1;
  * a claim never lasts longer than claim_window_s (claimed_until - claim start <= claim_window_s and no claim
    survives a tick past claimed_until), so a no-show never blocks a line longer than claim_window_s;
  * <=1 in_call per line and every in_call line points at a live accepted call on that line;
  * <=1 open (unended) accepted call per line, and a line has one exactly when it is in_call (with that call_id);
  * gatekeeper-rejected calls never count toward the cap; no pop and no accept at/after window_end (freeze);
  * freeze vs pause (C7.s): after a tick at/after window_end no waiting entry remains and no "text QUEUE"
    missed_slot is written while frozen; a manual competition_frozen (toggled by the machine) stops popping but
    never expires an eligible waiting entry.
Seeded: derandomize=True, no example database.
"""
from __future__ import annotations

import itertools
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from hypothesis import HealthCheck, settings, strategies as st
from hypothesis.stateful import (RuleBasedStateMachine, initialize, invariant, precondition, rule,
                                 run_state_machine_as_test)
from psycopg.types.json import Jsonb

from challenge.store import _IDENT, Json, _jsonable
from challenge.timeutil import et_day, parse_ts

ET = ZoneInfo("America/New_York")
BASE = datetime(2026, 10, 13, 22, 0, tzinfo=ET)  # inside the competition window, 2h before an ET midnight
N_USERS = 5
CAP = 3
CLAIM_S = 90
GAP_S = 30
COUNT_S, REVEAL_S, EXTRA_S = 180, 15, 60
MIN_COUNTED_S = 30
SETTINGS = settings(max_examples=250, stateful_step_count=40, deadline=None, derandomize=True, database=None,
                    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much,
                                           HealthCheck.data_too_large])


class ConnStore:
    """PgStore semantics (C3) over one persistent autocommit connection (fast enough for stateful tests)."""

    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def rpc(self, fn: str, args: dict | None = None):
        args = args or {}
        assert _IDENT.match(fn) and all(_IDENT.match(k) for k in args)
        params = {k: Jsonb(_jsonable(v)) if isinstance(v, (dict, list, tuple, Json)) else v for k, v in args.items()}
        sql = f"select {fn}({', '.join(f'{k} => %({k})s' for k in args)}) as r"
        return self.conn.execute(sql, params).fetchone()[0]


def _cfg(conn, key, value):
    conn.execute("insert into competition_config (key, value, updated_by) values (%s, %s, 'test')"
                 " on conflict (key) do update set value = excluded.value", (key, Jsonb(value)))


@pytest.fixture(scope="module")
def pconn(db):
    conn = psycopg.connect(db, autocommit=True)
    saved = conn.execute("select key, value from competition_config").fetchall()
    for k, v in {"daily_call_cap": CAP, "claim_window_s": CLAIM_S, "line_offline_gap_s": GAP_S,
                 "call_count_s": COUNT_S, "call_reveal_s": REVEAL_S, "in_call_timeout_extra_s": EXTRA_S,
                 "min_counted_call_s": MIN_COUNTED_S, "competition_frozen": False,
                 "window_start": "2026-10-12T20:00:00-04:00"}.items():
        _cfg(conn, k, v)
    conn.execute("delete from competition_config where key = 'frozen_at'")
    yield conn
    conn.execute("delete from line_state where line_id <> 'line-1'")
    conn.execute("delete from lines where id <> 'line-1'")
    for k, v in saved:
        _cfg(conn, k, v)
    conn.execute("delete from competition_config where key = 'frozen_at'")
    conn.close()


class SchedulerMachine(RuleBasedStateMachine):
    conn: psycopg.Connection
    n_lines = 1
    pausing = False  # the admin pause rule is enabled only on the *Pausing machines
    stats: Counter

    def __init__(self):
        super().__init__()
        c = self.conn
        self.st = ConnStore(c)
        c.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log, ch_job_state,"
                  " rank_state restart identity cascade")
        c.execute("delete from line_state where line_id <> 'line-1'")
        c.execute("delete from lines where id <> 'line-1'")
        c.execute("update lines set active = true")
        for i in range(2, self.n_lines + 1):
            c.execute("insert into lines (id, chert_agent_name, active) values (%s, %s, true)", (f"line-{i}", f"b{i}"))
            c.execute("insert into line_state (line_id, state, updated_at) values (%s, 'idle', now())", (f"line-{i}",))
        c.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                  " offline_until=null, in_call_since=null, version=0, updated_at=now()")
        self.lines = [f"line-{i}" for i in range(1, self.n_lines + 1)]
        coach = c.execute("select (value #>> '{}')::uuid from competition_config"
                          " where key='challenge_coach_id'").fetchone()[0]
        self.users: list[str] = []
        self.handles: list[str] = []
        for i in range(N_USERS):
            uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s)"
                            " returning id", (coach, f"p{i}", f"prop_{i}", BASE - timedelta(days=2))).fetchone()[0]
            h = f"+1777000{i:04d}"
            c.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
                      (h, uid))
            self.users.append(str(uid))
            self.handles.append(h)
        _cfg(c, "competition_frozen", False)
        c.execute("delete from competition_config where key = 'frozen_at'")
        self.paused = False
        self.now = BASE
        self.window_end = BASE + timedelta(days=30)
        self.claim_start: dict[str, datetime] = {}  # line -> time its current claim was made
        self.call_seq = itertools.count(1)
        self.stats["examples"] += 1

    # ------------------------------------------------------------------ independent model
    def snap(self) -> dict:
        c = self.conn
        lines = {r[0]: {"state": r[1], "user_id": r[2] and str(r[2]), "call_id": r[3], "claimed_until": r[4],
                        "offline_until": r[5], "in_call_since": r[6], "updated_at": r[7]}
                 for r in c.execute("select line_id, state, user_id, call_id, claimed_until, offline_until,"
                                    " in_call_since, updated_at from line_state order by line_id")}
        active = [{"id": r[0], "user_id": str(r[1]), "status": r[2], "entered_at": r[3], "line_id": r[4]}
                  for r in c.execute("select id, user_id, status, entered_at, line_id from queue"
                                     " where status in ('waiting','notified') order by id")]
        clients = {str(r[0]): {"banned": r[1] is not None, "opted_out": r[2] is not None}
                   for r in c.execute("select id, banned_at, opted_out_at from clients")}
        calls = [{"id": r[0], "user_id": r[1] and str(r[1]), "line_id": r[2], "decision": r[3], "connected_at": r[4],
                  "ended_at": r[5], "counted": r[6], "rep_count": r[7]}
                 for r in c.execute("select id, user_id, line_id, decision, connected_at, ended_at,"
                                    " counted_toward_cap, rep_count from calls")]
        return {"lines": lines, "active": active, "clients": clients, "calls": calls}

    def calls_today(self, s: dict, uid: str, now: datetime) -> int:
        day = et_day(now)
        return sum(1 for x in s["calls"] if x["user_id"] == uid and x["counted"] and et_day(x["connected_at"]) == day)

    def frozen(self, now: datetime) -> bool:
        return now >= self.window_end or self.paused

    def holds(self, s: dict, uid: str) -> list[str]:
        return [lid for lid, l in s["lines"].items() if l["user_id"] == uid and l["state"] in ("claimed", "in_call")]

    def eligible_waiting(self, s: dict, now: datetime, exclude: set[int]) -> list[dict]:
        out = []
        for q in s["active"]:
            cl = s["clients"][q["user_id"]]
            if (q["status"] == "waiting" and q["id"] not in exclude and not cl["banned"] and not cl["opted_out"]
                    and self.calls_today(s, q["user_id"], now) < CAP and not self.holds(s, q["user_id"])):
                out.append(q)
        return sorted(out, key=lambda q: (self.calls_today(s, q["user_id"], now), q["entered_at"], q["id"]))

    # ------------------------------------------------------------------ rules
    @initialize(start=st.integers(0, 4 * 3600), end_after=st.integers(10 * 60, 6 * 3600),
                today=st.lists(st.integers(0, CAP), min_size=N_USERS, max_size=N_USERS),
                yesterday=st.lists(st.integers(0, CAP), min_size=N_USERS, max_size=N_USERS))
    def init_time(self, start, end_after, today, yesterday):
        self.now = BASE + timedelta(seconds=start)
        self.window_end = self.now + timedelta(seconds=end_after)
        _cfg(self.conn, "window_end", self.window_end.isoformat())
        # call history: counted calls earlier today (ET) and on the previous ET day, so every priority tier and the
        # cap are reachable, and the ET-midnight rollover resets the earlier day's count
        day0 = datetime.combine(et_day(self.now), datetime.min.time(), tzinfo=ET)
        for i, (nt, ny) in enumerate(zip(today, yesterday)):
            for k in range(nt + ny):
                at = (day0 + timedelta(seconds=10 + k)) if k < nt else (day0 - timedelta(hours=1, seconds=k))
                self.conn.execute(
                    "insert into calls (id, line_id, user_id, decision, connected_at, ended_at, counted_toward_cap,"
                    " end_reason, rep_count) values (%s, 'line-1', %s, 'accept', %s, %s, true, 'end', 1)",
                    (f"hist-{i}-{k}", self.users[i], at, at + timedelta(seconds=60)))

    @rule(dt=st.integers(1, 400))
    def advance(self, dt):
        self.now += timedelta(seconds=dt)

    @rule()
    def tick(self):
        now = self.now
        before = self.snap()
        missed_before = self.conn.execute("select count(*) from messages where template = 'missed_slot'").fetchone()[0]
        r = self.st.rpc("ch_tick", {"p_now": now})
        after = self.snap()
        self.check_close(before, after, now, missed_before)
        # Pop model: waiting entries as they were before the tick; calls_today after the tick's in_call timeouts
        # (they can finalize a call as counted before popping); line holders as after the timers, i.e. the
        # post-tick lines with this tick's new claims undone.
        new_claims = {c["line_id"] for c in r["claims"]}
        pre_pop_lines = {k: ({**v, "state": "idle", "user_id": None} if k in new_claims else v)
                         for k, v in after["lines"].items()}
        model = {"active": before["active"], "clients": before["clients"], "calls": after["calls"],
                 "lines": pre_pop_lines}
        popped: set[int] = set()
        for claim in r["claims"]:
            assert not self.frozen(now), f"pop at/after window_end: {claim}"
            cands = self.eligible_waiting(model, now, popped)
            assert cands, f"pop with no eligible candidate: {claim}"
            best = cands[0]
            assert claim["queue_id"] == best["id"], (
                f"priority violated: popped {claim['queue_id']} but {best['id']} "
                f"(calls_today={self.calls_today(model, best['user_id'], now)}, entered_at={best['entered_at']})"
                f" should go first; candidates={[(q['id'], self.calls_today(model, q['user_id'], now)) for q in cands]}")
            popped.add(best["id"])
            self.claim_start[claim["line_id"]] = now
            self.stats["pops"] += 1
            if len(cands) > 1 and self.calls_today(model, cands[0]["user_id"], now) < max(
                    self.calls_today(model, q["user_id"], now) for q in cands):
                self.stats["tiered_pops"] += 1
        for lid, l in after["lines"].items():
            if l["state"] == "claimed":
                assert l["claimed_until"] > now, f"{lid}: claim survived a tick past claimed_until"
            if l["state"] == "in_call":
                assert l["in_call_since"] + timedelta(seconds=COUNT_S + REVEAL_S + EXTRA_S) > now, f"{lid}: stuck in_call"
            if l["state"] == "offline":
                assert l["offline_until"] > now, f"{lid}: stuck offline"
        if not self.frozen(now) and any(l["state"] == "idle" for l in after["lines"].values()):
            left = self.eligible_waiting(after, now, set())
            assert not left, f"idle line while eligible users wait: {[q['id'] for q in left]}"
        if self.paused:  # the admin lifts the pause after the chosen number of ticks
            self.pause_ticks -= 1
            if self.pause_ticks <= 0:
                _cfg(self.conn, "competition_frozen", False)
                self.paused = False

    def check_close(self, before: dict, after: dict, now: datetime, missed_before: int) -> None:
        """window_end closes the queue; an admin pause (competition_frozen) only stops popping (C7.s)."""
        c = self.conn
        waiting_ids = [q["id"] for q in before["active"] if q["status"] == "waiting"]
        status = dict(c.execute("select id, status from queue where id = any(%s::bigint[])", (waiting_ids,)).fetchall())
        if now >= self.window_end:
            self.stats["closed_ticks"] += 1
            left = c.execute("select id from queue where status = 'waiting'").fetchall()
            assert not left, f"waiting entries survived a tick at/after window_end: {left}"
        else:
            if self.paused:
                self.stats["paused_ticks"] += 1
                for q in before["active"]:
                    if q["status"] == "notified" and status_of(c, q["id"]) == "waiting":
                        self.stats["pause_requeued"] += 1  # claim expired during the pause: place kept
            for q in before["active"]:
                if q["status"] == "waiting" and status[q["id"]] == "expired":
                    cl = after["clients"][q["user_id"]]
                    assert cl["banned"] or cl["opted_out"] or self.calls_today(after, q["user_id"], now) >= CAP, \
                        f"eligible waiting entry {q['id']} expired before window_end (paused={self.paused})"
        if self.frozen(now):
            missed = c.execute("select count(*) from messages where template = 'missed_slot'").fetchone()[0]
            assert missed == missed_before, "missed_slot ('text QUEUE') written while frozen"

    @precondition(lambda self: self.pausing and not self.paused)
    @rule(ticks=st.integers(1, 3))
    def pause(self, ticks):
        """Admin "freeze early" / pause (competition_frozen), independent of window_end (pausing machines only).
        Other rules (joins, calls, clock advances) keep running while paused; the admin lifts it after `ticks` ticks."""
        _cfg(self.conn, "competition_frozen", True)
        self.paused, self.pause_ticks = True, ticks

    @rule(dt=st.integers(1, 400))
    def advance_and_tick(self, dt):
        self.now += timedelta(seconds=dt)
        self.tick()

    @rule(mask=st.integers(1, 2 ** N_USERS - 1))
    def join_many(self, mask):
        for u in range(N_USERS):
            if mask >> u & 1:
                self.join(u)

    @rule(line=st.integers(0, 1), delay=st.integers(0, 120), dur=st.integers(0, 260), reps=st.integers(0, 3))
    def answer_claim(self, line, delay, dur, reps):
        """The claim holder FaceTimes after `delay` s (late answers hit the expiry), then the call ends."""
        lid = self.lines[line % len(self.lines)]
        holder = self.snap()["lines"][lid]["user_id"]
        if holder is None:
            return
        self.now += timedelta(seconds=delay)
        self.call_start(self.users.index(holder), line, "chert_meta")
        self.now += timedelta(seconds=dur)
        self.call_end(line, dur, reps)

    @rule(u=st.integers(0, N_USERS - 1))
    def join(self, u):
        uid, now = self.users[u], self.now
        s = self.snap()
        cl = s["clients"][uid]
        ct = self.calls_today(s, uid, now)
        if cl["banned"]:
            want = "banned"
        elif self.frozen(now):
            want = "frozen"
        elif any(q["user_id"] == uid for q in s["active"]) or any(
                l["user_id"] == uid and l["state"] == "claimed" for l in s["lines"].values()):
            want = "already"
        elif any(l["user_id"] == uid and l["state"] == "in_call" for l in s["lines"].values()):
            want = "in_call"
        elif ct >= CAP:
            want = "at_cap"
        else:
            want = "opted_out_ok" if cl["opted_out"] else "ok"
        r = self.st.rpc("ch_queue_join", {"p_user_id": uid, "p_now": now})
        assert r["reason"] == want, (r, want)
        assert r["calls_today"] == ct and r["calls_left"] == max(CAP - ct, 0)

    @rule(u=st.integers(0, N_USERS - 1), reason=st.sampled_from(["left", "stop"]))
    def leave(self, u, reason):
        uid = self.users[u]
        self.st.rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": reason, "p_now": self.now})
        s = self.snap()
        assert not any(q["user_id"] == uid for q in s["active"]), "LEAVE did not remove the entry immediately"
        assert not any(l["user_id"] == uid and l["state"] == "claimed" for l in s["lines"].values())

    @rule(u=st.integers(0, N_USERS - 1))
    def opt_out(self, u):
        uid = self.users[u]
        self.st.rpc("ch_set_opt", {"p_user_id": uid, "p_opted_out": True, "p_now": self.now})
        s = self.snap()
        assert not any(q["user_id"] == uid for q in s["active"]), "STOP did not remove the entry immediately"
        assert not any(l["user_id"] == uid and l["state"] == "claimed" for l in s["lines"].values())

    @rule(u=st.integers(0, N_USERS - 1))
    def opt_in(self, u):
        self.st.rpc("ch_set_opt", {"p_user_id": self.users[u], "p_opted_out": False, "p_now": self.now})

    @precondition(lambda self: not getattr(self, "_banned_once", False))
    @rule(u=st.integers(0, N_USERS - 1))
    def ban(self, u):
        self._banned_once = True
        r = self.st.rpc("ch_admin_ban", {"p_user_id": self.users[u], "p_reason": "property test", "p_actor": "t@x",
                                         "p_now": self.now})
        assert r["ok"]
        assert self.conn.execute("select banned_at from clients where id = %s", (self.users[u],)).fetchone()[0] == self.now

    @rule(u=st.integers(-1, N_USERS - 1), line=st.integers(0, 1),
          mode=st.sampled_from(["chert_meta", "chert_meta", "claim_window"]))
    def call_start(self, u, line, mode):
        now = self.now
        lid = self.lines[line % len(self.lines)]
        handle = self.handles[u] if u >= 0 else "+19998887777"  # -1 = unregistered caller
        s = self.snap()
        ls = s["lines"][lid]
        live_claim = ls["state"] == "claimed" and ls["claimed_until"] > now and ls["user_id"] is not None
        uid = None
        if self.frozen(now):
            want = "frozen"
        elif mode == "chert_meta":
            uid = self.users[u] if u >= 0 else None
            want = None if uid else "not_registered"
        else:
            uid = ls["user_id"] if live_claim else None
            want = None if uid else "not_your_turn"
        if want is None:
            others = [l for k, l in s["lines"].items() if k != lid and l["user_id"] == uid and (
                l["state"] == "in_call" or (l["state"] == "claimed" and l["claimed_until"] > now))]
            if s["clients"][uid]["banned"]:
                want = "banned"
            elif others:
                want = "not_your_turn"
            elif self.calls_today(s, uid, now) >= CAP:
                want = "at_cap"
            elif live_claim and ls["user_id"] == uid:
                want = "ok"
            elif mode == "chert_meta" and ls["state"] == "idle" and not any(
                    q["user_id"] != uid for q in s["active"]):
                want = "ok"
            else:
                want = "not_your_turn"
        cid = f"pc-{next(self.call_seq)}"
        self.stats["start:" + want] += 1
        r = self.st.rpc("ch_call_start", {"p_call_id": cid, "p_line_id": lid, "p_handle": handle, "p_mode": mode,
                                          "p_now": now})
        assert r["reason"] == want, (r, want, mode, ls)
        assert (r["decision"] == "accept") == (want == "ok")
        if want == "ok":
            after = self.snap()
            assert after["lines"][lid]["state"] == "in_call" and after["lines"][lid]["call_id"] == cid
            assert not any(q["user_id"] == uid for q in after["active"])
        assert self.st.rpc("ch_call_start", {"p_call_id": cid, "p_line_id": lid, "p_handle": handle, "p_mode": mode,
                                             "p_now": now}) == r, "call_start not idempotent"

    @rule(pick=st.integers(0, 50), dur=st.integers(0, 260), reps=st.integers(0, 3))
    def call_end(self, pick, dur, reps):
        live = [l for l in self.snap()["lines"].values() if l["state"] == "in_call"]
        if not live:
            return
        l = live[pick % len(live)]
        ended = min(l["in_call_since"] + timedelta(seconds=dur), self.now)
        r = self.st.rpc("ch_call_end", {"p_call_id": l["call_id"], "p_ended_at": ended, "p_count_end_at": None,
                                        "p_rep_count": reps, "p_now": self.now})
        want = reps >= 1 or (ended - l["in_call_since"]).total_seconds() >= MIN_COUNTED_S
        assert r["ok"] and r["counted_toward_cap"] == want

    # ------------------------------------------------------------------ invariants (after every step)
    @invariant()
    def state_invariants(self):
        s = self.snap()
        per_user: dict[str, list] = {}
        for q in s["active"]:
            per_user.setdefault(q["user_id"], []).append(q)
        for uid, qs in per_user.items():
            assert len(qs) <= 1, f"user {uid} holds {len(qs)} active entries"
        calls = {x["id"]: x for x in s["calls"]}
        for uid in self.users:
            held = self.holds(s, uid)
            assert len(held) <= 1, f"user claimed/in_call on two lines: {held}"
            qs = per_user.get(uid, [])
            states = [s["lines"][h]["state"] for h in held]
            if "in_call" in states:
                assert not qs, "in_call user still has an active queue entry"
            if "claimed" in states:
                assert all(q["status"] == "notified" and q["line_id"] == held[0] for q in qs), \
                    "claim holder has a waiting entry / entry for another line"
        for lid, l in s["lines"].items():
            if l["state"] == "claimed":
                assert l["user_id"] in per_user and per_user[l["user_id"]][0]["status"] == "notified", \
                    f"{lid} claimed without a notified entry"
                assert l["claimed_until"] - l["updated_at"] <= timedelta(seconds=CLAIM_S), "claim longer than window"
                if lid in self.claim_start:
                    assert l["claimed_until"] <= self.claim_start[lid] + timedelta(seconds=CLAIM_S)
            elif l["state"] == "in_call":
                call = calls.get(l["call_id"])
                assert call and call["decision"] == "accept" and call["line_id"] == lid and \
                    call["user_id"] == l["user_id"] and call["ended_at"] is None, f"{lid} in_call without live call"
            else:
                assert l["user_id"] is None and l["call_id"] is None
        for q in s["active"]:
            if q["status"] == "notified":
                l = s["lines"].get(q["line_id"])
                assert l and l["state"] == "claimed" and l["user_id"] == q["user_id"], "orphan notified entry"
        open_calls: dict[str, list[str]] = {}
        for x in s["calls"]:
            if x["decision"] == "accept" and x["ended_at"] is None:
                open_calls.setdefault(x["line_id"], []).append(x["id"])
        for lid in set(open_calls) | set(s["lines"]):
            ids = open_calls.get(lid, [])
            assert len(ids) <= 1, f"{lid} has {len(ids)} open accepted calls: {ids}"
            l = s["lines"].get(lid)
            assert (l is not None and l["state"] == "in_call") == bool(ids), \
                f"{lid} state={l and l['state']} but open accepted calls={ids}"
            if ids:
                assert l["call_id"] == ids[0], f"{lid} in_call with {l['call_id']} but open call is {ids[0]}"
        in_call_ids = [l["call_id"] for l in s["lines"].values() if l["state"] == "in_call"]
        assert len(in_call_ids) == len(set(in_call_ids)), "one call in_call on two lines"
        for x in s["calls"]:
            if x["decision"] == "reject":
                assert not x["counted"], "gatekeeper-rejected call counted toward cap"
            elif x["connected_at"] is not None:
                assert parse_ts(x["connected_at"]) < self.window_end, "call accepted at/after window_end"


class OneLine(SchedulerMachine):
    n_lines = 1


class TwoLines(SchedulerMachine):
    n_lines = 2


class OneLinePausing(SchedulerMachine):
    n_lines = 1
    pausing = True


class TwoLinesPausing(SchedulerMachine):
    n_lines = 2
    pausing = True


def status_of(c, qid: int) -> str:
    return c.execute("select status from queue where id = %s", (qid,)).fetchone()[0]


@pytest.mark.parametrize("machine", [OneLine, TwoLines], ids=["1-line", "2-lines"])
def test_scheduler_state_machine(pconn, machine):
    machine.conn = pconn
    machine.stats = Counter()
    run_state_machine_as_test(machine, settings=SETTINGS)
    st_ = machine.stats
    # guard against a vacuous pass: the generated runs must actually exercise the scheduler
    assert st_["examples"] >= 200, st_
    assert st_["pops"] >= 200 and st_["tiered_pops"] >= 10, st_
    assert all(st_["start:" + k] > 0 for k in ("ok", "not_your_turn", "at_cap", "banned", "frozen", "not_registered")), st_
    assert st_["closed_ticks"] > 0, st_


@pytest.mark.parametrize("machine", [OneLinePausing, TwoLinesPausing], ids=["1-line", "2-lines"])
def test_scheduler_state_machine_with_admin_pause(pconn, machine):
    """Same machine plus the admin pause (competition_frozen toggled on and off): a pause stops popping but never
    closes the queue; only window_end does (C7.s)."""
    machine.conn = pconn
    machine.stats = Counter()
    run_state_machine_as_test(machine, settings=SETTINGS)
    st_ = machine.stats
    assert st_["examples"] >= 200, st_
    assert st_["pops"] >= 100 and st_["paused_ticks"] >= 50 and st_["closed_ticks"] > 0, st_
    assert st_["pause_requeued"] > 0, st_


def test_youre_up_not_starved_by_bulk_texts(pconn, db):
    """Found by scripts/simulate.py (seed 1, Sun 20:00 ET): a pop that lands during a bulk send (power-hour start +
    ending-soon to every user at outbound_rate_per_min=20) queued its 'you're up' FIFO behind ~130 texts; it went
    out 158 s later, after the 90 s claim had expired, so the user lost the slot without ever being told in time.
    'you're up' must be claimed ahead of already-due bulk rows (the youre_up comes from a real pop, so its claim is
    live: C7.s suppresses youre_up rows whose claim is gone)."""
    from challenge.config import Config
    from challenge.messaging.outbox import Outbox
    from challenge.messaging.providers import MockProvider
    from challenge.store import PgStore

    c = pconn
    c.execute("truncate clients, messages restart identity cascade")
    _cfg(c, "outbound_rate_per_min", 20)
    coach = c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,'b','burst_1',%s)"
                    " returning id", (coach, BASE)).fetchone()[0]
    c.execute("insert into client_handles (handle, client_id, kind, linked_via) values ('+17770009999',%s,'phone','join')",
              (uid,))
    now = datetime(2026, 10, 18, 20, 0, tzinfo=ET)
    st_ = ConnStore(c)
    for k in range(60):  # bulk proactive texts already due
        st_.rpc("ch_outbox_enqueue", {"p_handle": "+17770009999", "p_user_id": str(uid), "p_template": "ph_start",
                                      "p_body": None, "p_media_url": None, "p_dedupe_key": f"bulk:{k}",
                                      "p_not_before": now, "p_now": now, "p_ctx": {"power_hour": "8–9 PM"}})
    c.execute("delete from line_state where line_id <> 'line-1'")
    c.execute("delete from lines where id <> 'line-1'")
    c.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null, offline_until=null,"
              " in_call_since=null, updated_at=now()")
    _cfg(c, "competition_frozen", False)
    _cfg(c, "window_end", "2026-10-18T23:59:59-04:00")
    assert st_.rpc("ch_queue_join", {"p_user_id": str(uid), "p_now": now})["ok"]
    assert len(st_.rpc("ch_tick", {"p_now": now + timedelta(seconds=1)})["claims"]) == 1  # queues the 'youre_up'
    clock = {"t": now}
    provider = MockProvider()
    store = PgStore(db)
    ob = Outbox(store, Config(store, ttl_s=0), provider, clock=lambda: clock["t"])
    t = now
    while t < now + timedelta(seconds=CLAIM_S):
        clock["t"] = t
        ob.run_once(t)
        if any(s["body"].startswith("You're up!") for s in provider.sent):
            break
        t += timedelta(seconds=2)
    assert any(s["body"].startswith("You're up!") for s in provider.sent), \
        f"'you're up' not delivered within the {CLAIM_S}s claim window ({len(provider.sent)} bulk texts went first)"
    c.execute("truncate clients, messages restart identity cascade")


def test_freeze_closes_queue(pconn):
    """Found by scripts/simulate.py (seed 1): SPEC §7 'Freeze at window_end: stop popping, close queue'. A user
    still waiting at window_end stayed 'waiting' forever (shown in the queue / line status, never resolved)."""
    c = pconn
    st_ = ConnStore(c)
    c.execute("truncate clients, calls, messages, audit_log restart identity cascade")
    c.execute("update line_state set state='in_call', user_id=null, call_id='busy', in_call_since=%s, updated_at=now()"
              " where line_id='line-1'", (BASE,))
    end = BASE + timedelta(minutes=30)
    _cfg(c, "window_end", end.isoformat())
    coach = c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,'w','waiter_1',%s)"
                    " returning id", (coach, BASE - timedelta(days=1))).fetchone()[0]
    assert st_.rpc("ch_queue_join", {"p_user_id": str(uid), "p_now": BASE})["reason"] == "ok"
    st_.rpc("ch_tick", {"p_now": end + timedelta(seconds=1)})
    st_.rpc("ch_tick", {"p_now": end + timedelta(hours=1)})
    left = c.execute("select status from queue where user_id=%s", (uid,)).fetchall()
    assert left == [("expired",)], f"queue not closed at freeze: {left}"
    c.execute("update line_state set state='idle', user_id=null, call_id=null, in_call_since=null where line_id='line-1'")
    c.execute("truncate clients, calls, messages, audit_log restart identity cascade")
