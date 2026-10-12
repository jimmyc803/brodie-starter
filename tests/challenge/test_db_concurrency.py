"""Concurrency: 20 threads hammer ch_queue_join / ch_call_start / ch_call_end / ch_commit_reps / ch_tick /
ch_queue_leave at once; line/queue invariants must hold throughout and at the end, with no deadlocks or lost updates."""
from __future__ import annotations

import itertools
import random
import threading
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

from challenge.store import PgStore
from db.test.harness import connect

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 14, 9, 0, tzinfo=ET)
THREADS = 20
OPS_PER_THREAD = 40
USERS = 14


def _setup(conn) -> list[tuple[uuid.UUID, str]]:
    conn.execute("insert into lines (id, chert_agent_name) values ('line-2', 'brodie2') on conflict do nothing")
    conn.execute("insert into line_state (line_id, state, updated_at) values ('line-2', 'idle', now())"
                 " on conflict do nothing")
    # short timers so claims expire, calls time out and lines cycle within the run
    for k, v in [("claim_window_s", 20), ("line_offline_gap_s", 15), ("call_count_s", 40), ("call_reveal_s", 5),
                 ("in_call_timeout_extra_s", 10), ("daily_call_cap", 3), ("min_counted_call_s", 5)]:
        conn.execute("update competition_config set value=%s where key=%s", (Jsonb(v), k))
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    users = []
    for i in range(USERS):
        uid = conn.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s)"
                           " returning id", (coach, f"cc_{i}", f"cc_{i}", T0 - timedelta(days=1))).fetchone()[0]
        handle = f"+1666{i:07d}"
        conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
                     (handle, uid))
        users.append((uid, handle))
    return users


INVARIANTS = {
    # a user is in at most one of {waiting entry, claim holder, in_call} across all lines
    "user_single_slot": """
        select u from (
          select user_id as u from line_state where state in ('claimed','in_call') and user_id is not null
          union all select user_id from queue where status = 'waiting') x
        group by u having count(*) > 1""",
    "one_active_entry": "select user_id from queue where status in ('waiting','notified') group by user_id having count(*) > 1",
    # notified entry <=> holder of the claimed line it points at
    "notified_has_claim": """
        select q.id from queue q where q.status = 'notified' and not exists (
          select 1 from line_state l where l.state = 'claimed' and l.user_id = q.user_id and l.line_id = q.line_id)""",
    "claim_has_notified": """
        select l.line_id from line_state l where l.state = 'claimed' and not exists (
          select 1 from queue q where q.status = 'notified' and q.user_id = l.user_id and q.line_id = l.line_id)""",
    # in_call line points at its accepted, still-open call
    "in_call_matches_call": """
        select l.line_id from line_state l where l.state = 'in_call' and not exists (
          select 1 from calls c where c.id = l.call_id and c.decision = 'accept' and c.user_id = l.user_id
                                  and c.line_id = l.line_id and c.ended_at is null)""",
    # <= 1 open accepted call per line, and an open call always holds its line
    "one_open_call_per_line": """
        select line_id from calls where decision = 'accept' and ended_at is null group by line_id having count(*) > 1""",
    "open_call_holds_line": """
        select c.id from calls c where c.decision = 'accept' and c.ended_at is null and not exists (
          select 1 from line_state l where l.line_id = c.line_id and l.state = 'in_call' and l.call_id = c.id)""",
    # no lost updates: every line transition bumped version exactly once and was audited exactly once
    "version_matches_audit": """
        select l.line_id from line_state l
        where l.version <> (select count(*) from audit_log a where a.target = l.line_id and a.action like 'line:%')""",
    "accepts_match_transitions": """
        select 1 where (select count(*) from calls where decision = 'accept')
                    <> (select count(*) from audit_log where action like 'line:%->in_call')""",
    "one_youre_up_per_pop": """
        select 1 where (select count(*) from messages where template = 'youre_up')
                    <> (select count(*) from audit_log where action = 'queue:waiting->notified')""",
}


def _violations(dsn) -> dict[str, list]:
    with psycopg.connect(dsn, autocommit=False) as c:
        c.execute("set transaction isolation level repeatable read")
        out = {name: c.execute(sql).fetchall() for name, sql in INVARIANTS.items()}
        c.rollback()
    return {k: v for k, v in out.items() if v}


def test_concurrent_rpcs_keep_invariants(db):
    with connect(db) as conn:
        users = _setup(conn)
    store = PgStore(db)
    clock = itertools.count()
    clock_lock = threading.Lock()
    accepted: list[str] = []
    acc_lock = threading.Lock()
    errors: list[str] = []
    snapshots: list[dict] = []
    stop = threading.Event()
    barrier = threading.Barrier(THREADS + 1)
    counts = {"accept": 0, "reject": 0, "claims": 0, "timeouts": 0}

    def now() -> datetime:
        with clock_lock:
            return T0 + timedelta(seconds=2 * next(clock))

    def worker(seed: int) -> None:
        rnd = random.Random(seed)
        barrier.wait()
        for _ in range(OPS_PER_THREAD):
            uid, handle = rnd.choice(users)
            op = rnd.choices(["join", "start", "end", "commit", "tick", "leave"], [5, 5, 3, 2, 4, 1])[0]
            try:
                if op == "join":
                    store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": now()})
                elif op == "start":
                    call_id = f"cc-{uuid.uuid4().hex[:12]}"
                    mode = "claim_window" if rnd.random() < 0.2 else "chert_meta"
                    r = store.rpc("ch_call_start", {"p_call_id": call_id, "p_line_id": rnd.choice(["line-1", "line-2"]),
                                                    "p_handle": handle, "p_mode": mode, "p_now": now()})
                    with acc_lock:
                        counts[r["decision"]] += 1
                        if r["decision"] == "accept":
                            accepted.append(call_id)
                    # duplicate delivery of the same call_id is idempotent
                    r2 = store.rpc("ch_call_start", {"p_call_id": call_id, "p_line_id": "line-1",
                                                     "p_handle": handle, "p_mode": mode, "p_now": now()})
                    assert r2 == r, (r, r2)
                elif op in ("end", "commit"):
                    with acc_lock:
                        call_id = rnd.choice(accepted) if accepted else None
                    if call_id is None:
                        continue
                    t = now()
                    if op == "end":
                        store.rpc("ch_call_end", {"p_call_id": call_id, "p_ended_at": t, "p_count_end_at": None,
                                                  "p_rep_count": rnd.randint(0, 3), "p_now": t})
                    else:
                        reps = [{"n": i, "t": float(i), "at": t - timedelta(seconds=30 - i), "valid": True}
                                for i in range(1, rnd.randint(1, 4))]
                        store.rpc("ch_commit_reps", {"p_call_id": call_id, "p_now": t, "p_payload": {
                            "started_at": None, "ended_at": t, "liveness_result": "pass", "reps": reps}})
                elif op == "tick":
                    r = store.rpc("ch_tick", {"p_now": now()})
                    with acc_lock:
                        counts["claims"] += len(r["claims"])
                        counts["timeouts"] += len(r["timeouts"])
                else:
                    store.rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": "left", "p_now": now()})
            except Exception as e:  # noqa: BLE001 - every failure (deadlock, unique violation, assert) is collected
                errors.append(f"{op}: {e!r}")

    def checker() -> None:
        barrier.wait()
        while not stop.is_set():
            v = _violations(db)
            if v:
                snapshots.append(v)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(THREADS)]
    chk = threading.Thread(target=checker)
    for t in threads:
        t.start()
    chk.start()
    for t in threads:
        t.join(timeout=300)
    stop.set()
    chk.join(timeout=60)

    assert not any(t.is_alive() for t in threads), "worker hung (possible deadlock)"
    assert errors == []
    assert snapshots == []
    assert _violations(db) == {}

    # the run actually exercised the state machine
    assert counts["accept"] > 0 and counts["reject"] > 0 and counts["claims"] > 0, counts

    # every committed call has exactly one session, and repeated commits created no duplicate reps
    with connect(db) as conn:
        assert conn.execute("select count(*) from calls where session_id is not null").fetchone()[0] == \
            conn.execute("select count(*) from sessions").fetchone()[0]
        assert conn.execute("select count(*) from (select set_id, rep_number from reps group by 1, 2"
                            " having count(*) > 1) d").fetchone()[0] == 0
        # drain: ticking far ahead ends every call and frees every line, invariants still hold
        store.rpc("ch_tick", {"p_now": T0 + timedelta(hours=2)})
        store.rpc("ch_tick", {"p_now": T0 + timedelta(hours=2, minutes=1)})
        assert conn.execute("select count(*) from calls where decision='accept' and ended_at is null").fetchone()[0] == 0
    assert _violations(db) == {}
