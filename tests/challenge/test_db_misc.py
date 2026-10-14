"""Migration 20261013_challenge_misc.sql: registration, status/leaderboard, rank deltas, config, admin, outbox, inbound."""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.types.json import Jsonb

from db.test.harness import MIGRATIONS, connect

ET = ZoneInfo("America/New_York")
MIGRATION = MIGRATIONS / "20261013_challenge_misc.sql"
REPS_MIGRATION = MIGRATIONS / "20261027_challenge_admin_reps.sql"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=ET)
RPCS = ["ch_queue_position", "ch_join_start", "ch_join_confirm", "ch_user_by_handle", "ch_set_opt", "ch_user_status",
        "ch_leaderboard", "ch_rank_deltas", "ch_config_get", "ch_config_set", "ch_admin_void_call",
        "ch_admin_unvoid_call", "ch_admin_adjust", "ch_admin_ban", "ch_admin_unban", "ch_admin_queue_remove",
        "ch_outbox_enqueue", "ch_outbox_claim", "ch_outbox_mark", "ch_inbound_record", "ch_heartbeat"]


def et(*args) -> datetime:
    return datetime(*args, tzinfo=ET)


def rpc(c, fn: str, **kw):
    params = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in kw.items()}
    sql = f"select {fn}({', '.join(f'{k} => %({k})s' for k in kw)})"
    return c.execute(sql, params).fetchone()[0]


def raises(c, exc, fn: str, **kw):
    with pytest.raises(exc):
        with c.transaction():
            rpc(c, fn, **kw)


def make_user(c, name: str, joined_at: datetime | None = None, handle: str | None = None) -> uuid.UUID:
    coach = c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s, %s, %s, %s) returning id",
                    (coach, name, name, joined_at or et(2026, 10, 12, 20, 0))).fetchone()[0]
    if handle:
        c.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s, %s, 'phone', 'admin')",
                  (handle, uid))
    return uid


def make_call(c, user_id, connected_at: datetime, n_valid: int = 0, *, points_each: int = 1, void=False,
              counted=True) -> str:
    call_id = f"call-{uuid.uuid4().hex[:12]}"
    sid = c.execute("insert into sessions (client_id, started_at, ended_at) values (%s, %s, %s) returning id",
                    (user_id, connected_at, connected_at + timedelta(seconds=195))).fetchone()[0]
    c.execute("insert into calls (id, line_id, user_id, decision, connected_at, ended_at, counted_toward_cap, void,"
              " session_id, liveness_result, committed_at) values (%s, 'line-1', %s, 'accept', %s, %s, %s, %s, %s,"
              " 'pass', %s)",
              (call_id, user_id, connected_at, connected_at + timedelta(seconds=195), counted, void, sid,
               connected_at + timedelta(seconds=200)))
    set_id = c.execute("insert into sets (session_id, exercise_key, set_number, planned_reps, completed_reps)"
                       " values (%s, 'pushups', 1, 0, %s) returning id", (sid, n_valid)).fetchone()[0]
    for i in range(n_valid):
        c.execute("insert into reps (set_id, rep_number, t, valid, points, multiplier, reject_reasons, at, in_challenge)"
                  " values (%s, %s, %s, true, %s, %s, '{}', %s, false)",
                  (set_id, i + 1, 10 + i, points_each, points_each, connected_at + timedelta(seconds=10 + i)))
    return call_id


def audit(c, action: str):
    return c.execute("select actor, target, before, after, reason from audit_log where action=%s order by id",
                     (action,)).fetchall()


@pytest.fixture
def tx(db):
    c = connect(db, autocommit=False)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


# ---------------------------------------------------------------- migration / grants

def test_migration_idempotent_and_execute_service_role_only(pg_cluster, db):
    name = db.split("dbname=")[1].split()[0]
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)
    # Re-applying this file resurrects the 4-arg ch_admin_adjust that 20261027 replaced with the reps-aware one, and
    # a 4-argument named call would then be ambiguous. Re-apply that migration (twice: idempotent) so the module
    # database ends on the current definition.
    pg_cluster.apply_file(name, REPS_MIGRATION)
    pg_cluster.apply_file(name, REPS_MIGRATION)
    with connect(db) as c:
        rows = c.execute(
            "select p.proname, p.prosecdef, has_function_privilege('anon', p.oid, 'execute'),"
            " has_function_privilege('authenticated', p.oid, 'execute'),"
            " has_function_privilege('service_role', p.oid, 'execute'), p.proconfig"
            " from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any(%s)", (RPCS,)).fetchall()
        assert {r[0] for r in rows} == set(RPCS)
        for proname, secdef, anon, authd, service, cfg in rows:
            assert secdef and not anon and not authd and service, proname
            assert "search_path=public" in (cfg or []), proname


# ---------------------------------------------------------------- registration

def test_join_flow_happy_path(tx):
    assert rpc(tx, "ch_join_start", p_handle=" +15550001 ", p_display_name="Alice_1", p_now=NOW) == \
        {"ok": True, "reason": "ok", "display_name": "Alice_1"}
    r = rpc(tx, "ch_join_confirm", p_handle="+15550001", p_now=NOW)
    assert r["ok"] and r["reason"] == "ok"
    uid = r["user_id"]
    row = tx.execute("select c.coach_id::text = (select value #>> '{}' from competition_config"
                     " where key='challenge_coach_id'), c.display_name, c.joined_at, c.age_confirmed_at,"
                     " c.rules_accepted_at, h.linked_via, h.kind from clients c join client_handles h on h.client_id=c.id"
                     " where c.id=%s", (uid,)).fetchone()
    assert row == (True, "Alice_1", NOW, NOW, NOW, "join", "phone")
    assert tx.execute("select count(*) from join_pending").fetchone()[0] == 0
    assert audit(tx, "user_join")[0][1] == uid
    assert rpc(tx, "ch_user_by_handle", p_handle="+15550001") == \
        {"user_id": uid, "display_name": "Alice_1", "opted_out": False, "banned": False}
    assert rpc(tx, "ch_user_by_handle", p_handle="+19999999") == {"user_id": None}
    # already registered: start again from the same handle
    assert rpc(tx, "ch_join_start", p_handle="+15550001", p_display_name="Other_1", p_now=NOW)["reason"] == \
        "already_registered"
    # email handles are case-normalized
    rpc(tx, "ch_join_start", p_handle="Bob@Example.COM", p_display_name="bobby", p_now=NOW)
    r2 = rpc(tx, "ch_join_confirm", p_handle="bob@example.com", p_now=NOW)
    assert r2["ok"]
    assert tx.execute("select kind from client_handles where handle='bob@example.com'").fetchone()[0] == "email"


# "bad name" is valid since D-41 (see test_db_names_with_spaces.py); a space at an edge or doubled is not.
@pytest.mark.parametrize("name", ["ab", "a" * 21, "bad  name", " bad name", "bad name ", "a" * 19 + " b",
                                 "bad-name", "émile", "", None])
def test_join_start_bad_name(tx, name):
    r = rpc(tx, "ch_join_start", p_handle="+15550002", p_display_name=name, p_now=NOW)
    assert r == {"ok": False, "reason": "bad_name"}
    assert tx.execute("select count(*) from join_pending").fetchone()[0] == 0


def test_join_taken_case_insensitive(tx):
    make_user(tx, "Taken_Name")
    assert rpc(tx, "ch_join_start", p_handle="+1", p_display_name="taken_NAME", p_now=NOW)["reason"] == "taken"


def test_join_confirm_race_two_connections(db):
    setup = connect(db)
    name = f"Racer{uuid.uuid4().hex[:6]}"
    h1, h2 = f"+7{uuid.uuid4().int % 10**9}", f"+8{uuid.uuid4().int % 10**9}"
    assert rpc(setup, "ch_join_start", p_handle=h1, p_display_name=name, p_now=NOW)["ok"]
    assert rpc(setup, "ch_join_start", p_handle=h2, p_display_name=name.upper(), p_now=NOW)["ok"]
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def run(h):
        c = connect(db, autocommit=False)
        try:
            barrier.wait(timeout=10)
            r = rpc(c, "ch_join_confirm", p_handle=h, p_now=NOW)
            time.sleep(0.3)  # hold the txn open so the confirmations overlap
            c.commit()
            results[h] = r
        except Exception as e:  # surfaced by the assertion below
            c.rollback()
            results[h] = e
        finally:
            c.close()

    try:
        threads = [threading.Thread(target=run, args=(h,)) for h in (h1, h2)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=30)
        assert all(isinstance(r, dict) for r in results.values()), results
        oks = [r for r in results.values() if r["ok"]]
        taken = [r for r in results.values() if r.get("reason") == "taken"]
        assert len(oks) == 1 and len(taken) == 1, results
        assert setup.execute("select count(*) from clients where lower(display_name)=lower(%s)",
                             (name,)).fetchone()[0] == 1
        assert setup.execute("select count(*) from client_handles where handle = any(%s)", ([h1, h2],)).fetchone()[0] == 1
        assert setup.execute("select count(*) from join_pending where handle = any(%s)", ([h1, h2],)).fetchone()[0] == 0
    finally:
        setup.execute("delete from clients where lower(display_name)=lower(%s)", (name,))
        setup.execute("delete from join_pending where handle = any(%s)", ([h1, h2],))
        setup.close()


def test_join_no_pending_closed_and_handle_required(tx):
    assert rpc(tx, "ch_join_confirm", p_handle="+4", p_now=NOW) == {"ok": False, "reason": "no_pending", "user_id": None}
    rpc(tx, "ch_join_start", p_handle="+4", p_display_name="Closer", p_now=NOW)
    tx.execute("update competition_config set value='false' where key='registration_open'")
    assert rpc(tx, "ch_join_confirm", p_handle="+4", p_now=NOW)["reason"] == "closed"
    assert rpc(tx, "ch_join_start", p_handle="+5", p_display_name="Closer2", p_now=NOW)["reason"] == "closed"
    tx.execute("update competition_config set value='true' where key='registration_open'")
    assert rpc(tx, "ch_join_start", p_handle="+5", p_display_name="Closer2",
               p_now=et(2026, 10, 19, 0, 0))["reason"] == "closed"
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_join_start", p_handle="  ", p_display_name="x_y_z", p_now=NOW)


def test_set_opt_audited(tx):
    uid = make_user(tx, "opter")
    assert rpc(tx, "ch_set_opt", p_user_id=uid, p_opted_out=True, p_now=NOW) == {"ok": True, "opted_out": True}
    assert rpc(tx, "ch_set_opt", p_user_id=uid, p_opted_out=True, p_now=NOW + timedelta(hours=1))["opted_out"]
    assert tx.execute("select opted_out_at from clients where id=%s", (uid,)).fetchone()[0] == NOW
    assert len(audit(tx, "opt_out")) == 1
    assert rpc(tx, "ch_set_opt", p_user_id=uid, p_opted_out=False, p_now=NOW) == {"ok": True, "opted_out": False}
    assert rpc(tx, "ch_set_opt", p_user_id=uuid.uuid4(), p_opted_out=True, p_now=NOW)["reason"] == "not_registered"


def test_set_opt_out_clears_queue_and_claim(tx):
    waiting = make_user(tx, "w_user")
    notified = make_user(tx, "n_user")
    other = make_user(tx, "o_user")
    tx.execute("insert into lines (id, chert_agent_name) values ('line-opt', 'optagent') on conflict do nothing")
    tx.execute("insert into line_state (line_id, state, updated_at) values ('line-opt','idle',now())"
               " on conflict do nothing")
    qw = tx.execute("insert into queue (user_id, entered_at, status) values (%s, %s, 'waiting') returning id",
                    (waiting, NOW)).fetchone()[0]
    qn = tx.execute("insert into queue (user_id, entered_at, status, line_id, notified_at, claim_expires_at)"
                    " values (%s, %s, 'notified', 'line-opt', %s, %s) returning id",
                    (notified, NOW, NOW, NOW + timedelta(minutes=1))).fetchone()[0]
    qo = tx.execute("insert into queue (user_id, entered_at, status) values (%s, %s, 'waiting') returning id",
                    (other, NOW)).fetchone()[0]
    tx.execute("update line_state set state='claimed', user_id=%s, claimed_until=%s where line_id='line-opt'",
               (notified, NOW + timedelta(minutes=1)))
    assert rpc(tx, "ch_set_opt", p_user_id=waiting, p_opted_out=True, p_now=NOW)["opted_out"]
    assert rpc(tx, "ch_set_opt", p_user_id=notified, p_opted_out=True, p_now=NOW)["opted_out"]
    st = dict(tx.execute("select id, status from queue where id = any(%s)", ([qw, qn, qo],)).fetchall())
    assert st == {qw: "left", qn: "expired", qo: "waiting"}
    assert tx.execute("select state, user_id, claimed_until from line_state where line_id='line-opt'").fetchone() == \
        ("idle", None, None)
    assert {r[1] for r in audit(tx, "opt_out_queue_remove")} == {str(qw), str(qn)}
    assert len(audit(tx, "opt_out")) == 2


# ---------------------------------------------------------------- status / leaderboard / queue position

def test_user_status_and_leaderboard(tx):
    a = make_user(tx, "alpha", et(2026, 10, 12, 20, 0))
    b = make_user(tx, "bravo", et(2026, 10, 12, 21, 0))
    make_user(tx, "charlie", et(2026, 10, 12, 22, 0))
    make_call(tx, a, et(2026, 10, 13, 10, 0), 30)
    make_call(tx, a, et(2026, 10, 14, 10, 0), 5)
    make_call(tx, b, et(2026, 10, 14, 9, 0), 10, points_each=2)
    make_call(tx, b, et(2026, 10, 14, 11, 0), 50, void=True)
    s = rpc(tx, "ch_user_status", p_user_id=a, p_now=NOW)
    assert s["display_name"] == "alpha" and s["points"] == 35 and s["valid_reps"] == 35
    assert (s["rank"], s["total_users"], s["calls_today"], s["calls_left"], s["streak"]) == (1, 3, 1, 4, 2)
    assert s["avatar_level"] == 2 and s["queue_position"] is None and s["queue_status"] is None
    sb = rpc(tx, "ch_user_status", p_user_id=b, p_now=NOW)
    assert (sb["points"], sb["rank"], sb["calls_today"], sb["streak"]) == (20, 2, 2, 1)
    assert rpc(tx, "ch_user_status", p_user_id=uuid.uuid4(), p_now=NOW) == {"user_id": None}
    lb = rpc(tx, "ch_leaderboard", p_limit=10, p_now=NOW)
    assert [(r["rank"], r["display_name"], r["points"], r["streak"]) for r in lb] == \
        [(1, "alpha", 35, 2), (2, "bravo", 20, 1), (3, "charlie", 0, 0)]
    assert lb[0]["user_id"] == str(a)
    assert len(rpc(tx, "ch_leaderboard", p_limit=1, p_now=NOW)) == 1
    # matches the internal view (single source of truth)
    assert tx.execute("select points from ch_user_stats where user_id=%s", (a,)).fetchone()[0] == 35
    # banned users are unlisted
    rpc(tx, "ch_admin_ban", p_user_id=a, p_reason="cheating", p_actor="admin@x.com")
    assert [r["display_name"] for r in rpc(tx, "ch_leaderboard", p_limit=10, p_now=NOW)] == ["bravo", "charlie"]
    assert rpc(tx, "ch_user_status", p_user_id=a, p_now=NOW)["rank"] is None


def test_queue_position_orders_by_calls_today_then_entered_at(tx):
    early = make_user(tx, "early")
    late = make_user(tx, "late")
    third = make_user(tx, "third")
    make_call(tx, early, et(2026, 10, 14, 9, 0), 1)
    make_call(tx, late, et(2026, 10, 13, 9, 0), 1)  # yesterday: does not count today
    tx.execute("insert into queue (user_id, entered_at, status) values (%s, %s, 'waiting'), (%s, %s, 'waiting'),"
               " (%s, %s, 'notified')",
               (early, NOW - timedelta(minutes=10), late, NOW - timedelta(minutes=5), third, NOW - timedelta(minutes=20)))
    assert rpc(tx, "ch_queue_position", p_user_id=late, p_now=NOW) == 1
    assert rpc(tx, "ch_queue_position", p_user_id=early, p_now=NOW) == 2
    assert rpc(tx, "ch_queue_position", p_user_id=third, p_now=NOW) is None
    s = rpc(tx, "ch_user_status", p_user_id=early, p_now=NOW)
    assert (s["queue_position"], s["queue_status"]) == (2, "waiting")
    assert rpc(tx, "ch_user_status", p_user_id=third, p_now=NOW)["queue_status"] == "notified"


# ---------------------------------------------------------------- rank deltas

def adjust(c, uid, pts):
    return rpc(c, "ch_admin_adjust", p_user_id=uid, p_points=pts, p_reason="test", p_actor="admin@x.com")


def test_rank_deltas_first_observation_drops_ties_and_throttle(tx):
    a = make_user(tx, "rk_a", et(2026, 10, 12, 20, 0))
    b = make_user(tx, "rk_b", et(2026, 10, 12, 20, 1))
    c = make_user(tx, "rk_c", et(2026, 10, 12, 20, 2))
    d = make_user(tx, "rk_d", et(2026, 10, 12, 20, 3))
    for u, p in ((a, 30), (b, 20), (c, 10), (d, 5)):
        adjust(tx, u, p)
    assert rpc(tx, "ch_rank_deltas", p_now=NOW) == []  # first observation of everyone
    assert tx.execute("select count(*) from rank_state where rank is not null").fetchone()[0] == 4
    adjust(tx, c, 20)   # c = 30, ties a; same reached_at (txn now()) -> joined_at tiebreak keeps a ahead
    adjust(tx, d, 100)  # d = 105 -> rank 1
    # new order: d 105, a 30, c 30, b 20 -> a 1->2 (1, below min), b 2->4 (drop 2), c 3->3, d 4->1
    out = rpc(tx, "ch_rank_deltas", p_now=NOW)
    assert [(r["user_id"], r["old_rank"], r["new_rank"], r["points"], r["ahead_display_name"], r["ahead_points"],
             r["throttled"]) for r in out] == [(str(b), 2, 4, 20, "rk_c", 30, False)]
    ranks = dict(tx.execute("select user_id, rank from rank_state").fetchall())
    assert ranks == {d: 1, a: 2, c: 3, b: 4}
    assert tx.execute("select last_drop_text_at from rank_state where user_id=%s", (b,)).fetchone()[0] == NOW
    assert rpc(tx, "ch_rank_deltas", p_now=NOW) == []  # nothing changed since
    # another drop for b within the throttle window: reported but throttled; stamp unchanged
    e = make_user(tx, "rk_e", et(2026, 10, 12, 20, 4))
    f = make_user(tx, "rk_f", et(2026, 10, 12, 20, 5))
    assert rpc(tx, "ch_rank_deltas", p_now=NOW) == []  # e/f first observed at ranks 5/6
    adjust(tx, e, 25)
    adjust(tx, f, 25)
    later = NOW + timedelta(hours=1)
    out = rpc(tx, "ch_rank_deltas", p_now=later)
    assert [(r["user_id"], r["old_rank"], r["new_rank"], r["throttled"]) for r in out] == [(str(b), 4, 6, True)]
    assert tx.execute("select last_drop_text_at from rank_state where user_id=%s", (b,)).fetchone()[0] == NOW
    # banned user leaves the ranking: rank cleared, returns as a first observation
    rpc(tx, "ch_admin_ban", p_user_id=d, p_reason="x", p_actor="admin@x.com")
    rpc(tx, "ch_rank_deltas", p_now=later)
    assert tx.execute("select rank from rank_state where user_id=%s", (d,)).fetchone()[0] is None


# ---------------------------------------------------------------- config

def test_config_get_set_audited_and_reason_required(tx):
    cfg = rpc(tx, "ch_config_get")
    assert cfg["daily_call_cap"] == 5 and cfg["registration_open"] is True
    # migrations may audit their own config writes (e.g. actor 'migration:judge_j3'): only count this test's rows
    base = len(audit(tx, "config_set"))
    assert all(r[0].startswith("migration:") for r in audit(tx, "config_set"))
    tx.execute("set local role service_role")
    assert rpc(tx, "ch_config_set", p_key="daily_call_cap", p_value=Jsonb(7), p_actor="admin@x.com",
               p_reason="more calls") == {"ok": True}
    tx.execute("reset role")
    assert rpc(tx, "ch_config_get")["daily_call_cap"] == 7
    assert audit(tx, "config_set")[base:] == [("admin@x.com", "daily_call_cap", {"value": 5}, {"value": 7}, "more calls")]
    assert tx.execute("select updated_by from competition_config where key='daily_call_cap'").fetchone()[0] == \
        "admin@x.com"
    for reason in (None, "", "   "):
        raises(tx, psycopg.errors.InvalidParameterValue, "ch_config_set", p_key="daily_call_cap", p_value=Jsonb(9),
               p_actor="admin@x.com", p_reason=reason)
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_config_set", p_key="daily_call_cap", p_value=Jsonb(9),
           p_actor=" ", p_reason="r")
    assert rpc(tx, "ch_config_set", p_key="nope", p_value=Jsonb(1), p_actor="a", p_reason="r")["reason"] == "unknown_key"
    assert rpc(tx, "ch_config_set", p_key="daily_call_cap", p_value=Jsonb("7"), p_actor="a",
               p_reason="r")["reason"] == "type_mismatch"
    assert rpc(tx, "ch_config_set", p_key="brodie_number", p_value=Jsonb("+15551234"), p_actor="a",
               p_reason="r")["ok"]
    assert len(audit(tx, "config_set")) - base == 2


# ---------------------------------------------------------------- admin

def test_admin_void_unvoid_adjust_audited(tx):
    uid = make_user(tx, "victim")
    call = make_call(tx, uid, et(2026, 10, 14, 9, 0), 10)
    assert rpc(tx, "ch_admin_void_call", p_call_id=call, p_reason="cheat", p_actor="admin@x.com")["ok"]
    assert rpc(tx, "ch_user_status", p_user_id=uid, p_now=NOW)["points"] == 0
    assert rpc(tx, "ch_admin_unvoid_call", p_call_id=call, p_reason="appeal", p_actor="admin@x.com")["ok"]
    assert rpc(tx, "ch_user_status", p_user_id=uid, p_now=NOW)["points"] == 10
    v = audit(tx, "void_call")
    assert v[0][:2] == ("admin@x.com", call) and v[0][2]["void"] is False and v[0][3]["void"] is True
    assert v[0][3]["void_reason"] == "cheat" and v[0][4] == "cheat"
    assert audit(tx, "unvoid_call")[0][3]["void"] is False
    r = adjust(tx, uid, -3)
    assert r["ok"] and r["points"] == 7 and r["valid_reps"] == 7 and r["reps_delta"] == -3
    a = audit(tx, "adjust_points")[0]
    assert a[2] == {"points": 10, "valid_reps": 10}
    assert a[3]["points"] == 7 and a[3]["delta"] == -3 and a[3]["valid_reps"] == 7 and a[3]["reps_delta"] == -3
    assert rpc(tx, "ch_admin_void_call", p_call_id="missing", p_reason="r", p_actor="a")["reason"] == "not_found"
    assert rpc(tx, "ch_admin_adjust", p_user_id=uuid.uuid4(), p_points=1, p_reason="r", p_actor="a")["reason"] == \
        "not_found"


def test_admin_adjust_moves_valid_reps(tx):
    """An adjustment carries a reps delta: by default it mirrors the points, so the board never shows 45 pts / 52 reps."""
    uid = make_user(tx, "repfix")
    make_call(tx, uid, et(2026, 10, 14, 9, 0), 10)
    assert (rpc(tx, "ch_user_status", p_user_id=uid, p_now=NOW)["points"],
            rpc(tx, "ch_user_status", p_user_id=uid, p_now=NOW)["valid_reps"]) == (10, 10)

    # default (no p_reps): reps move with the points
    assert adjust(tx, uid, 5)["valid_reps"] == 15
    s = rpc(tx, "ch_user_status", p_user_id=uid, p_now=NOW)
    assert (s["points"], s["valid_reps"]) == (15, 15)

    # explicit 0: a points-only correction leaves the rep count alone
    r = rpc(tx, "ch_admin_adjust", p_user_id=uid, p_points=4, p_reps=0, p_reason="power hour fix", p_actor="a@x.com")
    assert (r["points"], r["valid_reps"], r["reps_delta"]) == (19, 15, 0)

    # explicit reps: a rep-only correction leaves points alone (points delta 0 is allowed when reps move)
    r = rpc(tx, "ch_admin_adjust", p_user_id=uid, p_points=0, p_reps=-5, p_reason="miscount", p_actor="a@x.com")
    assert (r["points"], r["valid_reps"]) == (19, 10)

    # every public reader agrees, and the big board tile is just their sum
    assert tx.execute("select points, valid_reps from ch_user_stats where user_id=%s", (uid,)).fetchone() == (19, 10)
    assert tx.execute("select points, valid_reps from leaderboard_public where display_name='repfix'").fetchone() == \
        (19, 10)
    assert tx.execute("select valid_reps from user_public where display_name='repfix'").fetchone()[0] == 10
    assert rpc(tx, "ch_leaderboard", p_limit=10, p_now=NOW)[0]["valid_reps"] == 10
    assert tx.execute("select ch_valid_reps(%s)", (uid,)).fetchone()[0] == 10

    # a correction bigger than the earned reps floors at 0 rather than going negative
    rpc(tx, "ch_admin_adjust", p_user_id=uid, p_points=0, p_reps=-999, p_reason="wipe reps", p_actor="a@x.com")
    assert tx.execute("select ch_valid_reps(%s)", (uid,)).fetchone()[0] == 0
    assert tx.execute("select valid_reps from ch_user_stats where user_id=%s", (uid,)).fetchone()[0] == 0

    # per-day reporting stays judged-reps-only: an adjustment belongs to a user, not to an ET day
    assert tx.execute("select valid_reps from user_daily_public where display_name='repfix'").fetchall() == [(10,)]

    # a no-op (no points, no reps) is still refused
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_admin_adjust",
           p_user_id=uid, p_points=0, p_reps=0, p_reason="nothing", p_actor="a@x.com")


def test_admin_ban_unban_audited(tx):
    uid = make_user(tx, "baddie", handle="+16660000")
    assert rpc(tx, "ch_admin_ban", p_user_id=uid, p_reason="abuse", p_actor="admin@x.com")["ok"]
    assert rpc(tx, "ch_user_by_handle", p_handle="+16660000")["banned"] is True
    b = audit(tx, "ban")[0]
    assert b[2] == {"banned_at": None, "ban_reason": None} and b[3]["ban_reason"] == "abuse" and b[3]["banned_at"]
    assert rpc(tx, "ch_admin_unban", p_user_id=uid, p_reason="ok now", p_actor="admin@x.com")["ok"]
    assert rpc(tx, "ch_user_by_handle", p_handle="+16660000")["banned"] is False
    assert audit(tx, "unban")[0][3] == {"banned_at": None, "ban_reason": None}


@pytest.mark.parametrize("fn,args", [
    ("ch_admin_void_call", {"p_call_id": "x"}), ("ch_admin_unvoid_call", {"p_call_id": "x"}),
    ("ch_admin_adjust", {"p_points": 5}), ("ch_admin_ban", {}), ("ch_admin_unban", {}),
    ("ch_admin_queue_remove", {"p_queue_id": 1}),
])
@pytest.mark.parametrize("reason", [None, "", "  "])
def test_admin_reason_required(tx, fn, args, reason):
    uid = make_user(tx, "reasonless")
    kw = dict(args)
    if fn in ("ch_admin_adjust", "ch_admin_ban", "ch_admin_unban"):
        kw["p_user_id"] = uid
    raises(tx, psycopg.errors.InvalidParameterValue, fn, **kw, p_reason=reason, p_actor="admin@x.com")
    assert tx.execute("select count(*) from audit_log where actor='admin@x.com'").fetchone()[0] == 0


def test_admin_queue_remove_frees_claimed_line(tx):
    w = make_user(tx, "waiter")
    h = make_user(tx, "holder")
    qw = tx.execute("insert into queue (user_id, entered_at, status) values (%s, %s, 'waiting') returning id",
                    (w, NOW)).fetchone()[0]
    qh = tx.execute("insert into queue (user_id, entered_at, status, line_id, notified_at) values"
                    " (%s, %s, 'notified', 'line-1', %s) returning id", (h, NOW, NOW)).fetchone()[0]
    tx.execute("update line_state set state='claimed', user_id=%s, claimed_until=%s where line_id='line-1'",
               (h, NOW + timedelta(seconds=90)))
    assert rpc(tx, "ch_admin_queue_remove", p_queue_id=qw, p_reason="spam", p_actor="admin@x.com") == \
        {"ok": True, "lines_idled": []}
    assert tx.execute("select state, user_id from line_state").fetchone() == ("claimed", h)
    assert rpc(tx, "ch_admin_queue_remove", p_queue_id=qh, p_reason="afk", p_actor="admin@x.com") == \
        {"ok": True, "lines_idled": ["line-1"]}
    assert tx.execute("select state, user_id, claimed_until from line_state").fetchone() == ("idle", None, None)
    assert [s for (s,) in tx.execute("select status from queue order by id")] == ["left", "left"]
    rows = audit(tx, "queue_remove")
    assert [r[2]["status"] for r in rows] == ["waiting", "notified"] and rows[1][3]["lines_idled"] == ["line-1"]
    assert rpc(tx, "ch_admin_queue_remove", p_queue_id=qh, p_reason="again", p_actor="a")["reason"] == "not_active"
    assert rpc(tx, "ch_admin_queue_remove", p_queue_id=-1, p_reason="r", p_actor="a")["reason"] == "not_found"


# ---------------------------------------------------------------- outbox

def enqueue(c, key, *, handle="+17770000", body="hi", template=None, ctx=None, not_before=None, now=NOW, user=None):
    return rpc(c, "ch_outbox_enqueue", p_handle=handle, p_user_id=user, p_template=template, p_body=body,
               p_media_url=None, p_dedupe_key=key, p_not_before=not_before, p_now=now, p_ctx=ctx)


def test_outbox_enqueue_dedupe_and_handle_fallback(tx):
    r1 = enqueue(tx, "k1")
    assert r1["duplicate"] is False
    assert enqueue(tx, "k1", body="other") == {"id": r1["id"], "duplicate": True}
    uid = make_user(tx, "texted", handle="+18880000")
    r3 = enqueue(tx, "youre_up:1", handle=None, body=None, template="youre_up", ctx={"line": "line-1"}, user=uid)
    row = tx.execute("select handle, body, template, ctx, status, attempts, not_before from messages where id=%s",
                     (r3["id"],)).fetchone()
    assert row == ("+18880000", None, "youre_up", {"line": "line-1"}, "queued", 0, NOW)
    a, b = enqueue(tx, None), enqueue(tx, None)
    assert a["id"] != b["id"] and not a["duplicate"] and not b["duplicate"]
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_outbox_enqueue", p_handle="+1", p_user_id=None,
           p_template=None, p_body=None, p_media_url=None, p_dedupe_key="k9", p_not_before=None, p_now=NOW)


def test_outbox_claim_lease_reclaim_retry_and_mark(tx):
    due = enqueue(tx, "due")["id"]
    future = enqueue(tx, "future", not_before=NOW + timedelta(minutes=5))["id"]
    got = rpc(tx, "ch_outbox_claim", p_limit=10, p_now=NOW)
    assert [m["id"] for m in got] == [due] and got[0]["attempts"] == 1 and got[0]["body"] == "hi"
    assert tx.execute("select status, lease_until from messages where id=%s", (due,)).fetchone() == \
        ("sending", NOW + timedelta(seconds=60))
    assert rpc(tx, "ch_outbox_claim", p_limit=10, p_now=NOW + timedelta(seconds=30)) == []  # lease held
    got = rpc(tx, "ch_outbox_claim", p_limit=10, p_now=NOW + timedelta(minutes=5))  # lease expired + future due
    assert sorted(m["id"] for m in got) == [due, future]
    assert {m["id"]: m["attempts"] for m in got} == {due: 2, future: 1}
    # retry: back to queued with not_before = retry_at
    retry_at = NOW + timedelta(minutes=10)
    assert rpc(tx, "ch_outbox_mark", p_id=due, p_status="queued", p_provider_message_id=None, p_error="429",
               p_retry_at=retry_at)["status"] == "queued"
    assert tx.execute("select status, not_before, last_error, lease_until from messages where id=%s",
                      (due,)).fetchone() == ("queued", retry_at, "429", None)
    early = rpc(tx, "ch_outbox_claim", p_limit=10, p_now=retry_at - timedelta(seconds=1))
    assert due not in [m["id"] for m in early]  # (only the expired lease of `future` is reclaimed)
    assert [m["id"] for m in rpc(tx, "ch_outbox_claim", p_limit=10, p_now=retry_at)] == [due]
    assert rpc(tx, "ch_outbox_mark", p_id=due, p_status="sent", p_provider_message_id="pm-1", p_error=None,
               p_retry_at=None)["status"] == "sent"
    row = tx.execute("select status, provider_message_id, sent_at is not null from messages where id=%s",
                     (due,)).fetchone()
    assert row == ("sent", "pm-1", True)
    # marks after sent are no-ops
    assert rpc(tx, "ch_outbox_mark", p_id=due, p_status="failed", p_provider_message_id=None, p_error="late",
               p_retry_at=None)["changed"] is False
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_outbox_mark", p_id=due, p_status="bogus",
           p_provider_message_id=None, p_error=None, p_retry_at=None)
    # attempts exhausted: queued retry becomes failed; expired lease at max attempts becomes failed
    tx.execute("update messages set attempts=5 where id=%s", (future,))
    assert rpc(tx, "ch_outbox_mark", p_id=future, p_status="queued", p_provider_message_id=None, p_error="x",
               p_retry_at=retry_at)["status"] == "failed"
    third = enqueue(tx, "third")["id"]
    rpc(tx, "ch_outbox_claim", p_limit=10, p_now=NOW)
    tx.execute("update messages set attempts=5 where id=%s", (third,))
    assert rpc(tx, "ch_outbox_claim", p_limit=10, p_now=NOW + timedelta(minutes=2)) == []
    assert tx.execute("select status, last_error from messages where id=%s", (third,)).fetchone() == \
        ("failed", "lease_expired")


def test_outbox_mark_fenced_by_attempt(tx):
    mid = enqueue(tx, "fence")["id"]
    first = rpc(tx, "ch_outbox_claim", p_limit=1, p_now=NOW)[0]
    assert first["attempts"] == 1
    second = rpc(tx, "ch_outbox_claim", p_limit=1, p_now=NOW + timedelta(minutes=5))[0]  # lease expired -> reclaim
    assert second["id"] == mid and second["attempts"] == 2
    lease = tx.execute("select lease_until from messages where id=%s", (mid,)).fetchone()[0]
    for st in ("queued", "failed", "sent"):
        r = rpc(tx, "ch_outbox_mark", p_id=mid, p_status=st, p_provider_message_id="stale", p_error="stale",
                p_retry_at=None, p_attempt=1)
        assert r["ok"] is False and r["reason"] == "stale"
    assert tx.execute("select status, attempts, lease_until, last_error, provider_message_id from messages where id=%s",
                      (mid,)).fetchone() == ("sending", 2, lease, None, None)
    ok = rpc(tx, "ch_outbox_mark", p_id=mid, p_status="sent", p_provider_message_id="pm", p_error=None,
             p_retry_at=None, p_attempt=2)
    assert ok["ok"] and ok["status"] == "sent"


def test_outbox_claim_skip_locked_two_connections(db):
    setup = connect(db)
    c1 = connect(db, autocommit=False)
    c2 = connect(db, autocommit=False)
    try:
        ids = [enqueue(setup, f"skip-{i}-{uuid.uuid4().hex[:6]}", now=NOW - timedelta(minutes=1))["id"]
               for i in range(3)]
        first = rpc(c1, "ch_outbox_claim", p_limit=2, p_now=NOW)  # c1 holds row locks (uncommitted)
        c2.execute("set local lock_timeout = '2s'")
        second = rpc(c2, "ch_outbox_claim", p_limit=10, p_now=NOW)  # must not block on c1's rows
        a, b = {m["id"] for m in first}, {m["id"] for m in second}
        assert len(a) == 2 and len(b) == 1 and a | b == set(ids) and not (a & b)
        c1.commit()
        c2.commit()
        assert setup.execute("select count(*) from messages where id = any(%s) and status='sending' and attempts=1",
                             (ids,)).fetchone()[0] == 3
    finally:
        c1.rollback()
        c2.rollback()
        setup.execute("delete from messages where dedupe_key like 'skip-%'")
        for c in (c1, c2, setup):
            c.close()


# ---------------------------------------------------------------- inbound / heartbeat

def test_inbound_record_dedupe(tx):
    uid = make_user(tx, "sender", handle="+19990000")
    r1 = rpc(tx, "ch_inbound_record", p_provider_message_id="in-1", p_handle="+19990000", p_body="JOIN", p_now=NOW)
    assert r1["duplicate"] is False and r1["user_id"] == str(uid)
    r2 = rpc(tx, "ch_inbound_record", p_provider_message_id="in-1", p_handle="+19990000", p_body="JOIN", p_now=NOW)
    assert r2 == {"id": r1["id"], "duplicate": True, "user_id": str(uid)}
    assert tx.execute("select direction, status, body from messages where id=%s", (r1["id"],)).fetchone() == \
        ("in", "received", "JOIN")
    r3 = rpc(tx, "ch_inbound_record", p_provider_message_id="in-2", p_handle="+10000000", p_body="hi", p_now=NOW)
    assert r3["duplicate"] is False and r3["user_id"] is None


def test_heartbeat_upsert(tx):
    assert rpc(tx, "ch_heartbeat", p_component="worker", p_detail={"v": 1}, p_now=NOW) == {"ok": True}
    rpc(tx, "ch_heartbeat", p_component="worker", p_detail={"v": 2}, p_now=NOW + timedelta(seconds=5))
    assert tx.execute("select at, detail from heartbeats where component='worker'").fetchall() == \
        [(NOW + timedelta(seconds=5), {"v": 2})]
    raises(tx, psycopg.errors.InvalidParameterValue, "ch_heartbeat", p_component=" ", p_detail=None, p_now=NOW)
