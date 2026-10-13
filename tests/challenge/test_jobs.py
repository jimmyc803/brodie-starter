"""Scheduled jobs against migrated Postgres + MockProvider with a fake clock (task 23)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from challenge.config import Config
from challenge.dispatcher.app import create_app
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.jobs import Jobs
from challenge.dispatcher.powerhour import fmt_range, pick_hour
from challenge.messaging.outbox import Outbox
from challenge.messaging.providers import MockProvider
from challenge.store import PgStore
from tests.challenge.test_dispatcher_api import commit_ev, mkuser, rep

ET = ZoneInfo("America/New_York")
D = datetime(2026, 10, 13, 12, 0, tzinfo=ET)  # a Tuesday inside the window
TEAM = "+15550009999"


def et(day, h, m=0, s=0):
    return datetime(2026, 10, day, h, m, s, tzinfo=ET)


@pytest.fixture
def env(db, conn, monkeypatch):
    monkeypatch.delenv("OUTBOUND_RATE_PER_MIN", raising=False)
    monkeypatch.setenv("POWER_HOUR_SECRET", "test-salt")
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log,"
                 " ch_job_state, heartbeats restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    for k, v in {"quiet_hours": [23, 9], "team_alert_handles": [], "competition_frozen": False,
                 "power_hour_window": [12, 22], "recap_hour": 10, "streak_risk_hour": 20,
                 "outbound_rate_per_min": 600, "window_end": "2026-10-18T23:59:59-04:00"}.items():
        conn.execute("update competition_config set value=%s where key=%s", (Jsonb(v), k))
    store, provider = PgStore(db), MockProvider()
    cfg = Config(store, ttl_s=0)
    clock = {"t": D}
    now = lambda: clock["t"]  # noqa: E731
    outbox = Outbox(store, cfg, provider, clock=now)
    outbox._at, outbox._tokens = D - timedelta(days=30), 600.0
    jobs = Jobs(store, cfg, outbox, now)
    return conn, store, cfg, provider, jobs, clock


def n_msgs(conn, template):
    return conn.execute("select count(*) from messages where template=%s", (template,)).fetchone()[0]


def set_ph(store, day, hour):
    from challenge.dispatcher.powerhour import start_at
    store.rpc("ch_power_hour_ensure", {"p_date_et": day, "p_starts_at": start_at(day, hour), "p_now": D})


def call(store, cid, handle, reps, at):
    r = store.rpc("ch_call_start", {"p_call_id": cid, "p_line_id": "line-1", "p_handle": handle,
                                    "p_mode": "chert_meta", "p_now": at})
    assert r["decision"] == "accept", r
    ev = commit_ev(cid)
    ev["payload"]["reps"] = reps
    assert store.rpc("ch_commit_reps", {"p_call_id": cid, "p_payload": ev["payload"],
                                        "p_now": at + timedelta(seconds=200)})["ok"]
    for k in (900, 1200):
        store.rpc("ch_tick", {"p_now": at + timedelta(seconds=k)})


# ---------------------------------------------------------------- power hour
def test_power_hour_rotation_seven_days(env):
    conn, store, cfg, _, jobs, clock = env
    hours = []
    for day in range(12, 19):
        clock["t"] = et(day, 8)
        r = jobs.run_due(clock["t"])
        assert "error" not in str(r["power_hours"]), r
        row = store.rpc("ch_power_hour_row", {"p_date_et": f"2026-10-{day}"})
        s = datetime.fromisoformat(row["starts_at"]).astimezone(ET)
        e = datetime.fromisoformat(row["ends_at"]).astimezone(ET)
        assert s.minute == 0 and 12 <= s.hour and e.hour <= 22 and e - s == timedelta(hours=1)
        hours.append(s.hour)
    assert all(a != b for a, b in zip(hours, hours[1:])), hours
    assert hours[0] >= 20  # day one starts at 20:00 ET: a power hour before it would be wasted
    assert conn.execute("select count(*) from power_hours").fetchone()[0] == 7  # Oct 19 is past the window: no row
    # rows are stable: running again changes nothing
    before = conn.execute("select date_et, starts_at from power_hours order by 1").fetchall()
    for day in range(12, 19):
        jobs.power._ensured.clear()
        jobs.run_due(et(day, 9))
    assert conn.execute("select date_et, starts_at from power_hours order by 1").fetchall() == before


def test_pick_hour_seeded_and_salted():
    from datetime import date
    d = date(2026, 10, 14)
    assert pick_hour(d, 12, 22, salt="a") == pick_hour(d, 12, 22, salt="a")
    assert {pick_hour(d, 12, 22, salt=s) for s in "abcdefghij"} != {pick_hour(d, 12, 22, salt="a")}
    assert pick_hour(d, 12, 22, exclude=pick_hour(d, 12, 22, salt="a"), salt="a") != pick_hour(d, 12, 22, salt="a")
    assert fmt_range(et(13, 15), et(13, 16)) == "3:00–4:00 PM"
    assert fmt_range(et(13, 11), et(13, 12)) == "11:00 AM–12:00 PM"


# ---------------------------------------------------------------- announcements
def test_announcements_exactly_once(env):
    conn, store, cfg, provider, jobs, clock = env
    mkuser(conn), mkuser(conn)
    set_ph(store, D.date(), 15)
    for t in (et(13, 14, 44, 59), et(13, 14, 45), et(13, 14, 46), et(13, 14, 59), et(13, 15), et(13, 15, 1),
              et(13, 15, 2), et(13, 15, 30)):
        jobs.run_due(t)
    assert n_msgs(conn, "ph_warn") == 2 and n_msgs(conn, "ph_start") == 2
    bodies = [m["body"] for m in provider.sent]
    assert sum("starts in 15 minutes" in b for b in bodies) == 2
    assert sum("LIVE" in b for b in bodies) == 2
    row = store.rpc("ch_power_hour_row", {"p_date_et": D.date()})
    assert row["warned_at"] and row["started_announced_at"]
    # a restarted dispatcher (fresh Jobs) does not repeat them
    jobs2 = Jobs(store, cfg, jobs.outbox, jobs.clock)
    for t in (et(13, 15, 3), et(13, 15, 4)):
        jobs2.run_due(t)
    assert n_msgs(conn, "ph_warn") == 2 and n_msgs(conn, "ph_start") == 2


def test_quiet_hours_skip_not_defer(env):
    conn, store, cfg, provider, jobs, clock = env
    mkuser(conn)
    conn.execute("update competition_config set value=%s where key='quiet_hours'", (Jsonb([14, 16]),))
    set_ph(store, D.date(), 15)
    for t in (et(13, 14, 45), et(13, 14, 50), et(13, 15), et(13, 15, 5)):
        jobs.run_due(t)
    assert n_msgs(conn, "ph_warn") == 0 and n_msgs(conn, "ph_start") == 0
    jobs.run_due(et(13, 16, 30))  # out of quiet hours: stale announcements are not sent late
    assert n_msgs(conn, "ph_warn") == 0 and n_msgs(conn, "ph_start") == 0
    # recap hour inside quiet hours is skipped, not deferred
    conn.execute("update competition_config set value=%s where key='quiet_hours'", (Jsonb([9, 11]),))
    jobs.run_due(et(14, 10))
    jobs.run_due(et(14, 11, 30))
    assert n_msgs(conn, "daily_recap") == 0


# ---------------------------------------------------------------- recap / streak
def test_daily_recap_content_and_dedupe(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    uid2, h2 = mkuser(conn)
    call(store, "rc1", h, [rep(1, D.isoformat()), rep(2, D.isoformat()), rep(3, D.isoformat())], D)
    set_ph(store, et(14, 0).date(), 17)
    for t in (et(14, 9, 59), et(14, 10), et(14, 10, 2), et(14, 10, 4), et(14, 11)):
        jobs.run_due(t)
    assert n_msgs(conn, "daily_recap") == 2
    ctx = conn.execute("select ctx from messages where template='daily_recap' and user_id=%s", (uid,)).fetchone()[0]
    assert (ctx["yesterday_points"], ctx["points"], ctx["rank"], ctx["streak"]) == (3, 3, 1, 1)
    assert ctx["power_hour"] == "5:00–6:00 PM"
    ctx2 = conn.execute("select ctx from messages where template='daily_recap' and user_id=%s", (uid2,)).fetchone()[0]
    assert (ctx2["yesterday_points"], ctx2["points"], ctx2["rank"]) == (0, 0, 2)
    body = next(m["body"] for m in provider.sent if m["handle"] == h and "Yesterday" in m["body"])
    assert "+3 points" in body and "rank #1" in body and "5:00–6:00 PM ET" in body
    assert conn.execute("select dedupe_key from messages where template='daily_recap' and user_id=%s", (uid,)).fetchone()[0] \
        == f"recap:2026-10-14:{uid}"
    assert store.rpc("ch_power_hour_row", {"p_date_et": "2026-10-14"})["announced_at"]
    conn.execute("update messages set status='sent' where template='daily_recap'")
    # opted-out users get nothing
    uid3, _ = mkuser(conn)
    store.rpc("ch_set_opt", {"p_user_id": uid3, "p_opted_out": True, "p_now": et(15, 1)})
    jobs.run_due(et(15, 10))
    assert conn.execute("select count(*) from messages where template='daily_recap' and user_id=%s", (uid3,)).fetchone()[0] == 0


def test_streak_risk(env):
    conn, store, cfg, provider, jobs, clock = env
    a, ha = mkuser(conn)
    b, hb = mkuser(conn)
    c, hc = mkuser(conn)
    r = lambda day: [rep(1, et(day, 12).isoformat())]  # noqa: E731
    call(store, "s-a1", ha, r(13), et(13, 12)); call(store, "s-a2", ha, r(14), et(14, 12))
    call(store, "s-b1", hb, r(13), et(13, 12, 30)); call(store, "s-b2", hb, r(14), et(14, 12, 30))
    call(store, "s-c1", hc, r(14), et(14, 13))
    call(store, "s-b3", hb, r(15), et(15, 12, 30))  # b already has a qualifying call today
    for t in (et(15, 19, 59), et(15, 20), et(15, 20, 5)):
        jobs.run_due(t)
    rows = conn.execute("select user_id::text from messages where template='streak_risk'").fetchall()
    assert [x[0] for x in rows] == [a]  # a: streak 2, none today; b: done today; c: streak 1


# ---------------------------------------------------------------- freeze + final
def test_freeze_and_final_results_once(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    uid2, h2 = mkuser(conn)
    call(store, "f1", h, [rep(1, D.isoformat()), rep(2, D.isoformat())], D)
    jobs.run_due(et(18, 23, 59, 58))
    assert cfg.get("competition_frozen") is False and n_msgs(conn, "final_results") == 0
    for t in (et(18, 23, 59, 59), et(19, 0, 0, 2), et(19, 0, 0, 4)):
        jobs.run_due(t)
    assert cfg.get("competition_frozen") is True
    assert conn.execute("select actor from audit_log where action ilike '%config%' and after::text like '%true%'"
                        " order by id desc limit 1").fetchone()[0] == "system"
    assert n_msgs(conn, "final_results") == 2
    # window_end is in quiet hours: delivery is deferred to 09:00, nothing sent overnight
    assert not [m for m in provider.sent if "wrap" in m["body"]]
    jobs.run_due(et(19, 9, 0, 1))
    finals = [m for m in provider.sent if "wrap" in m["body"]]
    assert len(finals) == 2 and "2 points, rank #1" in next(m["body"] for m in finals if m["handle"] == h)
    jobs.run_due(et(19, 9, 5)); jobs.run_due(et(19, 12))
    assert len([m for m in provider.sent if "wrap" in m["body"]]) == 2
    # restart: still once
    Jobs(store, cfg, jobs.outbox, jobs.clock).run_due(et(19, 13))
    assert n_msgs(conn, "final_results") == 2


def test_ending_soon_sunday_once(env):
    conn, store, cfg, provider, jobs, clock = env
    mkuser(conn)
    for t in (et(18, 19, 59), et(18, 20), et(18, 20, 1), et(18, 20, 30)):
        jobs.run_due(t)
    assert n_msgs(conn, "ending_soon") == 1
    assert any("ends tonight at 11:59 PM ET" in m["body"] for m in provider.sent)
    jobs.run_due(et(17, 20)); assert n_msgs(conn, "ending_soon") == 1


# ---------------------------------------------------------------- heartbeat / tick
def test_heartbeat_and_tick(env):
    conn, store, cfg, provider, jobs, clock = env
    r = jobs.run_due(D)
    assert set(r["tick"]) >= {"no_shows", "claims", "timeouts", "idled"}
    hb = conn.execute("select at, detail from heartbeats where component='dispatcher'").fetchone()
    assert hb[0] == D and hb[1] == {"errors": {}}
    jobs.run_due(D + timedelta(seconds=2))  # throttled: heartbeat not rewritten
    assert conn.execute("select at from heartbeats where component='dispatcher'").fetchone()[0] == D
    jobs.run_due(D + timedelta(seconds=11))
    assert conn.execute("select at from heartbeats where component='dispatcher'").fetchone()[0] == D + timedelta(seconds=11)


def test_tick_pops_queue_and_youre_up_sent(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    assert store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": D - timedelta(seconds=1)})["ok"]
    jobs.run_due(D)
    assert conn.execute("select state from line_state where line_id='line-1'").fetchone()[0] == "claimed"
    assert any("You're up" in m["body"] for m in provider.sent)


def test_step_errors_are_isolated(env):
    conn, store, cfg, provider, jobs, clock = env
    jobs.alerts.check = lambda now: 1 / 0
    r = jobs.run_due(D)
    assert r["alerts"] == {"error": "ZeroDivisionError"} and r["heartbeat"] is None
    assert jobs.errors == {"alerts": "ZeroDivisionError"}
    assert conn.execute("select detail from heartbeats where component='dispatcher'").fetchone()[0] == {
        "errors": {"alerts": "ZeroDivisionError"}}


# ---------------------------------------------------------------- alerts
def beat(conn, at, component="worker"):
    conn.execute("insert into heartbeats (component, at) values (%s,%s) on conflict (component) do update set at=excluded.at",
                 (component, at))


def test_alert_dedupe_and_bypass_quiet_hours(env):
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("update competition_config set value=%s where key='team_alert_handles'", (Jsonb([TEAM]),))
    t = et(13, 2)  # quiet hours
    beat(conn, t - timedelta(minutes=10))
    assert jobs.alerts.check(t) == ["worker_heartbeat"]
    assert jobs.alerts.check(t + timedelta(minutes=10)) == []
    assert jobs.alerts.check(t + timedelta(minutes=29)) == []
    assert jobs.alerts.check(t + timedelta(minutes=31)) == ["worker_heartbeat"]
    assert n_msgs(conn, "alert") == 2
    jobs.outbox.run_once(t + timedelta(minutes=32))
    assert provider.sent[0]["handle"] == TEAM and provider.sent[0]["body"].startswith("BRODIE ALERT [worker_heartbeat]")
    # fresh heartbeat: no condition
    beat(conn, t + timedelta(minutes=60))
    assert jobs.alerts.check(t + timedelta(minutes=61)) == []


def test_alert_line_stuck_and_failure_spike(env):
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("update competition_config set value=%s where key='team_alert_handles'", (Jsonb([TEAM]),))
    t = D
    beat(conn, t)
    uid, h = mkuser(conn)
    conn.execute("insert into queue (user_id, entered_at, status) values (%s,%s,'waiting')", (uid, t - timedelta(hours=1)))
    conn.execute("update line_state set state='offline', offline_until=%s, updated_at=%s",
                 (t + timedelta(days=1), t - timedelta(minutes=5)))
    assert jobs.alerts.conditions(t) == {}  # recent transition
    conn.execute("update line_state set updated_at=%s", (t - timedelta(minutes=13),))
    assert "line_stuck" in jobs.alerts.conditions(t)
    conn.execute("delete from queue")
    assert jobs.alerts.conditions(t) == {}  # nothing waiting
    for i in range(7):
        conn.execute("insert into messages (direction, handle, template, dedupe_key, status, created_at)"
                     " values ('out',%s,'help',%s,%s,%s)", (h, f"x{i}", "failed" if i < 2 else "sent", t - timedelta(minutes=3)))
    assert "outbound_failures" in jobs.alerts.conditions(t)  # 2/7 = 29%
    conn.execute("update messages set status='sent' where dedupe_key='x1'")
    assert "outbound_failures" not in jobs.alerts.conditions(t)  # 1/7 = 14%
    assert jobs.alerts.conditions(et(12, 19)) == {}  # before the window opens


# ---------------------------------------------------------------- post-call sweep
def test_postcall_sweep_processes_pending(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    call(store, "pc1", h, [rep(1, D.isoformat())], D)
    now = D + timedelta(seconds=300)
    r = jobs.postcall_sweep(now)
    assert r == {"done": 1, "failed": 0, "gave_up": 0}
    assert n_msgs(conn, "post_call") == 1
    assert jobs.postcall_sweep(now + timedelta(seconds=30)) == {"done": 0, "failed": 0, "gave_up": 0}
    assert conn.execute("select count(*) from ch_job_state where key like 'postcall:%%'").fetchone()[0] == 0


def test_postcall_sweep_gives_up_after_10_attempts(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    call(store, "pc2", h, [rep(1, D.isoformat())], D)
    conn.execute("delete from client_handles where client_id=%s", (uid,))  # handle_required forever
    t, results = D + timedelta(seconds=300), []
    for i in range(14):
        results.append(jobs.postcall_sweep(t + timedelta(seconds=30 * i)))
    assert [r["failed"] for r in results[:10]] == [1] * 10
    assert results[10]["gave_up"] == 1 and all(r == {"done": 0, "failed": 0, "gave_up": 0} for r in results[11:])
    assert conn.execute("select count(*) from heartbeats where component='warn:postcall:pc2'").fetchone()[0] == 1
    assert store.rpc("ch_postcall_pending", {"p_now": t + timedelta(days=1), "p_limit": 10}) == []
    assert conn.execute("select postcall_done_at from calls where id='pc2'").fetchone()[0] is None


def test_postcall_sweep_gives_up_after_one_hour(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    call(store, "pc3", h, [rep(1, D.isoformat())], D)
    conn.execute("delete from client_handles where client_id=%s", (uid,))
    t = D + timedelta(seconds=300)
    assert jobs.postcall_sweep(t)["failed"] == 1
    assert jobs.postcall_sweep(t + timedelta(minutes=61))["gave_up"] == 1


# ---------------------------------------------------------------- queue updates
def queue_users(conn, store, n, t):
    users = []
    for _ in range(n):
        uid, h = mkuser(conn)
        assert store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": t})["ok"]
        users.append((uid, h))
        t += timedelta(seconds=1)
    return users


def test_queue_updates(env):
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("update line_state set state='offline', offline_until=%s", (D + timedelta(days=1),))
    conn.execute("update competition_config set value='0' where key='line_offline_gap_s'")  # ~3.3 min per place
    users = queue_users(conn, store, 6, D)
    assert jobs.queue_updates(D) == 0  # baselines only
    last = users[5][0]
    for uid, _ in users[:2]:
        store.rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": "left", "p_now": D})
    assert jobs.queue_updates(D + timedelta(seconds=30)) == 0  # moved up by 2 and ETA < 10 min
    store.rpc("ch_queue_leave", {"p_user_id": users[2][0], "p_reason": "left", "p_now": D})
    assert jobs.queue_updates(D + timedelta(seconds=60)) == 2  # 6 -> 3 and 5 -> 2: improved by 3 each
    assert conn.execute("select ctx->>'position' from messages where template='queue_update' and user_id=%s", (last,)).fetchone()[0] == "3"
    store.rpc("ch_queue_leave", {"p_user_id": users[3][0], "p_reason": "left", "p_now": D})
    assert jobs.queue_updates(D + timedelta(minutes=5)) == 0  # throttled to 1 per 10 minutes
    assert jobs.queue_updates(D + timedelta(minutes=11)) == 0  # only 1 spot gained since the last text
    assert n_msgs(conn, "queue_update") == 2


def test_queue_updates_never_in_quiet_hours_and_eta_trigger(env):
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("update line_state set state='offline', offline_until=%s", (et(13, 1) + timedelta(days=1),))
    users = queue_users(conn, store, 5, et(13, 1))
    jobs.queue_updates(et(13, 1))
    for uid, _ in users[:3]:
        store.rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": "left", "p_now": et(13, 1)})
    assert jobs.queue_updates(et(13, 1, 5)) == 0 and n_msgs(conn, "queue_update") == 0  # 01:05 is quiet
    # ETA trigger: slow cycles make a 2-place gain worth >=10 min
    conn.execute("update line_state set offline_until=%s", (et(13, 12) + timedelta(days=1),))
    users2 = queue_users(conn, store, 4, et(13, 12))
    for uid, _ in users[3:]:
        store.rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": "left", "p_now": et(13, 12)})
    store.rpc("ch_config_set", {"p_key": "line_offline_gap_s", "p_value": __import__("challenge.store", fromlist=["Json"]).Json(900),
                                "p_actor": "t", "p_reason": "eta test"})
    jobs.queue_updates(et(13, 12))
    store.rpc("ch_queue_leave", {"p_user_id": users2[0][0], "p_reason": "left", "p_now": et(13, 12)})
    store.rpc("ch_queue_leave", {"p_user_id": users2[1][0], "p_reason": "left", "p_now": et(13, 12)})
    assert jobs.queue_updates(et(13, 12, 1)) == 1  # #2 gained 2 places = 36 min of ETA; #1 is the claim, not a queue update


# ---------------------------------------------------------------- rank_drop quiet hours (outbox)
def test_rank_drop_in_quiet_hours_is_dropped_not_deferred(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    ctx = {"old_rank": 4, "rank": 7, "next_rank": 6, "points_gap": 12}
    q = et(13, 2)
    store.rpc("ch_outbox_enqueue", {"p_handle": None, "p_user_id": uid, "p_template": "rank_drop", "p_body": None,
                                    "p_media_url": None, "p_dedupe_key": "rd1", "p_not_before": None, "p_now": q, "p_ctx": ctx})
    store.rpc("ch_outbox_enqueue", {"p_handle": None, "p_user_id": uid, "p_template": "rank_drop", "p_body": None,
                                    "p_media_url": None, "p_dedupe_key": "rd2", "p_not_before": None, "p_now": et(13, 12), "p_ctx": ctx})
    jobs.outbox.clock = lambda: q
    jobs.outbox.run_once(q)
    assert conn.execute("select status, last_error from messages where dedupe_key='rd1'").fetchone() == ("suppressed", "quiet_hours")
    assert provider.sent == []
    jobs.outbox.clock = lambda: et(13, 12)
    jobs.outbox.run_once(et(13, 12))
    assert conn.execute("select status from messages where dedupe_key='rd2'").fetchone()[0] == "sent"


# ---------------------------------------------------------------- app wiring
class _Probe:
    def __init__(self):
        self.calls = 0
        self.clock = lambda: D

    def run_due(self, now):
        self.calls += 1


def test_app_starts_jobs_loop_unless_disabled(db, monkeypatch):
    import time
    store = PgStore(db)
    monkeypatch.setenv("JOBS_ENABLED", "1")
    probe = _Probe()
    with TestClient(create_app(store, None, clock=lambda: D, flags=Flags(), token="t", jobs=probe)):
        for _ in range(50):
            if probe.calls:
                break
            time.sleep(0.05)
    assert probe.calls >= 1
    monkeypatch.setenv("JOBS_ENABLED", "0")
    off = _Probe()
    with TestClient(create_app(store, None, clock=lambda: D, flags=Flags(), token="t", jobs=off)):
        time.sleep(0.2)
    assert off.calls == 0


# ---------------------------------------------------------------- fix round
def test_call_spanning_window_end_commits_after_freeze(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    start = et(18, 23, 58)
    assert store.rpc("ch_call_start", {"p_call_id": "span", "p_line_id": "line-1", "p_handle": h,
                                       "p_mode": "chert_meta", "p_now": start})["decision"] == "accept"
    jobs.run_due(et(19, 0, 0, 1))  # freeze happens while the call is still running
    assert cfg.get("competition_frozen") is True
    assert datetime.fromisoformat(cfg.get("frozen_at")) == et(18, 23, 59, 59)
    reps = [rep(1, et(18, 23, 58, 30).isoformat()), rep(2, et(18, 23, 59, 58).isoformat()),
            rep(3, et(19, 0, 0, 1).isoformat()), rep(4, et(19, 0, 1).isoformat())]
    ev = commit_ev("span")
    ev["payload"].update(reps=reps, started_at=start.isoformat(), ended_at=et(19, 0, 1, 10).isoformat())
    r = store.rpc("ch_commit_reps", {"p_call_id": "span", "p_payload": ev["payload"], "p_now": et(19, 0, 1, 20)})
    assert r["ok"] and r["valid_reps"] == 2 and r["points"] == 2
    rows = conn.execute("select valid, reject_reasons from reps order by rep_number").fetchall()
    assert [x[0] for x in rows] == [True, True, False, False]
    assert all("after_freeze" in x[1] for x in rows[2:])


def test_admin_freeze_stamps_cutoff(env):
    conn, store, cfg, *_ = env
    uid, h = mkuser(conn)
    start = et(14, 12)
    store.rpc("ch_call_start", {"p_call_id": "adm", "p_line_id": "line-1", "p_handle": h, "p_mode": "chert_meta", "p_now": start})
    store.rpc("ch_config_set", {"p_key": "competition_frozen", "p_value": __import__("challenge.store", fromlist=["Json"]).Json(True),
                                "p_actor": "admin@x", "p_reason": "freeze"})
    cut = datetime.fromisoformat(cfg.get("frozen_at"))
    assert abs((cut - datetime.now(cut.tzinfo)).total_seconds()) < 60  # stamped with now()
    cut = start + timedelta(seconds=60)
    store.rpc("ch_set_frozen_at", {"p_at": cut, "p_actor": "admin@x", "p_reason": "test cutoff"})
    ev = commit_ev("adm")
    ev["payload"]["reps"] = [rep(1, (cut - timedelta(seconds=5)).isoformat()), rep(2, (cut + timedelta(seconds=5)).isoformat())]
    r = store.rpc("ch_commit_reps", {"p_call_id": "adm", "p_payload": ev["payload"], "p_now": start + timedelta(seconds=200)})
    assert r["valid_reps"] == 1


def test_power_hour_secret_required_in_competition_mode(db, monkeypatch):
    store = PgStore(db)
    monkeypatch.setenv("CHALLENGE_MODE", "competition")
    for bad in (None, "", "short"):
        if bad is None:
            monkeypatch.delenv("POWER_HOUR_SECRET", raising=False)
        else:
            monkeypatch.setenv("POWER_HOUR_SECRET", bad)
        with pytest.raises(RuntimeError, match="POWER_HOUR_SECRET"):
            create_app(store, None, clock=lambda: D, flags=Flags(), token="t")
    monkeypatch.setenv("POWER_HOUR_SECRET", "x" * 16)
    create_app(store, None, clock=lambda: D, flags=Flags(), token="t")
    monkeypatch.setenv("CHALLENGE_MODE", "demo")
    monkeypatch.delenv("POWER_HOUR_SECRET")
    create_app(store, None, clock=lambda: D, flags=Flags(), token="t")


def test_expired_time_bound_texts_are_suppressed(env):
    conn, store, cfg, provider, jobs, clock = env
    uid, h = mkuser(conn)
    t = et(13, 14, 45)
    exp = lambda dt: dt.isoformat()  # noqa: E731
    for key, tpl, expires in (("e1", "ph_warn", et(13, 15)), ("e2", "ph_start", et(13, 16)),
                              ("e3", "ending_soon", et(13, 20)), ("e4", "queue_update", et(13, 14, 55))):
        ctx = {"power_hour": "3:00–4:00 PM", "ends_at": "tonight", "position": 3, "eta": "~5–10 min",
               "expires_at": exp(expires), "_proactive": True}
        store.rpc("ch_outbox_enqueue", {"p_handle": None, "p_user_id": uid, "p_template": tpl, "p_body": None,
                                        "p_media_url": None, "p_dedupe_key": key, "p_not_before": None, "p_now": t, "p_ctx": ctx})
    jobs.outbox.clock = lambda: et(13, 15, 30)
    jobs.outbox.run_once(et(13, 15, 30))
    st = dict(conn.execute("select dedupe_key, status from messages order by dedupe_key").fetchall())
    assert st == {"e1": "suppressed", "e2": "sent", "e3": "sent", "e4": "suppressed"}
    assert conn.execute("select last_error from messages where dedupe_key='e1'").fetchone()[0] == "expired"


def test_job_claim_and_queue_update_bucket_are_atomic(env):
    conn, store, cfg, *_ = env
    assert store.rpc("ch_job_claim", {"p_key": "k", "p_now": D, "p_gap_s": 1800}) is True
    assert store.rpc("ch_job_claim", {"p_key": "k", "p_now": D + timedelta(minutes=29), "p_gap_s": 1800}) is False
    assert store.rpc("ch_job_claim", {"p_key": "k", "p_now": D + timedelta(minutes=31), "p_gap_s": 1800}) is True
    uid, h = mkuser(conn)
    args = {"p_user_id": uid, "p_state_key": f"qpos:{uid}", "p_state": {"position": 3}, "p_ctx": {"position": 3, "eta": "x"},
            "p_bucket_s": 600, "p_now": D}
    assert store.rpc("ch_queue_update_notify", args)["duplicate"] is False
    other = {**args, "p_state": {"position": 2}, "p_now": D + timedelta(seconds=30)}  # a second dispatcher, same bucket
    assert store.rpc("ch_queue_update_notify", other)["duplicate"] is True
    assert store.rpc("ch_job_get", {"p_key": f"qpos:{uid}"}) == {"position": 3}  # loser did not touch state
    assert n_msgs(conn, "queue_update") == 1
