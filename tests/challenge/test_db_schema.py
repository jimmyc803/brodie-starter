"""Migration 20261012_challenge_schema.sql: idempotency, grants/RLS, public views, scoring helpers, site pulse."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg
import pytest

from db.test.harness import MIGRATIONS, TEMPLATE_DB, connect

ET = ZoneInfo("America/New_York")
MIGRATION = MIGRATIONS / "20261012_challenge_schema.sql"
PUBLIC_VIEWS = ["leaderboard_public", "user_public", "user_daily_public", "call_result_public",
                "line_status_public", "power_hour_public", "competition_public"]
ANON_DENIED = ["clients", "client_handles", "calls", "reps", "messages", "queue", "line_state",
               "competition_config", "sessions", "audit_log", "score_adjustments", "admin_allowlist",
               "ch_call_stats", "ch_score_events", "ch_user_stats"]
NEW_TABLES = ["client_handles", "join_pending", "lines", "line_state", "queue", "calls", "competition_config",
              "power_hours", "messages", "audit_log", "score_adjustments", "rank_state", "admin_allowlist",
              "heartbeats", "site_pulse"]


def et(*args) -> datetime:
    return datetime(*args, tzinfo=ET)


def make_user(conn, name: str, joined_at: datetime | None = None) -> uuid.UUID:
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    return conn.execute(
        "insert into clients (coach_id, name, display_name, joined_at) values (%s, %s, %s, %s) returning id",
        (coach, name, name, joined_at or et(2026, 10, 12, 20, 0))).fetchone()[0]


def make_call(conn, user_id, connected_at: datetime, reps: list[tuple[bool, int, list[str]]] | None = None,
              *, void=False, counted=True, call_id: str | None = None, rep_offset_s: float = 10.0) -> str:
    """reps: (valid, points, reject_reasons); rep i happens at connected_at + rep_offset_s + i seconds."""
    call_id = call_id or f"call-{uuid.uuid4().hex[:12]}"
    session_id = conn.execute("insert into sessions (client_id, started_at, ended_at) values (%s, %s, %s) returning id",
                              (user_id, connected_at, connected_at + timedelta(seconds=195))).fetchone()[0]
    conn.execute(
        "insert into calls (id, line_id, user_id, decision, connected_at, ended_at, counted_toward_cap, void, session_id,"
        " liveness_result, committed_at) values (%s, 'line-1', %s, 'accept', %s, %s, %s, %s, %s, 'pass', %s)",
        (call_id, user_id, connected_at, connected_at + timedelta(seconds=195), counted, void, session_id,
         connected_at + timedelta(seconds=200)))
    set_id = conn.execute("insert into sets (session_id, exercise_key, set_number, planned_reps, completed_reps)"
                          " values (%s, 'pushups', 1, 0, %s) returning id",
                          (session_id, sum(1 for r in reps or [] if r[0]))).fetchone()[0]
    for i, (valid, points, reasons) in enumerate(reps or []):
        conn.execute(
            "insert into reps (set_id, rep_number, t, valid, points, multiplier, reject_reasons, at, in_challenge)"
            " values (%s, %s, %s, %s, %s, %s, %s, %s, false)",
            (set_id, i + 1, rep_offset_s + i, valid, points, max(points, 1), reasons,
             connected_at + timedelta(seconds=rep_offset_s + i)))
    return call_id


@pytest.fixture
def tx(db):
    """Superuser connection inside a transaction that is rolled back after the test."""
    c = connect(db, autocommit=False)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


# ---------------------------------------------------------------- migration

def test_migration_applies_twice_without_duplicate_seed(pg_cluster, db):
    name = db.split("dbname=")[1].split()[0]
    pg_cluster.apply_file(name, MIGRATION)
    pg_cluster.apply_file(name, MIGRATION)
    with connect(db) as c:
        assert c.execute("select count(*) from coaches where name='Brodie Challenge'").fetchone()[0] == 1
        coach_cfg, coach_id = c.execute(
            "select k.value #>> '{}', (select id::text from coaches where name='Brodie Challenge')"
            " from competition_config k where key='challenge_coach_id'").fetchone()
        assert coach_cfg == coach_id
        assert c.execute("select id, chert_agent_name, active from lines").fetchall() == [("line-1", "brodie", True)]
        assert c.execute("select line_id, state from line_state").fetchall() == [("line-1", "idle")]
        assert c.execute("select count(*) from site_pulse").fetchone()[0] == 1
        keys = {k for (k,) in c.execute("select key from competition_config")}
        assert {"window_start", "window_end", "call_count_s", "call_reveal_s", "daily_call_cap", "claim_window_s",
                "line_offline_gap_s", "min_counted_call_s", "in_call_timeout_extra_s", "power_hour_window",
                "power_multiplier", "rank_drop_min", "rank_drop_throttle_h", "quiet_hours", "recap_hour",
                "streak_risk_hour", "avatar_level_thresholds",
                "judge_thresholds", "registration_open", "competition_frozen", "swearing", "site_url",
                "brodie_number", "team_alert_handles", "challenge_coach_id", "outbound_rate_per_min",
                "ufc_fighter", "first_prize", "drawing_prize", "claim_grace_s", "worker_stale_s"} == keys
        assert c.execute("select value from competition_config where key='daily_call_cap'").fetchone()[0] == 5
        assert c.execute("select ch_cfg('window_start') #>> '{}'").fetchone()[0] == "2026-10-12T20:00:00-04:00"


def test_template_has_no_open_connections_and_program_upload_applied(pg_dsn):
    with connect(pg_dsn) as c:
        n = c.execute("select count(*) from pg_stat_activity where datname=%s", (TEMPLATE_DB,)).fetchone()[0]
        assert n == 0
    with connect(pg_dsn.replace("dbname=postgres", f"dbname={TEMPLATE_DB}")) as c:
        assert c.execute("select count(*) from storage.buckets where id='programs'").fetchone()[0] == 1


def test_contract_columns_present(conn):
    cols = lambda t: {r[0] for r in conn.execute(  # noqa: E731
        "select column_name from information_schema.columns where table_schema='public' and table_name=%s", (t,))}
    assert {"display_name", "joined_at", "age_confirmed_at", "rules_accepted_at", "opted_out_at", "banned_at",
            "ban_reason", "auth_user_id"} <= cols("clients")
    assert {"valid", "reject_reasons", "multiplier", "points", "at", "shoulder_elbow_gap", "shoulder_wrist_drop",
            "max_hip_line_dev_deg", "classifier_labels", "in_challenge", "judge_version", "torso_ok", "side"} <= cols("reps")
    assert {"ctx", "lease_until", "dedupe_key", "provider_message_id", "not_before"} <= cols("messages")
    body_nullable = conn.execute("select is_nullable from information_schema.columns where table_name='messages'"
                                 " and column_name='body'").fetchone()[0]
    assert body_nullable == "YES"


def test_rls_enabled_on_new_tables_and_realtime_publication(conn):
    rows = dict(conn.execute("select relname, relrowsecurity from pg_class where relnamespace='public'::regnamespace"
                             " and relname = any(%s)", (NEW_TABLES,)).fetchall())
    assert rows == {t: True for t in NEW_TABLES}
    assert conn.execute("select count(*) from pg_publication_tables where pubname='supabase_realtime'"
                        " and tablename='site_pulse'").fetchone()[0] == 1


def test_display_name_unique_case_insensitive(tx):
    make_user(tx, "Same_Name")
    with pytest.raises(psycopg.errors.UniqueViolation):
        make_user(tx, "same_name")


# ---------------------------------------------------------------- anon access

def test_anon_can_read_public_views(tx):
    u = make_user(tx, "viewer1")
    make_call(tx, u, et(2026, 10, 13, 12, 0), [(True, 1, []), (False, 0, ["too_shallow"])])
    tx.execute("set local role anon")
    for v in PUBLIC_VIEWS:
        tx.execute(f"select * from {v}").fetchall()
    assert tx.execute("select display_name, points, valid_reps from leaderboard_public").fetchall() == [("viewer1", 1, 1)]
    assert tx.execute("select count(*) from site_pulse").fetchone()[0] == 1


@pytest.mark.parametrize("table", ANON_DENIED)
def test_anon_denied_on_base_tables(db, table):
    with connect(db, autocommit=False) as c:
        c.execute("set local role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute(f"select * from {table} limit 1")
        c.rollback()


@pytest.mark.parametrize("fn", ["ch_cfg('team_alert_handles')", "ch_user_points(gen_random_uuid())",
                                "ch_streak(gen_random_uuid(), now())"])
def test_anon_cannot_call_table_reading_helpers(db, fn):
    for role in ("anon", "authenticated"):
        with connect(db, autocommit=False) as c:
            c.execute(f"set local role {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(f"select {fn}")
            c.rollback()


def test_anon_cannot_write_site_pulse(db):
    with connect(db, autocommit=False) as c:
        c.execute("set local role anon")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("update site_pulse set bumped_at = now()")
        c.rollback()


def test_public_views_expose_no_identifiers(conn):
    for v in PUBLIC_VIEWS:
        cols = [r[0] for r in conn.execute(
            "select column_name from information_schema.columns where table_schema='public' and table_name=%s", (v,))]
        assert cols, v
        for col in cols:
            assert not any(bad in col for bad in ("handle", "phone", "email", "user_id")), (v, col)
    lb = [r[0] for r in conn.execute("select column_name from information_schema.columns where table_name="
                                     "'leaderboard_public' order by ordinal_position")]
    assert lb == ["rank", "public_id", "display_name", "points", "valid_reps", "streak", "avatar_level", "badges",
                  "reached_at"]


# ---------------------------------------------------------------- scoring

def test_points_with_multiplier_void_and_adjustments(tx):
    a = make_user(tx, "alpha", et(2026, 10, 12, 20, 0))
    b = make_user(tx, "bravo", et(2026, 10, 12, 21, 0))
    c = make_user(tx, "charlie", et(2026, 10, 12, 22, 0))
    # alpha: 3 valid (1 normal + 2 power-hour at 2x) + 1 rejected = 5 points, 3 valid reps
    make_call(tx, a, et(2026, 10, 13, 15, 0), [(True, 1, []), (True, 2, []), (True, 2, []), (False, 0, ["knees_down"])])
    # alpha: void call does not count
    make_call(tx, a, et(2026, 10, 13, 16, 0), [(True, 1, [])] * 4, void=True)
    # bravo: 4 points + adjustment -1 (made earlier than alpha's last rep) => 3
    make_call(tx, b, et(2026, 10, 13, 14, 0), [(True, 1, [])] * 4)
    tx.execute("insert into score_adjustments (user_id, points, reason, actor, at) values (%s, -1, 'test', 'admin', %s)",
               (b, et(2026, 10, 13, 14, 30)))
    # charlie: out-of-window reps were zeroed at commit (points 0 + reason) -> no points, no valid reps
    make_call(tx, c, et(2026, 10, 13, 10, 0), [(True, 0, ["after_count"])], rep_offset_s=181)
    make_call(tx, c, et(2026, 10, 12, 19, 58), [(True, 0, ["before_start"])], rep_offset_s=5)

    assert tx.execute("select ch_user_points(%s), ch_valid_reps(%s)", (a, a)).fetchone() == (5, 3)
    assert tx.execute("select ch_user_points(%s), ch_valid_reps(%s)", (b, b)).fetchone() == (3, 4)
    assert tx.execute("select ch_user_points(%s), ch_valid_reps(%s)", (c, c)).fetchone() == (0, 0)
    rows = tx.execute("select rank, display_name, points, valid_reps from leaderboard_public order by rank").fetchall()
    assert rows == [(1, "alpha", 5, 3), (2, "bravo", 3, 4), (3, "charlie", 0, 0)]
    # config edits never retroactively change persisted points
    tx.execute("update competition_config set value = to_jsonb('2026-10-13T15:00:30-04:00'::text) where key='window_start'")
    tx.execute("update competition_config set value = '1' where key='call_count_s'")
    assert tx.execute("select ch_user_points(%s), ch_valid_reps(%s)", (a, a)).fetchone() == (5, 3)
    assert tx.execute("select points, valid_reps from leaderboard_public where display_name='alpha'").fetchone() == (5, 3)
    # tie on points -> earlier reached_at ranks first
    tx.execute("insert into score_adjustments (user_id, points, reason, actor, at) values (%s, 2, 'tie', 'admin', %s)",
               (b, et(2026, 10, 13, 18, 0)))
    rows = tx.execute("select display_name, points from leaderboard_public order by rank").fetchall()
    assert rows[:2] == [("alpha", 5), ("bravo", 5)]
    pub = tx.execute("select public_id, best_call_points from user_public where display_name='alpha'").fetchone()
    assert pub[0] == tx.execute("select md5(%s::text)", (a,)).fetchone()[0] and pub[1] == 5


def test_call_result_public_reasons_and_standing(tx):
    a = make_user(tx, "delta")
    b = make_user(tx, "echo")
    make_call(tx, b, et(2026, 10, 13, 9, 0), [(True, 1, [])] * 3)
    cid = make_call(tx, a, et(2026, 10, 13, 12, 0),
                    [(True, 1, []), (False, 0, ["too_shallow"]), (False, 0, ["too_shallow", "hips_sag"])])
    row = tx.execute("select valid_reps, rejected_reps, points, reasons, rank_after, total_points_after"
                     " from call_result_public where call_id=%s", (cid,)).fetchone()
    assert row == (1, 2, 1, {"too_shallow": 2, "hips_sag": 1}, 2, 1)


CR_COLS = ("points_before, avatar_level_before, total_points_after, avatar_level_after, rank_before, rank_after")


def test_call_result_before_after_ties_and_zero_point_users(tx):
    j = et(2026, 10, 12, 20, 0)
    a = make_user(tx, "hotel", j)                          # earliest joiner
    b = make_user(tx, "india", j + timedelta(minutes=1))
    z = make_user(tx, "juliet", j + timedelta(minutes=2))  # never scores, still ranked
    make_call(tx, a, et(2026, 10, 13, 9, 0), [(True, 1, [])] * 20)   # hotel 20 by 09:00:29
    make_call(tx, b, et(2026, 10, 13, 10, 0), [(True, 1, [])] * 20)  # india 20 by 10:00:29 (tie, reached later)
    cid = make_call(tx, b, et(2026, 10, 13, 12, 0), [(True, 1, [])] * 6)
    q = f"select {CR_COLS} from call_result_public where call_id=%s"
    # before: india 20 vs hotel 20, hotel reached first -> india #2; after: india 26 -> #1; levels 1 (<25) -> 2
    assert tx.execute(q, (cid,)).fetchone() == (20, 1, 26, 2, 2, 1)
    # hotel's first call: before = 0 points; tied at 0 with india/juliet -> earliest joiner (hotel) is #1
    first = tx.execute("select id from calls where user_id=%s", (a,)).fetchone()[0]
    assert tx.execute(q, (first,)).fetchone() == (0, 1, 20, 1, 1, 1)
    # a zero-point user ranks after everyone with points; joined_at breaks the 0-point tie
    zc = make_call(tx, z, et(2026, 10, 13, 13, 0), [(False, 0, ["too_fast"])])
    assert tx.execute(q, (zc,)).fetchone() == (0, 1, 0, 1, 3, 3)
    # events are filtered by their own time, not by call connect time: an adjustment after this call's end
    # does not change its historical standing; one before it does
    tx.execute("insert into score_adjustments (user_id, points, reason, actor, at) values (%s, 50, 'late', 'admin', %s)",
               (a, et(2026, 10, 13, 18, 0)))
    assert tx.execute(q, (cid,)).fetchone() == (20, 1, 26, 2, 2, 1)
    tx.execute("insert into score_adjustments (user_id, points, reason, actor, at) values (%s, 10, 'early', 'admin', %s)",
               (a, et(2026, 10, 13, 11, 0)))
    # hotel 30 before -> india #2 before; after 26 < 30 -> india #2 after (was #1 without the early adjustment)
    assert tx.execute(q, (cid,)).fetchone() == (20, 1, 26, 2, 2, 2)
    # leaderboard agrees with the full ordering now (hotel 80, india 26, juliet 0)
    assert tx.execute("select display_name from leaderboard_public order by rank").fetchall() == [
        ("hotel",), ("india",), ("juliet",)]


def test_competition_public_exposes_thresholds(tx):
    tx.execute("set local role anon")
    assert tx.execute("select avatar_level_thresholds from competition_public").fetchone()[0] == [
        0, 25, 60, 120, 200, 300, 450, 650, 900, 1200]


def test_streak_across_et_midnight(tx):
    u = make_user(tx, "foxtrot")
    late, early = et(2026, 10, 13, 23, 59), et(2026, 10, 14, 0, 1)
    assert late.astimezone(ZoneInfo("UTC")).date() == early.astimezone(ZoneInfo("UTC")).date()  # same UTC day
    assert tx.execute("select ch_et_day(%s), ch_et_day(%s)", (late, early)).fetchone() == (
        late.date(), early.date())
    make_call(tx, u, late - timedelta(seconds=30), [(True, 1, [])])  # rep lands at 23:59:40 ET on the 13th
    make_call(tx, u, early, [(True, 1, [])])
    # a counted call with no valid rep and a void call do not qualify a day
    make_call(tx, u, et(2026, 10, 12, 21, 0), [(False, 0, ["too_fast"])])
    streak = lambda now: tx.execute("select ch_streak(%s, %s)", (u, now)).fetchone()[0]  # noqa: E731
    assert streak(et(2026, 10, 14, 12, 0)) == 2
    assert streak(et(2026, 10, 15, 12, 0)) == 2   # no call yet today -> streak through yesterday
    assert streak(et(2026, 10, 16, 0, 0, 30)) == 0
    assert streak(et(2026, 10, 13, 23, 59, 50)) == 1
    make_call(tx, u, et(2026, 10, 15, 8, 0), [(True, 1, [])], void=True)
    assert streak(et(2026, 10, 15, 12, 0)) == 2
    assert tx.execute("select ch_calls_today(%s, %s)", (u, et(2026, 10, 14, 23, 0))).fetchone()[0] == 1
    assert tx.execute("select ch_calls_today(%s, %s)", (u, et(2026, 10, 15, 23, 0))).fetchone()[0] == 1  # void counts


@pytest.mark.parametrize("points,level", [(-5, 1), (0, 1), (24, 1), (25, 2), (59, 2), (60, 3), (899, 8), (900, 9),
                                          (1199, 9), (1200, 10), (50000, 10)])
def test_avatar_level_thresholds(conn, points, level):
    assert conn.execute("select ch_avatar_level(%s)", (points,)).fetchone()[0] == level


def test_streak_days_pure(conn):
    q = "select ch_streak_days(%s::date[], %s::date)"
    d = lambda n: (datetime(2026, 10, 10) + timedelta(days=n)).date()  # noqa: E731
    assert conn.execute(q, ([d(1), d(2), d(3)], d(3))).fetchone()[0] == 3
    assert conn.execute(q, ([d(1), d(2), d(3)], d(4))).fetchone()[0] == 3
    assert conn.execute(q, ([d(1), d(3)], d(3))).fetchone()[0] == 1
    assert conn.execute(q, ([d(1), d(2)], d(4))).fetchone()[0] == 0
    assert conn.execute(q, ([], d(4))).fetchone()[0] == 0
    assert conn.execute(q, ([d(5)], d(4))).fetchone()[0] == 0  # future days never count


# ---------------------------------------------------------------- site pulse

def _delete_user(db, u):
    with connect(db) as c:
        c.execute("delete from calls where user_id=%s", (u,))
        c.execute("delete from clients where id=%s", (u,))


def test_site_pulse_bumps_on_reps_insert(db):
    with connect(db, autocommit=False) as c:
        u = make_user(c, "golf")
        make_call(c, u, et(2026, 10, 13, 12, 0))
        c.commit()
        before = c.execute("select bumped_at from site_pulse where id=1").fetchone()[0]
        c.commit()
        set_id = c.execute("select s.id from sets s join sessions x on x.id=s.session_id where x.client_id=%s",
                           (u,)).fetchone()[0]
        c.execute("insert into reps (set_id, rep_number, t, valid, points) values (%s, 1, 1.0, true, 1)", (set_id,))
        mid = c.execute("select bumped_at from site_pulse where id=1").fetchone()[0]
        assert mid == before  # deferred: bump happens at commit
        c.commit()
        after = c.execute("select bumped_at from site_pulse where id=1").fetchone()[0]
        c.commit()
        assert after > before
        assert c.execute("select count(*) from site_pulse").fetchone()[0] == 1
    _delete_user(db, u)


def test_site_pulse_bumps_for_service_role_writes(db):
    with connect(db, autocommit=False) as c:
        before = c.execute("select bumped_at from site_pulse").fetchone()[0]
        c.commit()
        c.execute("set role service_role")
        c.execute("update line_state set version = version + 1 where line_id='line-1'")
        c.commit()
        c.execute("reset role")
        assert c.execute("select bumped_at from site_pulse").fetchone()[0] > before
        c.commit()
