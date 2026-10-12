"""Migration 20261013_challenge_calls.sql: call lifecycle, line state machine, queue RPCs, commit scoring."""
from __future__ import annotations

import itertools
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from challenge.store import PgStore
from db.test.harness import MIGRATIONS, connect

ET = ZoneInfo("America/New_York")
MIGRATION = MIGRATIONS / "20261013_challenge_calls.sql"
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=ET)
_seq = itertools.count(1)


def et(*args) -> datetime:
    return datetime(*args, tzinfo=ET)


@pytest.fixture
def st(db, conn):
    """Clean competition state per test; returns PgStore. Config is restored afterwards."""
    cfg = conn.execute("select key, value from competition_config").fetchall()
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending restart identity cascade")
    conn.execute("delete from line_state where line_id <> 'line-1'")
    conn.execute("delete from lines where id <> 'line-1'")
    conn.execute("update lines set active = true")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    yield PgStore(db)
    for k, v in cfg:
        conn.execute("update competition_config set value=%s where key=%s", (_jb(v), k))


def _jb(v):
    from psycopg.types.json import Jsonb
    return Jsonb(v)


def set_cfg(conn, key, value):
    conn.execute("update competition_config set value=%s where key=%s", (_jb(value), key))


def user(conn, name: str | None = None, *, phone: bool = True, email: bool = False) -> tuple[uuid.UUID, str]:
    n = next(_seq)
    name = name or f"user_{n}"
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = conn.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s) returning id",
                       (coach, name, name, et(2026, 10, 12, 12, 0))).fetchone()[0]
    handle = f"+1555{n:07d}"
    if email:
        conn.execute("insert into client_handles (handle, client_id, kind, linked_via, created_at)"
                     " values (%s,%s,'email','join', '2026-01-01')", (f"{name}@x.test", uid))
    if phone:
        conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
                     (handle, uid))
    return uid, handle


def cid() -> str:
    return f"call-{uuid.uuid4().hex[:10]}"


def start(st, handle, now, *, call_id=None, line="line-1", mode="chert_meta"):
    call_id = call_id or cid()
    r = st.rpc("ch_call_start", {"p_call_id": call_id, "p_line_id": line, "p_handle": handle, "p_mode": mode,
                                 "p_now": now})
    return call_id, r


def end(st, call_id, ended_at, rep_count=0, now=None):
    return st.rpc("ch_call_end", {"p_call_id": call_id, "p_ended_at": ended_at, "p_count_end_at": None,
                                  "p_rep_count": rep_count, "p_now": now or ended_at})


def tick(st, now):
    return st.rpc("ch_tick", {"p_now": now})


def join(st, uid, now):
    return st.rpc("ch_queue_join", {"p_user_id": uid, "p_now": now})


def line(conn, line_id="line-1"):
    return conn.execute("select state, user_id, call_id, claimed_until, offline_until, in_call_since, version"
                        " from line_state where line_id=%s", (line_id,)).fetchone()


def full_call(st, handle, at, dur_s=195, reps=0):
    """Walk-in call at `at` lasting dur_s, then tick the line back to idle; returns (call_id, idle_at)."""
    call_id, r = start(st, handle, at)
    assert r["decision"] == "accept", r
    end(st, call_id, at + timedelta(seconds=dur_s), reps)
    idle_at = at + timedelta(seconds=dur_s + 180)
    tick(st, idle_at)
    return call_id, idle_at


def commit(st, call_id, reps, now, liveness="pass", started_at=None):
    return st.rpc("ch_commit_reps", {"p_call_id": call_id, "p_now": now, "p_payload": {
        "started_at": started_at, "ended_at": None, "liveness_result": liveness, "judge_version": "j1", "reps": reps}})


def rep(n, at, valid=True, **kw):
    return {"n": n, "t": float(n), "at": at, "valid": valid, "reject_reasons": kw.pop("reject_reasons", []),
            "faults": [], "in_challenge": kw.pop("in_challenge", False), "min_elbow_deg_l": 80.5,
            "classifier_labels": ["pushups - correct"], "persons_in_frame": 1, "torso_ok": True, "side": "left", **kw}


# ---------------------------------------------------------------- migration / grants

def test_migration_applies_twice(pg_cluster, db, st):
    name = db.split("dbname=")[1].split()[0]
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)


@pytest.mark.parametrize("fn", ["ch_call_start(text,text,text,text,timestamptz)",
                                "ch_call_end(text,timestamptz,timestamptz,int,timestamptz)",
                                "ch_commit_reps(text,jsonb,timestamptz)", "ch_tick(timestamptz)",
                                "ch_queue_join(uuid,timestamptz)", "ch_queue_leave(uuid,text,timestamptz)",
                                "ch_queue_view(timestamptz)", "ch_calls_line_set(text,text,uuid,text,timestamptz,"
                                "timestamptz,timestamptz,timestamptz,text)"])
def test_execute_service_role_only(conn, fn):
    for role, ok in [("anon", False), ("authenticated", False), ("service_role", True)]:
        assert conn.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn)).fetchone()[0] is ok, role
    assert conn.execute("select prosecdef from pg_proc where oid = %s::regprocedure", (fn,)).fetchone()[0]


# ---------------------------------------------------------------- call start

def test_walk_in_accept_chert_meta(st, conn):
    uid, h = user(conn)
    call_id, r = start(st, h, T0)
    assert r == {"decision": "accept", "user_id": str(uid), "reason": "ok", "cue": None}
    s = line(conn)
    assert (s[0], s[1], s[2], s[5]) == ("in_call", uid, call_id, T0)
    assert s[6] == 1
    assert conn.execute("select action, actor from audit_log where target='line-1'").fetchall() == \
        [("line:idle->in_call", "system")]
    row = conn.execute("select decision, user_id, handle_raw, connected_at from calls where id=%s", (call_id,)).fetchone()
    assert row == ("accept", uid, h, T0)
    # idempotent on call_id: stored decision, no new transition
    assert start(st, h, T0 + timedelta(seconds=5), call_id=call_id)[1] == r
    assert line(conn)[6] == 1


def test_walk_in_rejected_in_claim_window_mode(st, conn):
    _, h = user(conn)
    call_id, r = start(st, h, T0, mode="claim_window")
    assert r == {"decision": "reject", "user_id": None, "reason": "not_your_turn", "cue": "not_your_turn"}
    assert line(conn)[0] == "idle"
    assert conn.execute("select decision, reject_reason, counted_toward_cap from calls where id=%s",
                        (call_id,)).fetchone() == ("reject", "not_your_turn", False)


def test_unregistered_and_inactive_line_and_window(st, conn):
    _, h = user(conn)
    assert start(st, "+19999999999", T0)[1] == {"decision": "reject", "user_id": None, "reason": "not_registered",
                                                "cue": "not_signed_up"}
    assert start(st, h, T0, line="nope")[1]["reason"] == "line_inactive"
    r = start(st, h, et(2026, 10, 12, 19, 59, 59))[1]
    assert (r["reason"], r["cue"]) == ("not_started", "competition_over")
    r = start(st, h, et(2026, 10, 18, 23, 59, 59))[1]
    assert (r["reason"], r["cue"]) == ("frozen", "competition_over")
    set_cfg(conn, "competition_frozen", True)
    assert start(st, h, T0)[1]["reason"] == "frozen"
    set_cfg(conn, "competition_frozen", False)
    assert line(conn)[0] == "idle"


def test_banned_rejected(st, conn):
    uid, h = user(conn)
    conn.execute("update clients set banned_at=now() where id=%s", (uid,))
    r = start(st, h, T0)[1]
    assert (r["decision"], r["reason"], r["cue"]) == ("reject", "banned", "not_your_turn")


def test_walk_in_blocked_when_someone_waiting(st, conn):
    a, _ = user(conn)
    _, hb = user(conn)
    assert join(st, a, T0)["reason"] == "ok"
    assert start(st, hb, T0 + timedelta(seconds=1))[1]["reason"] == "not_your_turn"


def test_claim_holder_accept_other_rejected(st, conn):
    a, ha = user(conn)
    b, hb = user(conn)
    j = join(st, a, T0)
    assert (j["ok"], j["reason"], j["position"], j["calls_today"], j["calls_left"], j["line_open"]) == \
        (True, "ok", 1, 0, 5, True)
    t = tick(st, T0 + timedelta(seconds=1))
    qa = conn.execute("select id from queue where user_id=%s", (a,)).fetchone()[0]
    [cl] = t["claims"]
    assert (cl["line_id"], cl["user_id"], cl["queue_id"]) == ("line-1", str(a), qa)
    assert datetime.fromisoformat(cl["claimed_until"]) == T0 + timedelta(seconds=91)
    assert line(conn)[:2] == ("claimed", a)
    assert start(st, hb, T0 + timedelta(seconds=10))[1]["reason"] == "not_your_turn"
    call_id, r = start(st, ha, T0 + timedelta(seconds=20))
    assert (r["decision"], r["user_id"]) == ("accept", str(a))
    assert conn.execute("select status, line_id from queue where id=%s", (qa,)).fetchone() == ("connected", "line-1")
    assert line(conn)[:3] == ("in_call", a, call_id)
    actions = [x for (x,) in conn.execute("select action from audit_log where target='line-1' order by id")]
    assert actions == ["line:idle->claimed", "line:claimed->in_call"]


def test_claim_window_mode_attributes_to_holder(st, conn):
    a, _ = user(conn)
    join(st, a, T0)
    tick(st, T0)
    call_id, r = start(st, None, T0 + timedelta(seconds=5), mode="claim_window")
    assert (r["decision"], r["user_id"]) == ("accept", str(a))
    assert conn.execute("select user_id from calls where id=%s", (call_id,)).fetchone()[0] == a


def test_expired_claim_not_honoured_before_tick(st, conn):
    a, ha = user(conn)
    join(st, a, T0)
    tick(st, T0)
    assert start(st, ha, T0 + timedelta(seconds=90))[1]["reason"] == "not_your_turn"


def test_at_cap_after_five_counted_calls_and_reset_after_et_midnight(st, conn):
    uid, h = user(conn)
    at = et(2026, 10, 13, 22, 30)
    for _ in range(5):
        _, at = full_call(st, h, at, dur_s=60)
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, at)).fetchone()[0] == 5
    r = start(st, h, et(2026, 10, 13, 23, 59, 59))[1]
    assert (r["decision"], r["reason"], r["cue"]) == ("reject", "at_cap", "at_cap")
    j = join(st, uid, et(2026, 10, 13, 23, 59, 59))
    assert (j["ok"], j["reason"], j["calls_left"]) == (False, "at_cap", 0)
    r = start(st, h, et(2026, 10, 14, 0, 0, 0))[1]
    assert (r["decision"], r["reason"]) == ("accept", "ok")


def test_short_call_not_counted_rep_call_counted(st, conn):
    uid, h = user(conn)
    c1, _ = start(st, h, T0)
    assert end(st, c1, T0 + timedelta(seconds=29), 0) == {"ok": True, "counted_toward_cap": False}
    s = line(conn)
    assert s[0] == "offline" and s[4] == T0 + timedelta(seconds=29 + 180)
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, T0)).fetchone()[0] == 0
    tick(st, T0 + timedelta(seconds=300))
    c2, _ = start(st, h, T0 + timedelta(seconds=301))
    assert end(st, c2, T0 + timedelta(seconds=310), 1)["counted_toward_cap"] is True
    # idempotent end
    assert end(st, c2, T0 + timedelta(seconds=310), 1)["counted_toward_cap"] is True
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, T0)).fetchone()[0] == 1
    assert end(st, "nope", T0)["ok"] is False


def test_rejected_call_end_and_commit(st, conn):
    _, h = user(conn)
    c, _ = start(st, h, T0, mode="claim_window")
    assert end(st, c, T0 + timedelta(seconds=60), 3)["counted_toward_cap"] is False
    assert commit(st, c, [rep(1, T0)], T0) == {"ok": False, "reason": "not_accepted"}
    assert conn.execute("select counted_toward_cap, session_id from calls where id=%s", (c,)).fetchone() == (False, None)


# ---------------------------------------------------------------- tick

def test_claim_expiry_no_show_idle_and_next_pop_same_tick(st, conn):
    a, ha = user(conn)
    b, hb = user(conn, email=True)
    join(st, a, T0)
    join(st, b, T0 + timedelta(seconds=1))
    t1 = tick(st, T0 + timedelta(seconds=2))
    qa, qb = [r[0] for r in conn.execute("select id from queue order by id")]
    assert [c["user_id"] for c in t1["claims"]] == [str(a)]
    assert tick(st, T0 + timedelta(seconds=91)) == {"no_shows": [], "claims": [], "timeouts": [], "idled": []}
    t2 = tick(st, T0 + timedelta(seconds=92))
    assert t2["no_shows"] == [{"user_id": str(a), "queue_id": qa}]
    assert [(c["user_id"], c["queue_id"]) for c in t2["claims"]] == [(str(b), qb)]
    assert t2["idled"] == ["line-1"]
    assert line(conn)[:2] == ("claimed", b)
    assert line(conn)[3] == T0 + timedelta(seconds=92 + 90)
    assert conn.execute("select status from queue where id=%s", (qa,)).fetchone()[0] == "no_show"
    assert conn.execute("select status, notified_at, line_id from queue where id=%s", (qb,)).fetchone() == \
        ("notified", T0 + timedelta(seconds=92), "line-1")
    msgs = conn.execute("select direction, status, template, dedupe_key, handle, user_id, ctx, body from messages"
                        " order by id").fetchall()
    assert [(m[2], m[3], m[4], m[5]) for m in msgs] == [
        ("youre_up", f"youre_up:{qa}", ha, a), ("missed_slot", f"missed_slot:{qa}", ha, a),
        ("youre_up", f"youre_up:{qb}", hb, b)]  # b prefers the phone handle over the older email one
    assert all(m[0] == "out" and m[1] == "queued" and m[7] is None for m in msgs)
    assert msgs[0][6]["claim_window_s"] == 90 and msgs[0][6]["line_id"] == "line-1"
    actions = [x for (x,) in conn.execute("select action from audit_log where target='line-1' order by id")]
    assert actions == ["line:idle->claimed", "line:claimed->idle", "line:idle->claimed"]
    assert line(conn)[6] == 3


def test_no_outbox_for_user_without_handle(st, conn):
    a, _ = user(conn, phone=False)
    join(st, a, T0)
    assert tick(st, T0)["claims"][0]["user_id"] == str(a)
    assert conn.execute("select count(*) from messages").fetchone()[0] == 0


def test_offline_to_idle_then_pop(st, conn):
    a, ha = user(conn)
    b, _ = user(conn)
    c, _ = start(st, ha, T0)
    assert join(st, b, T0 + timedelta(seconds=10))["line_open"] is False
    end(st, c, T0 + timedelta(seconds=195), 10)
    assert line(conn)[0] == "offline"
    assert tick(st, T0 + timedelta(seconds=374))["claims"] == []
    t = tick(st, T0 + timedelta(seconds=375))
    assert t["idled"] == ["line-1"]
    assert [x["user_id"] for x in t["claims"]] == [str(b)]
    actions = [x for (x,) in conn.execute("select action from audit_log where target='line-1' order by id")]
    assert actions == ["line:idle->in_call", "line:in_call->offline", "line:offline->idle", "line:idle->claimed"]


def test_in_call_timeout_finalizes_then_end_reconciles(st, conn):
    uid, h = user(conn)
    c, _ = start(st, h, T0)
    assert tick(st, T0 + timedelta(seconds=254))["timeouts"] == []
    t = tick(st, T0 + timedelta(seconds=255))
    assert t["timeouts"] == [c]
    s = line(conn)
    assert (s[0], s[1], s[2], s[4]) == ("offline", None, None, T0 + timedelta(seconds=255 + 180))
    assert conn.execute("select ended_at, counted_toward_cap from calls where id=%s", (c,)).fetchone() == \
        (T0 + timedelta(seconds=195), True)
    # late end from the worker: reconciles, line untouched, never double counts
    v = line(conn)[6]
    assert end(st, c, T0 + timedelta(seconds=190), 4, now=T0 + timedelta(seconds=300))["counted_toward_cap"] is True
    assert line(conn)[6] == v
    assert conn.execute("select ended_at, rep_count from calls where id=%s", (c,)).fetchone() == \
        (T0 + timedelta(seconds=190), 4)
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, T0)).fetchone()[0] == 1


def test_priority_calls_today_then_fifo(st, conn):
    a, ha = user(conn)
    b, _ = user(conn)
    c, _ = user(conn)
    at = T0
    for _ in range(2):
        _, at = full_call(st, ha, at, dur_s=60)
    join(st, a, at)
    join(st, b, at + timedelta(seconds=1))
    join(st, c, at + timedelta(seconds=2))
    view = st.rpc("ch_queue_view", {"p_now": at + timedelta(seconds=3)})
    assert [(q["user_id"], q["position"], q["calls_today"]) for q in view["queue"]] == \
        [(str(b), 1, 0), (str(c), 2, 0), (str(a), 3, 2)]
    assert view["lines"][0]["state"] == "idle"
    assert view["avg_cycle_s"] == 60 + 180
    assert join(st, a, at + timedelta(seconds=3))["position"] == 3
    order = []
    now = at + timedelta(seconds=3)
    for _ in range(3):
        order.append(tick(st, now)["claims"][0]["user_id"])
        now += timedelta(seconds=90)
    assert order == [str(b), str(c), str(a)]


def test_multi_line_pops_distinct_users(st, conn):
    conn.execute("insert into lines (id, chert_agent_name) values ('line-2', 'brodie2')")
    conn.execute("insert into line_state (line_id, state, updated_at) values ('line-2', 'idle', now())")
    a, _ = user(conn)
    b, _ = user(conn)
    join(st, a, T0)
    join(st, b, T0 + timedelta(seconds=1))
    t = tick(st, T0 + timedelta(seconds=2))
    assert [(x["line_id"], x["user_id"]) for x in t["claims"]] == [("line-1", str(a)), ("line-2", str(b))]
    assert tick(st, T0 + timedelta(seconds=3))["claims"] == []


def test_ineligible_waiting_expired_and_skipped(st, conn):
    a, _ = user(conn)
    b, _ = user(conn)
    join(st, a, T0)
    join(st, b, T0 + timedelta(seconds=1))
    conn.execute("update clients set banned_at=now() where id=%s", (a,))
    t = tick(st, T0 + timedelta(seconds=2))
    assert [x["user_id"] for x in t["claims"]] == [str(b)]
    assert conn.execute("select status from queue where user_id=%s", (a,)).fetchone()[0] == "expired"


def test_no_pops_after_window_end_or_before_start(st, conn):
    a, _ = user(conn)
    join(st, a, et(2026, 10, 12, 19, 0))
    assert tick(st, et(2026, 10, 12, 19, 59, 59))["claims"] == []
    end_ts = et(2026, 10, 18, 23, 59, 59)
    assert tick(st, end_ts)["claims"] == []
    assert conn.execute("select status from queue where user_id=%s", (a,)).fetchone()[0] == "waiting"
    b, _ = user(conn)
    assert join(st, b, end_ts)["reason"] == "frozen"
    set_cfg(conn, "competition_frozen", True)
    assert tick(st, T0)["claims"] == []
    set_cfg(conn, "competition_frozen", False)
    assert tick(st, T0)["claims"][0]["user_id"] == str(a)


# ---------------------------------------------------------------- queue join / leave

def test_queue_join_reasons(st, conn):
    a, ha = user(conn)
    assert join(st, uuid.uuid4(), T0)["reason"] == "not_registered"
    assert join(st, a, T0)["reason"] == "ok"
    r = join(st, a, T0 + timedelta(seconds=1))
    assert (r["ok"], r["reason"], r["position"]) == (True, "already", 1)
    tick(st, T0 + timedelta(seconds=2))
    assert join(st, a, T0 + timedelta(seconds=3))["reason"] == "already"
    start(st, ha, T0 + timedelta(seconds=4))
    assert join(st, a, T0 + timedelta(seconds=5))["reason"] == "in_call"
    b, _ = user(conn)
    conn.execute("update clients set opted_out_at=now() where id=%s", (b,))
    r = join(st, b, T0)
    assert (r["ok"], r["reason"]) == (True, "opted_out_ok")
    assert conn.execute("select opted_out_at from clients where id=%s", (b,)).fetchone()[0] is None
    c, _ = user(conn)
    conn.execute("update clients set banned_at=now() where id=%s", (c,))
    assert join(st, c, T0)["reason"] == "banned"


def test_leave_releases_claim(st, conn):
    a, _ = user(conn)
    assert st.rpc("ch_queue_leave", {"p_user_id": a, "p_reason": "left", "p_now": T0}) == \
        {"ok": True, "was_queued": False}
    join(st, a, T0)
    tick(st, T0)
    assert st.rpc("ch_queue_leave", {"p_user_id": a, "p_reason": "stop", "p_now": T0 + timedelta(seconds=5)}) == \
        {"ok": True, "was_queued": True}
    assert line(conn)[:2] == ("idle", None)
    assert conn.execute("select status from queue where user_id=%s", (a,)).fetchone()[0] == "left"


# ---------------------------------------------------------------- commit + scoring

def _reps_rows(conn, call_id):
    return conn.execute(
        "select r.rep_number, r.valid, r.multiplier, r.points, r.reject_reasons, r.at from calls c"
        " join sets s on s.session_id=c.session_id join reps r on r.set_id=s.id where c.id=%s order by r.rep_number",
        (call_id,)).fetchall()


def test_commit_idempotent_and_metrics_stored(st, conn):
    uid, h = user(conn)
    c, _ = start(st, h, T0)
    reps = [rep(1, T0 + timedelta(seconds=10)), rep(2, T0 + timedelta(seconds=12), valid=False,
                                                     reject_reasons=["depth"]),
            rep(3, T0 + timedelta(seconds=14), in_challenge=True)]
    r1 = commit(st, c, reps, T0 + timedelta(seconds=200))
    assert (r1["ok"], r1["valid_reps"], r1["points"], r1["already"]) == (True, 1, 1, False)
    r2 = commit(st, c, reps, T0 + timedelta(seconds=210))
    assert r2 == {**r1, "already": True}
    assert conn.execute("select count(*) from reps").fetchone()[0] == 3
    assert conn.execute("select count(*) from sessions").fetchone()[0] == 1
    rows = _reps_rows(conn, c)
    assert [(x[1], x[3], x[4]) for x in rows] == [(True, 1, []), (False, 0, ["depth"]), (False, 0, [])]
    m = conn.execute("select r.min_elbow_deg_l, r.classifier_labels, r.persons_in_frame, r.torso_ok, r.side,"
                     " r.judge_version, r.t, r.in_challenge from reps r where rep_number=1").fetchone()
    assert m == (80.5, ["pushups - correct"], 1, True, "left", "j1", 1.0, False)
    s = conn.execute("select s.client_id, st.completed_reps, st.exercise_key, st.set_number from calls c"
                     " join sessions s on s.id=c.session_id join sets st on st.session_id=s.id where c.id=%s",
                     (c,)).fetchone()
    assert s == (uid, 1, "pushups", 1)
    # commit before end: counted via rep_count; end afterwards keeps it consistent
    assert conn.execute("select rep_count, counted_toward_cap, committed_at from calls where id=%s", (c,)).fetchone() == \
        (3, True, T0 + timedelta(seconds=200))
    assert end(st, c, T0 + timedelta(seconds=20), 0)["counted_toward_cap"] is True
    assert conn.execute("select rep_count from calls where id=%s", (c,)).fetchone()[0] == 3
    assert commit(st, "nope", [], T0)["reason"] == "unknown_call"


def test_end_then_commit_recomputes_cap(st, conn):
    _, h = user(conn)
    c, _ = start(st, h, T0)
    assert end(st, c, T0 + timedelta(seconds=10), 0)["counted_toward_cap"] is False
    commit(st, c, [rep(1, T0 + timedelta(seconds=5), valid=False)], T0 + timedelta(seconds=20))
    assert conn.execute("select rep_count, counted_toward_cap from calls where id=%s", (c,)).fetchone() == (1, True)


def test_power_hour_multiplier_per_rep_at_boundaries(st, conn):
    ps, pe = et(2026, 10, 13, 15, 0), et(2026, 10, 13, 16, 0)
    conn.execute("insert into power_hours (date_et, starts_at, ends_at) values ('2026-10-13', %s, %s)", (ps, pe))
    _, h = user(conn)
    us = timedelta(microseconds=1)
    c1, _ = start(st, h, ps - timedelta(seconds=60))
    r = commit(st, c1, [rep(1, ps - us), rep(2, ps), rep(3, ps + timedelta(seconds=1))], ps + timedelta(seconds=200))
    assert r["points"] == 5
    assert [(x[2], x[3]) for x in _reps_rows(conn, c1)] == [(1, 1), (2, 2), (2, 2)]
    end(st, c1, ps + timedelta(seconds=135), 3)
    tick(st, ps + timedelta(seconds=400))
    c2, _ = start(st, h, pe - timedelta(seconds=60))
    r = commit(st, c2, [rep(1, pe - us), rep(2, pe), rep(3, pe + timedelta(seconds=1), valid=False)],
               pe + timedelta(seconds=200))
    assert r["points"] == 3
    assert [(x[2], x[3]) for x in _reps_rows(conn, c2)] == [(2, 2), (1, 1), (1, 0)]
    # other ET day: no power hour row -> 1x
    assert conn.execute("select ch_user_points(client_id) from sessions limit 1").fetchone()[0] == 8


def test_window_boundaries_and_count_limit(st, conn):
    we = et(2026, 10, 18, 23, 59, 59)
    _, h = user(conn)
    c, _ = start(st, h, we - timedelta(seconds=100))
    reps = [rep(1, we - timedelta(seconds=1)), rep(2, we), rep(3, we + timedelta(seconds=30), valid=False,
                                                                reject_reasons=["depth"])]
    r = commit(st, c, reps, we + timedelta(seconds=120))
    assert (r["valid_reps"], r["points"]) == (1, 1)
    assert [(x[1], x[3], x[4]) for x in _reps_rows(conn, c)] == \
        [(True, 1, []), (False, 0, ["after_freeze"]), (False, 0, ["depth", "after_freeze"])]


def test_after_count_boundary(st, conn):
    # after_count: at >= connected_at + call_count_s
    _, h2 = user(conn)
    c2, r = start(st, h2, T0)
    assert r["decision"] == "accept"
    commit(st, c2, [rep(1, T0 + timedelta(seconds=179)), rep(2, T0 + timedelta(seconds=180))], T0 + timedelta(seconds=200))
    assert [(x[3], x[4]) for x in _reps_rows(conn, c2)] == [(1, []), (0, ["after_count"])]


def test_before_start_and_frozen_at_commit(st, conn):
    _, h = user(conn)
    ws = et(2026, 10, 12, 20, 0)
    c, _ = start(st, h, ws)
    # reps carrying an absolute time before window_start are rejected
    commit(st, c, [rep(1, ws - timedelta(seconds=1)), rep(2, ws)], ws + timedelta(seconds=100))
    assert [(x[3], x[4]) for x in _reps_rows(conn, c)] == [(0, ["before_start"]), (1, [])]
    end(st, c, ws + timedelta(seconds=60), 2)
    tick(st, ws + timedelta(seconds=300))
    c2, _ = start(st, h, ws + timedelta(seconds=301))
    set_cfg(conn, "competition_frozen", True)
    r = commit(st, c2, [rep(1, ws + timedelta(seconds=310))], ws + timedelta(seconds=400))
    assert r["points"] == 0
    assert _reps_rows(conn, c2)[0][4] == ["after_freeze"]


def test_liveness_fail_zeroes_all_reps(st, conn):
    _, h = user(conn)
    c, _ = start(st, h, T0)
    r = commit(st, c, [rep(i, T0 + timedelta(seconds=10 + i)) for i in range(1, 6)], T0 + timedelta(seconds=200),
               liveness="fail")
    assert (r["valid_reps"], r["points"]) == (0, 0)
    assert {tuple(x[4]) for x in _reps_rows(conn, c)} == {("liveness_fail",)}
    assert conn.execute("select liveness_result from calls where id=%s", (c,)).fetchone()[0] == "fail"
    assert conn.execute("select completed_reps from sets").fetchone()[0] == 0


def test_rep_time_fallback_and_unique_numbering(st, conn):
    _, h = user(conn)
    c, _ = start(st, h, T0)
    reps = [{"n": 1, "t": 5.0, "valid": True}, {"n": 1, "t": 6.0, "valid": True}, {"t": 7.5, "valid": True}]
    r = commit(st, c, reps, T0 + timedelta(seconds=200), started_at=T0 + timedelta(seconds=2))
    assert r["valid_reps"] == 3
    rows = _reps_rows(conn, c)
    assert [x[0] for x in rows] == [1, 2, 3]
    assert sorted(x[5] for x in rows) == [T0 + timedelta(seconds=7), T0 + timedelta(seconds=8),
                                          T0 + timedelta(seconds=9.5)]
