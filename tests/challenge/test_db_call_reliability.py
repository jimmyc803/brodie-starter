"""Migration 20261023_challenge_call_reliability.sql: short-call / timeout turn restore, cap exemption, dial grace,
worker liveness gate, ch_postcall rank deltas outside the line lock."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from psycopg.types.json import Jsonb

from challenge.store import PgStore
from db.test.harness import MIGRATIONS, connect

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=ET)
CLAIM_S = 90
GRACE_S = 10
GAP_S = 10
TIMEOUT_S = 180 + 15 + 60  # call_count_s + call_reveal_s + in_call_timeout_extra_s


def rpc(c, fn: str, **kw):
    params = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in kw.items()}
    return c.execute(f"select {fn}({', '.join(f'{k} => %({k})s' for k in kw)})", params).fetchone()[0]


def cfg(c, key, value):
    c.execute("insert into competition_config (key, value, updated_by) values (%s, %s, 'test')"
              " on conflict (key) do update set value = excluded.value", (key, Jsonb(value)))


@pytest.fixture
def c(db):
    conn = connect(db)
    conn.execute("truncate clients, calls, messages, audit_log, heartbeats, rank_state restart identity cascade")
    conn.execute("delete from line_state where line_id <> 'line-1'")
    conn.execute("delete from lines where id <> 'line-1'")
    conn.execute("update lines set active = true, facetime_handle = null")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, updated_at=now()")
    for k, v in {"competition_frozen": False, "window_start": "2026-10-12T20:00:00-04:00",
                 "window_end": "2026-10-18T23:59:59-04:00", "claim_window_s": CLAIM_S, "daily_call_cap": 5,
                 "claim_grace_s": GRACE_S, "worker_stale_s": 120, "line_offline_gap_s": GAP_S,
                 "min_counted_call_s": 30, "call_count_s": 180, "call_reveal_s": 15, "in_call_timeout_extra_s": 60,
                 "brodie_number": None}.items():
        cfg(conn, k, v)
    conn.execute("delete from competition_config where key = 'frozen_at'")
    try:
        yield conn
    finally:
        conn.close()


def user(c, i: int) -> str:
    coach = c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s) returning id",
                    (coach, f"u{i}", f"user_{i}", T0 - timedelta(days=1))).fetchone()[0]
    c.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
              (f"+1777000{i:04d}", uid))
    return str(uid)


def start(c, at, *, mode="claim_window", handle=None, call_id=None):
    call_id = call_id or f"call-{uuid.uuid4().hex[:10]}"
    return call_id, rpc(c, "ch_call_start", p_call_id=call_id, p_line_id="line-1", p_handle=handle, p_mode=mode,
                        p_now=at)


def end(c, call_id, ended_at, reps=0, now=None):
    return rpc(c, "ch_call_end", p_call_id=call_id, p_ended_at=ended_at, p_count_end_at=None, p_rep_count=reps,
               p_now=now or ended_at)


def commit(c, call_id, reps, now, ended_at=None):
    return rpc(c, "ch_commit_reps", p_call_id=call_id, p_now=now, p_payload={
        "started_at": None, "ended_at": ended_at.isoformat() if ended_at else None, "liveness_result": "skipped",
        "judge_version": "j3", "reps": reps})


def rep(n, at, valid):
    return {"n": n, "t": float(n), "at": at.isoformat(), "valid": valid, "reject_reasons": [] if valid else ["no_depth"],
            "faults": [], "in_challenge": False}


def line(c):
    return c.execute("select state, user_id::text, claimed_until from line_state where line_id='line-1'").fetchone()


def queue(c, uid):
    return c.execute("select id, status, claim_expires_at, turn_restores from queue where user_id=%s order by id",
                     (uid,)).fetchall()


def youre_up(c):
    return [(k, ctx) for k, ctx in c.execute("select dedupe_key, ctx from messages where template='youre_up' order by id")]


def counted(c, call_id):
    return c.execute("select counted_toward_cap from calls where id=%s", (call_id,)).fetchone()[0]


def today(c, uid, at=T0):
    return c.execute("select ch_calls_today(%s, %s)", (uid, at)).fetchone()[0]


def claim_for(c, uid, at=T0):
    assert rpc(c, "ch_queue_join", p_user_id=uid, p_now=at - timedelta(seconds=1))["ok"]
    [cl] = rpc(c, "ch_tick", p_now=at)["claims"]
    assert cl["user_id"] == uid
    return cl["queue_id"]


MIGRATION = MIGRATIONS / "20261023_challenge_call_reliability.sql"


def test_migration_applies_twice(pg_cluster, db):
    name = db.split("dbname=")[1].split()[0]
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)
    # later migrations redefine functions from this one (20261024 cap fix): re-apply them (twice: idempotent) so the
    # module database ends on the current definitions again
    for later in sorted(p for p in MIGRATIONS.glob("*.sql") if p.name > MIGRATION.name):
        pg_cluster.apply_file(name, later)
        pg_cluster.apply_file(name, later)
    with connect(db) as conn:
        assert conn.execute("select count(*) from competition_config where key in ('claim_grace_s', 'worker_stale_s')"
                            ).fetchone()[0] == 2
        assert "turn_restored_at" in conn.execute(
            "select pg_get_functiondef('ch_calls_cap_exempt(calls)'::regprocedure)").fetchone()[0]


@pytest.mark.parametrize("fn", ["ch_calls_settle(text,timestamptz)", "ch_calls_cap_exempt(calls)",
                                "ch_calls_line_stale(text,timestamptz)", "ch_calls_line_handle(text)",
                                "ch_call_start(text,text,text,text,timestamptz)", "ch_tick(timestamptz)",
                                "ch_commit_reps(text,jsonb,timestamptz)", "ch_postcall(text,timestamptz,text)"])
def test_execute_service_role_only(db, fn):
    with connect(db) as conn:
        for role, ok in [("anon", False), ("authenticated", False), ("service_role", True)]:
            assert conn.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn)).fetchone()[0] is ok
        assert conn.execute("select prosecdef from pg_proc where oid = %s::regprocedure", (fn,)).fetchone()[0]


# ---------------------------------------------------------------- P0-1 griefer / short call

def test_short_claim_window_call_restores_turn_once_and_never_counts(c):
    a, b = user(c, 1), user(c, 2)
    qa = claim_for(c, a)
    rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=1))
    # a stranger dials during a's claim: attributed to a (no caller ID), hangs up after 4 s with no reps
    g1, r = start(c, T0 + timedelta(seconds=5))
    assert (r["decision"], r["user_id"]) == ("accept", a)
    assert c.execute("select via_claim, queue_id from calls where id=%s", (g1,)).fetchone() == (True, qa)
    t_end = T0 + timedelta(seconds=9)
    assert end(c, g1, t_end) == {"ok": True, "counted_toward_cap": False}
    # a gets the turn back right away: same entry, fresh claim window on the line, a new "you're up"
    until = t_end + timedelta(seconds=CLAIM_S)
    assert queue(c, a) == [(qa, "notified", until, 1)]
    assert line(c) == ("claimed", a, until)
    keys = [k for k, _ in youre_up(c)]
    assert keys == [f"youre_up:{qa}", f"youre_up:{qa}:restore:{g1}"]
    ctx = youre_up(c)[-1][1]
    assert ctx["restored"] is True and ctx["queue_id"] == qa and ctx["claim_window_s"] == CLAIM_S
    assert datetime.fromisoformat(ctx["claimed_until"]) == until
    assert today(c, a) == 0
    assert c.execute("select count(*) from audit_log where action='call:turn_restored' and target=%s",
                     (g1,)).fetchone()[0] == 1
    # retries of the end (and of a late empty commit) change nothing
    assert end(c, g1, t_end) == {"ok": True, "counted_toward_cap": False}
    assert commit(c, g1, [], t_end + timedelta(seconds=1))["ok"] is True
    assert commit(c, g1, [], t_end + timedelta(seconds=2))["already"] is True
    assert queue(c, a) == [(qa, "notified", until, 1)] and len(youre_up(c)) == 2
    assert counted(c, g1) is False
    # the stranger grabs the restored claim too: not restored a second time, still never counted
    g2, r = start(c, t_end + timedelta(seconds=3))
    assert r["user_id"] == a
    assert end(c, g2, t_end + timedelta(seconds=6))["counted_toward_cap"] is False
    assert queue(c, a) == [(qa, "connected", until, 1)]
    assert line(c)[0] == "offline" and len(youre_up(c)) == 2
    assert today(c, a) == 0
    # the queue moves on to b once the offline gap ends
    r = rpc(c, "ch_tick", p_now=t_end + timedelta(seconds=6 + GAP_S))
    assert [x["user_id"] for x in r["claims"]] == [b]


def test_holder_who_hangs_up_instantly_twice_does_not_loop(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    c1, _ = start(c, T0 + timedelta(seconds=3))
    end(c, c1, T0 + timedelta(seconds=4))
    assert queue(c, a)[0][1:] == ("notified", T0 + timedelta(seconds=4 + CLAIM_S), 1)
    c2, _ = start(c, T0 + timedelta(seconds=6))
    end(c, c2, T0 + timedelta(seconds=7))
    assert queue(c, a) == [(qa, "connected", T0 + timedelta(seconds=4 + CLAIM_S), 1)]
    assert line(c)[0] == "offline"
    assert c.execute("select count(*) from audit_log where action='call:turn_restored'").fetchone()[0] == 1


def test_short_call_with_only_invalid_reps_commit_first(c):
    """Worker order: reps_committed then call_ended. Invalid reps alone do not burn the cap on a short call."""
    a = user(c, 1)
    qa = claim_for(c, a)
    g, _ = start(c, T0 + timedelta(seconds=5))
    t_end = T0 + timedelta(seconds=20)
    r = commit(c, g, [rep(1, T0 + timedelta(seconds=10), False), rep(2, T0 + timedelta(seconds=14), False)], t_end,
               ended_at=t_end)
    assert (r["ok"], r["valid_reps"]) == (True, 0)
    assert end(c, g, t_end, reps=2)["counted_toward_cap"] is False
    assert queue(c, a)[0][:2] == (qa, "notified")
    assert today(c, a) == 0


def test_short_call_end_first_then_commit_without_valid_reps(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    g, _ = start(c, T0 + timedelta(seconds=5))
    t_end = T0 + timedelta(seconds=20)
    # end first with a rep count: valid reps unknown yet -> counted (old rule), turn not restored yet
    assert end(c, g, t_end, reps=1)["counted_toward_cap"] is True
    assert queue(c, a)[0][1] == "connected"
    # the commit shows no valid rep: exempt and restored (the line is still in its offline gap)
    assert commit(c, g, [rep(1, T0 + timedelta(seconds=10), False)], t_end + timedelta(seconds=1))["ok"]
    assert counted(c, g) is False
    assert queue(c, a)[0][:2] == (qa, "notified")
    assert line(c)[:2] == ("claimed", a)
    # retries keep it that way
    assert end(c, g, t_end, reps=1)["counted_toward_cap"] is False
    assert commit(c, g, [], t_end + timedelta(seconds=5))["already"] is True
    assert len(youre_up(c)) == 2 and today(c, a) == 0


def test_short_call_with_a_valid_rep_counts_and_is_not_restored(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    g, _ = start(c, T0 + timedelta(seconds=5))
    t_end = T0 + timedelta(seconds=20)
    r = commit(c, g, [rep(1, T0 + timedelta(seconds=10), True)], t_end, ended_at=t_end)
    assert r["valid_reps"] == 1
    assert end(c, g, t_end, reps=1)["counted_toward_cap"] is True
    assert queue(c, a) == [(qa, "connected", T0 + timedelta(seconds=CLAIM_S), 0)]
    assert today(c, a) == 1 and len(youre_up(c)) == 1


def test_zero_rep_call_of_30s_or_more_still_counts(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    g, _ = start(c, T0 + timedelta(seconds=5))
    assert end(c, g, T0 + timedelta(seconds=35))["counted_toward_cap"] is True
    assert queue(c, a)[0][:2] == (qa, "connected")
    assert today(c, a) == 1


def test_chert_meta_short_call_is_not_restored(c):
    """With caller ID the caller is really the holder: a short call is theirs (counted by the usual rule only)."""
    a = user(c, 1)
    qa = claim_for(c, a)
    g, r = start(c, T0 + timedelta(seconds=5), mode="chert_meta", handle="+17770000001")
    assert r["decision"] == "accept"
    assert c.execute("select via_claim from calls where id=%s", (g,)).fetchone()[0] is False
    assert end(c, g, T0 + timedelta(seconds=9))["counted_toward_cap"] is False
    assert queue(c, a)[0][:2] == (qa, "connected")
    assert line(c)[0] == "offline"


def test_restore_when_user_requeued_uses_the_new_entry(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    g, _ = start(c, T0 + timedelta(seconds=5))
    t_end = T0 + timedelta(seconds=20)
    assert end(c, g, t_end, reps=1)["counted_toward_cap"] is True  # valid reps unknown until the commit
    # the holder texted QUEUE again before the commit landed
    j = rpc(c, "ch_queue_join", p_user_id=a, p_now=t_end + timedelta(seconds=1))
    assert j["reason"] == "ok"
    commit(c, g, [rep(1, T0 + timedelta(seconds=10), False)], t_end + timedelta(seconds=2))
    rows = queue(c, a)
    assert [(r[0] == qa, r[1], r[3]) for r in rows] == [(True, "connected", 1), (False, "notified", 1)]
    assert line(c)[:2] == ("claimed", a)
    assert youre_up(c)[-1][0] == f"youre_up:{rows[1][0]}:restore:{g}"


def test_restore_goes_to_front_of_waiting_when_worker_is_stale(c):
    a, b = user(c, 1), user(c, 2)
    c.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (T0,))
    qa = claim_for(c, a, T0 + timedelta(seconds=1))
    rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=2))
    g, _ = start(c, T0 + timedelta(seconds=5))
    t_end = T0 + timedelta(seconds=200)  # long claim... the worker stopped beating meanwhile (> 120 s)
    c.execute("update calls set connected_at=%s where id=%s", (t_end - timedelta(seconds=5), g))
    assert end(c, g, t_end)["counted_toward_cap"] is False
    # not claimed onto a dead line: back to waiting, ahead of b, no "you're up" yet
    assert queue(c, a)[0][:2] == (qa, "waiting")
    assert len(youre_up(c)) == 1
    view = rpc(c, "ch_queue_view", p_now=t_end)
    assert [q["user_id"] for q in view["queue"]] == [a, b]
    r = rpc(c, "ch_tick", p_now=t_end + timedelta(seconds=GAP_S))
    assert r["claims"] == [] and r["held"] == ["line-1"]
    c.execute("update heartbeats set at=%s where component='worker:line-1'", (t_end + timedelta(seconds=GAP_S),))
    r = rpc(c, "ch_tick", p_now=t_end + timedelta(seconds=GAP_S + 1))
    assert [x["user_id"] for x in r["claims"]] == [a] and "held" not in r


# ---------------------------------------------------------------- P1-2 in_call timeout

def test_timeout_without_commit_not_counted_and_turn_restored_once(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    s = T0 + timedelta(seconds=5)
    c1, _ = start(c, s)
    t = s + timedelta(seconds=TIMEOUT_S)
    r = rpc(c, "ch_tick", p_now=t)
    assert r["timeouts"] == [c1]
    assert r["restored"] == [{"call_id": c1, "user_id": a, "queue_id": qa, "line_id": "line-1", "how": "claimed"}]
    assert c.execute("select end_reason, counted_toward_cap from calls where id=%s", (c1,)).fetchone() == \
        ("timeout", False)
    assert queue(c, a) == [(qa, "notified", t + timedelta(seconds=CLAIM_S), 1)]
    assert line(c) == ("claimed", a, t + timedelta(seconds=CLAIM_S))
    assert youre_up(c)[-1][0] == f"youre_up:{qa}:restore:{c1}"
    # a second timeout on the restored claim: not counted, not restored again (entry is connected, line goes offline)
    s2 = t + timedelta(seconds=5)
    c2, _ = start(c, s2)
    r = rpc(c, "ch_tick", p_now=s2 + timedelta(seconds=TIMEOUT_S))
    assert r["timeouts"] == [c2] and "restored" not in r
    assert counted(c, c2) is False
    assert queue(c, a)[0][1] == "connected" and line(c)[0] == "offline"
    assert today(c, a) == 0


def test_timeout_then_late_commit_recounts(c):
    a = user(c, 1)
    claim_for(c, a)
    s = T0 + timedelta(seconds=5)
    c1, _ = start(c, s)
    rpc(c, "ch_tick", p_now=s + timedelta(seconds=TIMEOUT_S))
    assert counted(c, c1) is False
    # the worker's commit arrives late with reps and the real end: the provisional end is replaced, it counts
    r = commit(c, c1, [rep(1, s + timedelta(seconds=10), True)], s + timedelta(seconds=TIMEOUT_S + 30),
               ended_at=s + timedelta(seconds=60))
    assert r["ok"] and r["valid_reps"] == 1
    assert c.execute("select end_reason, counted_toward_cap from calls where id=%s", (c1,)).fetchone() == \
        ("commit", True)
    assert today(c, a) == 1
    assert c.execute("select count(*) from audit_log where action='call:turn_restored'").fetchone()[0] == 1


def _counted_calls(c, uid, n, at=T0):
    for i in range(n):
        t = at - timedelta(hours=2, minutes=10 * i)
        c.execute("insert into calls (id, line_id, user_id, decision, connected_at, ended_at, counted_toward_cap)"
                  " values (%s, 'line-1', %s, 'accept', %s, %s, true)", (f"earlier-{uid[:8]}-{i}", uid, t,
                                                                         t + timedelta(minutes=4)))
    assert today(c, uid, at) == n


def test_late_commit_after_the_restored_turn_was_used_never_exceeds_the_cap(c):
    """20261024 fix: 4 counted calls, the 5th times out (exempt, turn restored), the restored turn is used (5th
    counted call); the reconciler's late commit for the timed-out call must not make it 6."""
    a = user(c, 1)
    _counted_calls(c, a, 4)
    claim_for(c, a)
    s = T0 + timedelta(seconds=5)
    c1, _ = start(c, s)
    t = s + timedelta(seconds=TIMEOUT_S)
    assert rpc(c, "ch_tick", p_now=t)["restored"][0]["call_id"] == c1
    s2 = t + timedelta(seconds=5)
    c2, r2 = start(c, s2)
    assert r2["decision"] == "accept"
    # the late commit arrives while the restored-turn call is still in progress: it may not take that call's slot
    r = commit(c, c1, [rep(1, s + timedelta(seconds=10), True)], s2 + timedelta(seconds=20),
               ended_at=s + timedelta(seconds=60))
    assert r["ok"] and r["valid_reps"] == 1 and r["points"] >= 1                # the reps still score
    assert counted(c, c1) is False
    e2 = s2 + timedelta(seconds=120)
    end(c, c2, e2, reps=3)
    commit(c, c2, [rep(1, s2 + timedelta(seconds=10), True)], e2 + timedelta(seconds=1), ended_at=e2)
    assert counted(c, c2) is True and counted(c, c1) is False and today(c, a) == 5
    # retries of the late commit change nothing
    assert commit(c, c1, [], e2 + timedelta(seconds=30))["already"] is True
    assert today(c, a) == 5


def test_late_commit_after_the_restored_turn_was_used_and_ended(c):
    """Same, but the restored-turn call has already ended (counted) when the late commit lands: still capped at 5."""
    a = user(c, 1)
    _counted_calls(c, a, 4)
    claim_for(c, a)
    s = T0 + timedelta(seconds=5)
    c1, _ = start(c, s)
    t = s + timedelta(seconds=TIMEOUT_S)
    rpc(c, "ch_tick", p_now=t)
    s2 = t + timedelta(seconds=5)
    c2, _ = start(c, s2)
    e2 = s2 + timedelta(seconds=120)
    end(c, c2, e2, reps=3)
    assert today(c, a, e2) == 5
    commit(c, c1, [rep(1, s + timedelta(seconds=10), True)], e2 + timedelta(seconds=30), ended_at=s + timedelta(seconds=60))
    assert counted(c, c1) is False and today(c, a, e2) == 5


def test_late_commit_recounts_when_under_the_cap_even_after_a_restore(c):
    """Room left under the cap: the late commit still re-counts the restored call (the 20261023 behaviour)."""
    a = user(c, 1)
    _counted_calls(c, a, 3)
    claim_for(c, a)
    s = T0 + timedelta(seconds=5)
    c1, _ = start(c, s)
    t = s + timedelta(seconds=TIMEOUT_S)
    rpc(c, "ch_tick", p_now=t)
    s2 = t + timedelta(seconds=5)
    c2, _ = start(c, s2)
    e2 = s2 + timedelta(seconds=120)
    end(c, c2, e2, reps=3)
    commit(c, c1, [rep(1, s + timedelta(seconds=10), True)], e2 + timedelta(seconds=30), ended_at=s + timedelta(seconds=60))
    assert counted(c, c1) is True and counted(c, c2) is True and today(c, a, e2) == 5


# ---------------------------------------------------------------- P2-1 dial grace

def test_dial_grace_accepts_holder_after_claimed_until(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    deadline = T0 + timedelta(seconds=CLAIM_S)
    # the tick does not expire the claim inside the grace
    r = rpc(c, "ch_tick", p_now=deadline + timedelta(seconds=GRACE_S - 1))
    assert r["no_shows"] == [] and line(c)[:2] == ("claimed", a)
    g, r = start(c, deadline + timedelta(seconds=GRACE_S - 1))
    assert (r["decision"], r["user_id"]) == ("accept", a)
    assert queue(c, a)[0][:2] == (qa, "connected")


def test_dial_grace_ends_and_tick_expires_after_it(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    deadline = T0 + timedelta(seconds=CLAIM_S)
    assert start(c, deadline + timedelta(seconds=GRACE_S))[1]["reason"] == "not_your_turn"
    r = rpc(c, "ch_tick", p_now=deadline + timedelta(seconds=GRACE_S))
    assert r["no_shows"] == [{"user_id": a, "queue_id": qa}]


def test_dial_grace_chert_meta_and_config(c):
    a = user(c, 1)
    claim_for(c, a)
    deadline = T0 + timedelta(seconds=CLAIM_S)
    g, r = start(c, deadline + timedelta(seconds=5), mode="chert_meta", handle="+17770000001")
    assert r["decision"] == "accept"
    end(c, g, deadline + timedelta(seconds=40))
    b = user(c, 2)
    claim_for(c, b, T0 + timedelta(minutes=10))
    cfg(c, "claim_grace_s", 0)
    _, r = start(c, T0 + timedelta(minutes=10, seconds=CLAIM_S))
    assert r["reason"] == "not_your_turn"


def test_dial_grace_with_admin_pause_requeues_after_grace(c):
    a = user(c, 1)
    qa = claim_for(c, a)
    cfg(c, "competition_frozen", True)
    deadline = T0 + timedelta(seconds=CLAIM_S)
    rpc(c, "ch_tick", p_now=deadline + timedelta(seconds=GRACE_S - 1))
    assert queue(c, a)[0][1] == "notified"
    rpc(c, "ch_tick", p_now=deadline + timedelta(seconds=GRACE_S))
    assert queue(c, a)[0][:2] == (qa, "waiting") and line(c)[0] == "idle"
    assert c.execute("select count(*) from messages where template='missed_slot'").fetchone()[0] == 0
    cfg(c, "competition_frozen", False)


def test_grace_seeded_in_config(c):
    keys = dict(c.execute("select key, value from competition_config where key in ('claim_grace_s', 'worker_stale_s')"))
    assert set(keys) == {"claim_grace_s", "worker_stale_s"}


# ---------------------------------------------------------------- P1-1 worker liveness gate

def test_stale_worker_heartbeat_holds_the_queue(c):
    a = user(c, 1)
    rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)
    c.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (T0 - timedelta(seconds=121),))
    r = rpc(c, "ch_tick", p_now=T0)
    assert r["claims"] == [] and r["held"] == ["line-1"]
    assert line(c)[0] == "idle" and youre_up(c) == [] and queue(c, a)[0][1] == "waiting"
    # the aggregate 'worker' row does not count: the gate reads the line's own heartbeat
    c.execute("insert into heartbeats (component, at) values ('worker', %s)", (T0,))
    assert rpc(c, "ch_tick", p_now=T0)["held"] == ["line-1"]
    c.execute("update heartbeats set at=%s where component='worker:line-1'", (T0 - timedelta(seconds=30),))
    r = rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=1))
    assert [x["user_id"] for x in r["claims"]] == [a] and "held" not in r


def test_worker_gate_off_without_heartbeat_or_when_disabled(c):
    a, b = user(c, 1), user(c, 2)
    rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)
    assert [x["user_id"] for x in rpc(c, "ch_tick", p_now=T0)["claims"]] == [a]  # line never beat: not gated
    rpc(c, "ch_queue_leave", p_user_id=a, p_reason="left", p_now=T0 + timedelta(seconds=1))
    c.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (T0 - timedelta(hours=1),))
    cfg(c, "worker_stale_s", 0)
    rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=2))
    assert [x["user_id"] for x in rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=3))["claims"]] == [b]


def test_held_only_reported_when_someone_waits(c):
    c.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (T0 - timedelta(hours=1),))
    assert rpc(c, "ch_tick", p_now=T0) == {"no_shows": [], "claims": [], "timeouts": [], "idled": []}


# ---------------------------------------------------------------- P2-2 ch_postcall rank deltas before the line lock

def test_postcall_computes_rank_deltas_before_taking_the_line_lock(c, db):
    a = user(c, 1)
    s = T0
    call_id, r = start(c, s, mode="chert_meta", handle="+17770000001")
    assert r["decision"] == "accept"
    commit(c, call_id, [rep(1, s + timedelta(seconds=10), True)], s + timedelta(seconds=40))
    end(c, call_id, s + timedelta(seconds=40), reps=1)
    holder = connect(db)
    holder.autocommit = False
    holder.execute("select ch_calls_lock_lines()")  # a long ch_tick / call_start in flight
    out: dict = {}

    def run():
        out["r"] = PgStore(db).rpc("ch_postcall", {"p_call_id": call_id, "p_now": s + timedelta(seconds=45),
                                                   "p_card_delivery": "link"})

    th = threading.Thread(target=run)
    th.start()
    try:
        # the postcall backend already holds rank_state (ch_rank_deltas ran) while it waits for the line lock
        seen = False
        for _ in range(100):
            row = c.execute(
                "select count(*) from pg_locks l join pg_class k on k.oid = l.relation"
                " where k.relname = 'rank_state' and l.mode = 'ShareRowExclusiveLock' and l.granted"
                " and l.pid <> pg_backend_pid() and l.pid <> %s", (holder.info.backend_pid,)).fetchone()[0]
            if row:
                seen = True
                break
            time.sleep(0.05)
        assert seen, "ch_rank_deltas did not run before the line lock"
        assert th.is_alive()  # still blocked on the line lock for the intent writes
    finally:
        holder.rollback()
        holder.close()
        th.join(10)
    assert out["r"]["ok"] is True and out["r"]["already"] is False
    assert c.execute("select count(*) from messages where template='post_call' and user_id=%s", (a,)).fetchone()[0] == 1
    assert rpc(c, "ch_postcall", p_call_id=call_id, p_now=s + timedelta(seconds=50), p_card_delivery="link") == \
        {"ok": True, "already": True}


def test_concurrent_postcall_same_call_writes_intents_once(c, db):
    a, b = user(c, 1), user(c, 2)
    cfg(c, "rank_drop_min", 1)  # two users: b drops from rank 1 to 2 when a overtakes
    cb, r = start(c, T0, mode="chert_meta", handle="+17770000002")
    assert r["decision"] == "accept", r
    commit(c, cb, [rep(1, T0 + timedelta(seconds=5), True)], T0 + timedelta(seconds=40))
    end(c, cb, T0 + timedelta(seconds=40), reps=1)
    assert rpc(c, "ch_postcall", p_call_id=cb, p_now=T0 + timedelta(seconds=41), p_card_delivery="link")["ok"]
    s = T0 + timedelta(minutes=5)
    rpc(c, "ch_tick", p_now=s)  # line offline -> idle
    ca, r = start(c, s, mode="chert_meta", handle="+17770000001")
    assert r["decision"] == "accept", r
    commit(c, ca, [rep(i, s + timedelta(seconds=5 + i), True) for i in range(1, 4)], s + timedelta(seconds=40))
    end(c, ca, s + timedelta(seconds=40), reps=3)
    res: list = []

    def run():
        res.append(PgStore(db).rpc("ch_postcall", {"p_call_id": ca, "p_now": s + timedelta(seconds=45),
                                                   "p_card_delivery": "link"}))

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert sorted(bool(r.get("already")) for r in res) == [False, True, True, True], res
    assert c.execute("select count(*) from messages where template='rank_drop' and user_id=%s", (b,)).fetchone()[0] == 1
    assert c.execute("select last_drop_text_at is not null from rank_state where user_id=%s", (b,)).fetchone()[0]
