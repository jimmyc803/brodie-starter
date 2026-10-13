"""Migration 20261025_challenge_metrics.sql: referral codes, join attribution, team flag, site visits, admin metrics."""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.types.json import Jsonb

from db.test.harness import MIGRATIONS, connect

ET = ZoneInfo("America/New_York")
MIGRATION = MIGRATIONS / "20261025_challenge_metrics.sql"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=ET)
CODE_RE = re.compile(r"^[23456789BCDFGHJKLMNPQRSTVWXZ]{6}$")
RPCS = ["ch_join_attribution", "ch_site_visit", "ch_admin_set_team", "ch_admin_metrics", "ch_user_by_handle",
        "ch_user_status", "ch_new_ref_code", "ch_attribute_join", "ch_norm_ref_code", "ch_norm_source"]


def rpc(c, fn: str, **kw):
    params = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in kw.items()}
    return c.execute(f"select {fn}({', '.join(f'{k} => %({k})s' for k in kw)})", params).fetchone()[0]


def coach(c):
    return c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]


def make_user(c, name, joined_at=None, handle=None, team=False, referred_by=None):
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at, is_team, referred_by)"
                    " values (%s, %s, %s, %s, %s, %s) returning id",
                    (coach(c), name, name, joined_at or NOW - timedelta(days=1), team, referred_by)).fetchone()[0]
    if handle:
        c.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s, %s, 'phone', 'admin')",
                  (handle, uid))
    return uid


def ref_code(c, uid):
    return c.execute("select ref_code from clients where id = %s", (uid,)).fetchone()[0]


def join(c, handle, name, now=NOW):
    assert rpc(c, "ch_join_start", p_handle=handle, p_display_name=name, p_now=now)["ok"]
    r = rpc(c, "ch_join_confirm", p_handle=handle, p_now=now)
    assert r["ok"], r
    return uuid.UUID(str(r["user_id"]))


def make_call(c, user_id, connected_at, n_valid=0, decision="accept", counted=True):
    call_id = f"call-{uuid.uuid4().hex[:12]}"
    sid = None
    if user_id is not None:
        sid = c.execute("insert into sessions (client_id, started_at, ended_at) values (%s, %s, %s) returning id",
                        (user_id, connected_at, connected_at + timedelta(seconds=195))).fetchone()[0]
    c.execute("insert into calls (id, line_id, user_id, decision, connected_at, ended_at, counted_toward_cap,"
              " session_id, committed_at) values (%s, 'line-1', %s, %s, %s, %s, %s, %s, %s)",
              (call_id, user_id, decision, connected_at, connected_at + timedelta(seconds=195), counted, sid,
               connected_at + timedelta(seconds=200)))
    if n_valid:
        set_id = c.execute("insert into sets (session_id, exercise_key, set_number, planned_reps, completed_reps)"
                           " values (%s, 'pushups', 1, 0, %s) returning id", (sid, n_valid)).fetchone()[0]
        for i in range(n_valid):
            c.execute("insert into reps (set_id, rep_number, t, valid, points, multiplier, reject_reasons, at,"
                      " in_challenge) values (%s, %s, %s, true, 1, 1, '{}', %s, false)",
                      (set_id, i + 1, 10 + i, connected_at + timedelta(seconds=10 + i)))
    return call_id


@pytest.fixture
def tx(db):
    c = connect(db, autocommit=False)
    try:
        c.execute("truncate clients, calls, messages, audit_log, join_pending, join_attribution, site_visits"
                  " restart identity cascade")
        c.execute("update competition_config set value = 'false' where key = 'competition_frozen'")
        c.execute("update competition_config set value = 'true' where key = 'registration_open'")
        yield c
    finally:
        c.rollback()
        c.close()


# ---------------------------------------------------------------- migration / grants

def test_migration_idempotent_backfills_codes_and_grants(pg_cluster, db):
    name = db.split("dbname=")[1].split()[0]
    with connect(db) as c:
        c.execute("truncate clients restart identity cascade")
        c.execute("alter table clients disable trigger ch_clients_ref_code")
        old = make_user(c, "Old_Timer")
        never = c.execute("insert into clients (coach_id, name) values (%s, 'legacy') returning id",
                          (coach(c),)).fetchone()[0]
        c.execute("alter table clients enable trigger ch_clients_ref_code")
        assert ref_code(c, old) is None
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)
    with connect(db) as c:
        code = ref_code(c, old)
        assert CODE_RE.match(code)
        assert ref_code(c, never) is None  # non-participants get no code
        pg_cluster.apply_file(name, MIGRATION)
        assert ref_code(c, old) == code  # re-applying never rotates an existing code
        rows = c.execute(
            "select p.proname, p.prosecdef, has_function_privilege('anon', p.oid, 'execute'),"
            " has_function_privilege('authenticated', p.oid, 'execute'),"
            " has_function_privilege('service_role', p.oid, 'execute'), p.proconfig"
            " from pg_proc p where p.pronamespace = 'public'::regnamespace and p.proname = any(%s)", (RPCS,)).fetchall()
        assert {r[0] for r in rows} == set(RPCS)
        for proname, secdef, anon, authd, service, cfg in rows:
            assert secdef and not anon and not authd and service, proname
            assert "search_path=public" in (cfg or []), proname
        rls = dict(c.execute("select relname, relrowsecurity from pg_class where relnamespace='public'::regnamespace"
                             " and relname in ('join_attribution', 'site_visits')").fetchall())
        assert rls == {"join_attribution": True, "site_visits": True}
        for table in ("join_attribution", "site_visits", "clients"):
            for role in ("anon", "authenticated"):
                assert not c.execute("select has_table_privilege(%s, %s, 'select')", (role, table)).fetchone()[0]
        c.execute("truncate clients restart identity cascade")


def test_codes_assigned_on_join_and_unique(tx):
    a = make_user(tx, "Alpha")
    b = make_user(tx, "Bravo")
    assert CODE_RE.match(ref_code(tx, a)) and ref_code(tx, a) != ref_code(tx, b)
    pending = tx.execute("insert into clients (coach_id, name) values (%s, 'x') returning id", (coach(tx),)).fetchone()[0]
    assert ref_code(tx, pending) is None
    tx.execute("update clients set joined_at = %s where id = %s", (NOW, pending))
    assert CODE_RE.match(ref_code(tx, pending))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with tx.transaction():
            tx.execute("update clients set ref_code = %s where id = %s", (ref_code(tx, a), b))
    with pytest.raises(psycopg.errors.CheckViolation):
        with tx.transaction():
            tx.execute("update clients set acquisition_source = 'Bad Source' where id = %s", (a,))


# ---------------------------------------------------------------- attribution

def test_sms_join_with_ref_and_source_records_referrer(tx):
    a = make_user(tx, "Alpha", handle="+15550000001")
    code = ref_code(tx, a)
    r = rpc(tx, "ch_join_attribution", p_handle=" +15550000002 ", p_ref_code=code.lower(), p_source="TikTok",
            p_now=NOW)
    assert r == {"ok": True, "reason": "ok", "ref_valid": True}
    b = join(tx, "+15550000002", "Bravo")
    assert tx.execute("select referred_by, acquisition_source from clients where id = %s", (b,)).fetchone() == (a, "tiktok")
    assert tx.execute("select count(*) from join_attribution").fetchone()[0] == 0
    assert CODE_RE.match(ref_code(tx, b))
    assert rpc(tx, "ch_user_by_handle", p_handle="+15550000002")["ref_code"] == ref_code(tx, b)
    assert rpc(tx, "ch_user_status", p_user_id=b, p_now=NOW)["ref_code"] == ref_code(tx, b)


def test_ref_only_source_is_referral_and_first_valid_code_wins(tx):
    a = make_user(tx, "Alpha")
    z = make_user(tx, "Zulu")
    h = "+15550000003"
    assert rpc(tx, "ch_join_attribution", p_handle=h, p_ref_code="ZZZZZZ", p_source=None, p_now=NOW) == \
        {"ok": False, "reason": "empty", "ref_valid": False}  # unknown code: nothing stored
    assert rpc(tx, "ch_join_attribution", p_handle=h, p_ref_code=ref_code(tx, a), p_source=None, p_now=NOW)["ok"]
    assert rpc(tx, "ch_join_attribution", p_handle=h, p_ref_code=ref_code(tx, z), p_source="ig", p_now=NOW)["ok"]
    c = join(tx, h, "Charlie")
    assert tx.execute("select referred_by, acquisition_source from clients where id = %s", (c,)).fetchone() == (a, "ig")
    d = join(tx, "+15550000004", "Delta")  # plain JOIN: untouched
    assert tx.execute("select referred_by, acquisition_source from clients where id = %s", (d,)).fetchone() == (None, None)
    h2 = "+15550000005"
    rpc(tx, "ch_join_attribution", p_handle=h2, p_ref_code=ref_code(tx, a), p_source=None, p_now=NOW)
    e = join(tx, h2, "Echo")
    assert tx.execute("select referred_by, acquisition_source from clients where id = %s", (e,)).fetchone() == (a, "referral")


def test_attribution_validation_and_registered_handles(tx):
    make_user(tx, "Alpha", handle="+15550000001")
    assert rpc(tx, "ch_join_attribution", p_handle="+15550000001", p_ref_code=None, p_source="x", p_now=NOW) == \
        {"ok": False, "reason": "already_registered", "ref_valid": False}
    assert rpc(tx, "ch_join_attribution", p_handle="+15550000009", p_ref_code="no!", p_source="bad source",
               p_now=NOW)["reason"] == "empty"
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with tx.transaction():
            rpc(tx, "ch_join_attribution", p_handle=" ", p_ref_code=None, p_source="x", p_now=NOW)


def test_upgrade_of_handle_linked_client_is_attributed(tx):
    a = make_user(tx, "Alpha")
    h = "+15550000007"
    legacy = tx.execute("insert into clients (coach_id, name) values (%s, 'legacy') returning id", (coach(tx),)).fetchone()[0]
    tx.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s, %s, 'phone', 'claim_window')",
               (h, legacy))
    rpc(tx, "ch_join_attribution", p_handle=h, p_ref_code=ref_code(tx, a), p_source=None, p_now=NOW)
    assert join(tx, h, "Golf") == legacy
    assert tx.execute("select referred_by, acquisition_source from clients where id = %s", (legacy,)).fetchone() == \
        (a, "referral")


# ---------------------------------------------------------------- team flag

def test_admin_set_team_audited(tx):
    a = make_user(tx, "Alpha")
    assert rpc(tx, "ch_admin_set_team", p_user_id=a, p_team=True, p_reason="staff phone", p_actor="ops@x.com",
               p_now=NOW) == {"ok": True, "changed": True}
    assert rpc(tx, "ch_admin_set_team", p_user_id=a, p_team=True, p_reason="again", p_actor="ops@x.com",
               p_now=NOW) == {"ok": True, "changed": False}
    assert tx.execute("select is_team from clients where id = %s", (a,)).fetchone()[0] is True
    rows = tx.execute("select actor, target, before, after, reason from audit_log where action = 'set_team'"
                      " order by id").fetchall()
    assert rows[0] == ("ops@x.com", str(a), {"is_team": False}, {"is_team": True}, "staff phone")
    assert rpc(tx, "ch_admin_set_team", p_user_id=uuid.uuid4(), p_team=True, p_reason="x y z", p_actor="a",
               p_now=NOW) == {"ok": False, "reason": "not_found"}
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with tx.transaction():
            rpc(tx, "ch_admin_set_team", p_user_id=a, p_team=False, p_reason=" ", p_actor="a", p_now=NOW)


# ---------------------------------------------------------------- site visits

def test_site_visit_normalizes_and_stores_no_identifiers(tx):
    a = make_user(tx, "Alpha")
    assert rpc(tx, "ch_site_visit", p_kind="landing", p_path="/join?ref=abc#x", p_source="TikTok",
               p_ref_code=ref_code(tx, a).lower(), p_referrer_host="WWW.TikTok.com", p_now=NOW) == {"ok": True}
    rpc(tx, "ch_site_visit", p_kind="join_tap", p_path="javascript:alert(1)", p_source="<script>", p_ref_code="!",
        p_referrer_host="evil host/", p_now=NOW)
    rows = tx.execute("select kind, path, source, ref_code, referrer_host from site_visits order by id").fetchall()
    assert rows == [("landing", "/join", "tiktok", ref_code(tx, a), "www.tiktok.com"),
                    ("join_tap", "/", None, None, None)]
    cols = {r[0] for r in tx.execute("select column_name from information_schema.columns"
                                     " where table_name = 'site_visits'")}
    assert cols == {"id", "at", "kind", "path", "source", "ref_code", "referrer_host"}
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with tx.transaction():
            rpc(tx, "ch_site_visit", p_kind="pageview", p_path="/", p_source=None, p_ref_code=None,
                p_referrer_host=None, p_now=NOW)


# ---------------------------------------------------------------- metrics

def seed_metrics(tx):
    team = make_user(tx, "Team_One", joined_at=NOW - timedelta(days=2), team=True)
    b = make_user(tx, "Bravo", joined_at=NOW - timedelta(days=1), referred_by=team)
    # 23:30 ET yesterday is 03:30 UTC today: it must land on yesterday's ET day.
    c = make_user(tx, "Charlie", joined_at=datetime(2026, 10, 14, 23, 30, tzinfo=ET), referred_by=b)
    d = make_user(tx, "Delta", joined_at=NOW - timedelta(hours=1), referred_by=c)
    e = make_user(tx, "Echo", joined_at=NOW - timedelta(hours=2), referred_by=b)
    tx.execute("update clients set acquisition_source = 'tiktok' where id = %s", (e,))
    tx.execute("update clients set opted_out_at = %s where id = %s", (NOW, e))
    tx.execute("update clients set banned_at = %s where id = %s", (NOW, d))
    make_call(tx, team, NOW - timedelta(hours=3), n_valid=4)
    make_call(tx, b, NOW - timedelta(hours=2), n_valid=3)
    make_call(tx, b, NOW - timedelta(days=1), n_valid=2, counted=False)
    make_call(tx, c, NOW - timedelta(minutes=30), decision="reject", counted=False)
    make_call(tx, None, NOW - timedelta(minutes=20), decision="reject", counted=False)
    for kind, src in (("landing", "tiktok"), ("landing", None), ("landing", "tiktok"), ("join_tap", None)):
        rpc(tx, "ch_site_visit", p_kind=kind, p_path="/join", p_source=src, p_ref_code=None, p_referrer_host=None,
            p_now=NOW - timedelta(hours=1))
    tx.execute("insert into messages (direction, handle, body, status, created_at) values"
               " ('in', '+15559990001', 'join  someone', 'received', %s),"
               " ('in', '+15559990001', 'JOIN someone_else', 'received', %s),"
               " ('in', '+15559990002', 'joining?', 'received', %s),"
               " ('in', '+15559990003', 'QUEUE', 'received', %s)", (NOW, NOW, NOW, NOW))
    tx.execute("insert into join_pending (handle, display_name, created_at) values ('+15559990004', 'Pending', %s)", (NOW,))
    return team, b, c, d, e


def test_admin_metrics_excludes_team(tx):
    team, b, c, d, e = seed_metrics(tx)
    m = rpc(tx, "ch_admin_metrics", p_include_team=False, p_now=NOW, p_days=7)
    k = m["kpis"]
    assert (k["joined"], k["joined_today"], k["called_users"], k["scored_users"]) == (4, 2, 2, 1)
    assert (k["calls_connected"], k["calls_accepted"], k["calls_counted"], k["valid_reps"]) == (4, 2, 1, 5)
    assert (k["dau_today"], k["opted_out"], k["banned"], k["team_accounts"], k["pending_joins"]) == (2, 1, 1, 1, 1)
    assert m["signups_daily"] == [{"day": "2026-10-14", "n": 2}, {"day": "2026-10-15", "n": 2}]
    assert m["signups_before"] == 0
    # Last 48 h: Bravo (10-14 16:00Z), Charlie (10-15 03:00Z), Echo, Delta; the team account is excluded.
    assert [(r["hour"][:13], r["n"]) for r in m["signups_hourly"]] == [
        ("2026-10-14T16", 1), ("2026-10-15T03", 1), ("2026-10-15T14", 1), ("2026-10-15T15", 1)]
    days = {r["day"]: r for r in m["calls_daily"]}
    assert days["2026-10-15"] == {"day": "2026-10-15", "connected": 3, "accepted": 1, "valid_reps": 3}
    assert days["2026-10-14"]["valid_reps"] == 2
    assert m["visits_daily"] == [{"day": "2026-10-15", "landings": 3, "join_taps": 1}]
    # started = 4 joined + 2 unregistered handles that texted JOIN (+15559990001 twice) or are pending.
    assert m["funnel"] == {"visits": 3, "join_taps": 1, "join_started": 6, "joined": 4, "called": 2, "scored": 1}
    v = m["virality"]
    assert v["referred"] == 4  # Bravo's referrer is a team account, but Bravo is a real referred signup
    assert v["active_referrers"] == 2  # Bravo, Charlie (the team referrer is excluded)
    assert {s["source"]: s["n"] for s in v["sources"]} == {"direct": 3, "tiktok": 1}
    assert v["visit_sources"] == [{"source": "tiktok", "n": 2}, {"source": "direct", "n": 1}]
    assert v["top_referrers"][0] == {"user_id": str(b), "display_name": "Bravo", "referred": 2, "referred_called": 1}
    assert v["max_depth"] == 2 and v["second_gen"] == 1
    assert "+1555" not in str(m)


def test_admin_metrics_includes_team_and_handles_empty(tx):
    team, b, *_ = seed_metrics(tx)
    m = rpc(tx, "ch_admin_metrics", p_include_team=True, p_now=NOW, p_days=7)
    assert m["kpis"]["joined"] == 5 and m["kpis"]["calls_connected"] == 5 and m["kpis"]["valid_reps"] == 9
    assert m["virality"]["max_depth"] == 3 and m["virality"]["active_referrers"] == 3
    assert m["funnel"]["join_started"] == 7
    for table in ("site_visits", "join_pending", "messages", "reps", "sets", "calls", "sessions"):
        tx.execute(f"delete from {table}")
    tx.execute("update clients set referred_by = null")
    tx.execute("delete from clients")
    empty = rpc(tx, "ch_admin_metrics", p_include_team=False, p_now=NOW, p_days=None)
    assert empty["days"] == 30 and empty["signups_daily"] == [] and empty["virality"]["top_referrers"] == []
    assert empty["funnel"] == {"visits": 0, "join_taps": 0, "join_started": 0, "joined": 0, "called": 0, "scored": 0}
    assert empty["virality"]["max_depth"] == 0
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        with tx.transaction():
            rpc(tx, "ch_admin_metrics", p_include_team=False, p_now=None, p_days=7)
