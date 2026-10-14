"""Jobs loop / PgStore / host monitor parts of the call-path reliability fixes (audit P1-1, P1-4)."""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib.util
import json
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from psycopg.types.json import Jsonb

from challenge.dispatcher.jobs import run_loop
from challenge.store import PgStore, StoreError
from tests.challenge.test_dispatcher_api import mkuser
from tests.challenge.test_jobs import D, TEAM, env  # noqa: F401  (env is a fixture)

ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------- P1-4: outbox on its own task

class _SlowOutboxJobs:
    """run_due records calls; the outbox pass blocks like a hung provider send."""

    def __init__(self):
        self.clock = lambda: D
        self.due: list[bool] = []
        self.outbox_started = threading.Event()
        self.release = threading.Event()

    def run_due(self, now, include_outbox=True):
        self.due.append(include_outbox)

    def run_outbox(self, now):
        self.outbox_started.set()
        self.release.wait(5)


def test_run_loop_ticks_while_the_outbox_send_is_blocked():
    jobs = _SlowOutboxJobs()

    async def scenario():
        task = asyncio.create_task(run_loop(jobs, interval_s=0.02, outbox_interval_s=0.02))
        try:
            for _ in range(200):
                if jobs.outbox_started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert jobs.outbox_started.is_set()
            before = len(jobs.due)
            await asyncio.sleep(0.3)  # the outbox is stuck in a send for this whole time
            return len(jobs.due) - before
        finally:
            jobs.release.set()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    ticks = asyncio.run(scenario())
    assert ticks >= 5, ticks
    assert jobs.due and not any(jobs.due), "run_loop must leave the outbox to its own task"


def test_run_due_still_runs_the_outbox_by_default(env):  # noqa: F811
    conn, store, cfg, provider, jobs, clock = env
    uid, _ = mkuser(conn)
    assert store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": D - timedelta(seconds=1)})["ok"]
    r = jobs.run_due(D, include_outbox=False)
    assert "outbox" not in r and provider.sent == []
    jobs.run_outbox(D)
    assert any("You're up" in m["body"] for m in provider.sent)
    r = jobs.run_due(D + timedelta(seconds=2))
    assert "outbox" in r


def test_run_outbox_records_errors(env):  # noqa: F811
    conn, store, cfg, provider, jobs, clock = env
    jobs.outbox.run_once = lambda now: 1 / 0
    with pytest.raises(ZeroDivisionError):
        jobs.run_outbox(D)
    assert jobs.errors == {"outbox": "ZeroDivisionError"}
    jobs.outbox.run_once = lambda now: 0
    jobs.run_outbox(D)
    assert jobs.errors == {}


# ---------------------------------------------------------------- P1-1: held queue alerts once

def test_stale_line_heartbeat_holds_queue_and_alerts_once(env):  # noqa: F811
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("update competition_config set value=%s where key='team_alert_handles'", (Jsonb([TEAM]),))
    conn.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (D - timedelta(minutes=5),))
    uid, _ = mkuser(conn)
    assert store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": D - timedelta(seconds=1)})["ok"]
    for k in range(5):
        r = jobs.run_due(D + timedelta(seconds=2 * k))
        assert r["tick"]["held"] == ["line-1"] and r["tick"]["claims"] == []
    alerts = conn.execute("select ctx from messages where template='alert' and ctx->>'condition' = 'line_held'").fetchall()
    assert len(alerts) == 1  # once per hold, not every tick (other conditions alert on their own)
    assert "line-1" in alerts[0][0]["detail"]
    assert conn.execute("select count(*) from messages where template='youre_up'").fetchone()[0] == 0
    # the worker beats again: the queue moves
    conn.execute("update heartbeats set at=%s where component='worker:line-1'", (D + timedelta(seconds=20),))
    r = jobs.run_due(D + timedelta(seconds=21))
    assert [x["user_id"] for x in r["tick"]["claims"]] == [str(uid)] and "held" not in r["tick"]
    assert jobs._held == set()


def test_held_alert_failure_is_retried(env):  # noqa: F811
    conn, store, cfg, provider, jobs, clock = env
    conn.execute("insert into heartbeats (component, at) values ('worker:line-1', %s)", (D - timedelta(minutes=5),))
    uid, _ = mkuser(conn)
    store.rpc("ch_queue_join", {"p_user_id": uid, "p_now": D - timedelta(seconds=1)})
    calls = []

    def boom(cond, detail, now):
        calls.append(cond)
        raise RuntimeError("outbox down")

    jobs.alerts.fire = boom
    assert jobs.run_due(D)["tick"] == {"error": "RuntimeError"}
    assert jobs.run_due(D + timedelta(seconds=2))["tick"] == {"error": "RuntimeError"}
    assert calls.count("line_held") == 2  # not marked as alerted while the alert could not be sent


# ---------------------------------------------------------------- P1-4: PgStore timeouts

def test_pgstore_statement_timeout(db, conn):
    conn.execute("create or replace function t_sleep(p_s float8) returns int language sql as"
                 " $$ select 1 from pg_sleep(p_s) $$")
    fast = PgStore(db, statement_timeout_ms=200)
    t = time.monotonic()
    with pytest.raises(StoreError, match="statement timeout"):
        fast.rpc("t_sleep", {"p_s": 3})
    assert time.monotonic() - t < 2.5
    assert fast.rpc("t_sleep", {"p_s": 0}) == 1
    # set_config(..., true) is transaction-local: nothing leaks into the session
    assert PgStore(db, statement_timeout_ms=0).rpc("t_sleep", {"p_s": 0.3}) == 1


def test_pgstore_timeout_defaults_and_env(monkeypatch):
    s = PgStore("dbname=x")
    assert (s.connect_timeout_s, s.statement_timeout_ms) == (5, 10_000)
    monkeypatch.setenv("PG_CONNECT_TIMEOUT_S", "3")
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "2500")
    s = PgStore("dbname=x")
    assert (s.connect_timeout_s, s.statement_timeout_ms) == (3, 2500)
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "soon")
    with pytest.raises(StoreError):
        PgStore("dbname=x")
    with pytest.raises(StoreError):
        PgStore("dbname=x", connect_timeout_s=0, statement_timeout_ms=1)


def test_pgstore_connect_timeout_is_passed(monkeypatch):
    import psycopg

    seen = {}

    def fake_connect(dsn, **kw):
        seen.update(kw)
        raise psycopg.OperationalError("connection timeout expired")

    monkeypatch.setattr(psycopg, "connect", fake_connect)
    with pytest.raises(StoreError, match="timeout"):
        PgStore("host=10.255.255.1 dbname=x", connect_timeout_s=2).rpc("ch_tick", {"p_now": D})
    assert seen == {"autocommit": True, "connect_timeout": 2}


# ---------------------------------------------------------------- P1-1: monitor chert check

@pytest.fixture
def monitor():
    spec = importlib.util.spec_from_file_location("brodie_monitor", ROOT / "infra" / "monitor.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "infra"))
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(str(ROOT / "infra"))
    return mod


NOW = dt.datetime(2026, 10, 13, 9, 0, tzinfo=dt.timezone.utc)


def ago(minutes):
    return NOW - dt.timedelta(minutes=minutes)


def test_chert_ok_when_connected_or_waiting_room(monitor):
    entries = [(ago(25), "Connected to Chert. Call readiness is reported separately."),
               (ago(4), '"brodie" joined a waiting room. Media readiness is not verified.')]
    assert monitor.chert_status(True, entries, NOW, 30, 10) == ("ok", "connected")
    # the old doctor complaints (line busy because connected, livekit vars) are irrelevant now
    assert monitor.chert_status(True, entries + [(ago(1), "line_free ✗ Session is connected")], NOW, 30, 10)[0] == "ok"


def test_chert_fail_when_unit_inactive(monitor):
    state, detail = monitor.chert_status(False, [], NOW, 30, 10)
    assert state == "fail" and "not active" in detail


def test_chert_lost_is_pending_then_fails_without_recovery(monitor):
    base = [(ago(20), '"brodie" joined a waiting room.')]
    lost = base + [(ago(8), "Connection to Chert lost: reconnecting…"), (ago(3), "Connection to Chert lost: reconnecting…")]
    assert monitor.chert_status(True, lost, NOW, 30, 10)[0] == "pending"  # first loss 8 min ago < 10 min grace
    lost = base + [(ago(12), "Connection to Chert lost: reconnecting…"), (ago(2), "Connection to Chert lost: reconnecting…")]
    state, detail = monitor.chert_status(True, lost, NOW, 30, 10)
    assert state == "fail" and "12 min" in detail
    # a waiting-room join after the loss is a recovery
    assert monitor.chert_status(True, lost + [(ago(1), '"brodie" joined a waiting room.')], NOW, 30, 10)[0] == "ok"


def test_chert_session_expired_and_silence_fail(monitor):
    state, detail = monitor.chert_status(True, [(ago(20), "Connected to Chert."),
                                                (ago(5), "Stopped, but your Chert session expired")], NOW, 30, 10)
    assert state == "fail" and "expired" in detail
    state, detail = monitor.chert_status(True, [(ago(5), "some unrelated line")], NOW, 30, 10)
    assert state == "fail" and "no connected or waiting-room state" in detail
    # restarted after the expiry with a fresh login: healthy again
    assert monitor.chert_status(True, [(ago(5), "Stopped, but your Chert session expired"),
                                       (ago(1), "Connected to Chert.")], NOW, 30, 10)[0] == "ok"


def test_journal_entries_parses_json_lines(monitor, monkeypatch):
    seen = []
    us = int(ago(3).timestamp() * 1e6)
    lines = [json.dumps({"MESSAGE": '"brodie" joined a waiting room.', "__REALTIME_TIMESTAMP": str(us)}),
             json.dumps({"MESSAGE": list("Call ended: room removed.".encode()), "__REALTIME_TIMESTAMP": str(us + 1)}),
             json.dumps({"__REALTIME_TIMESTAMP": str(us + 2)}), ""]
    monkeypatch.setattr(monitor, "command", lambda *a: seen.append(a) or "\n".join(lines))
    out = monitor.journal_entries("chert-agent", 30)
    assert [m for _, m in out] == ['"brodie" joined a waiting room.', "Call ended: room removed."]
    assert out[0][0] == dt.datetime.fromtimestamp(us / 1e6, dt.timezone.utc)
    assert seen[0][:5] == ("journalctl", "-u", "chert-agent", "--since", "-30min")


def _run_main(monitor, monkeypatch, *, active, entries, journal_error=None, kinds=None):
    alerts, pings = [], []
    # Each check names itself (D-40); `kinds` collects those names when a caller cares.
    monkeypatch.setattr(monitor, "alert", lambda message, kind="infra": (alerts.append(message),
                                                                        kinds.append(kind) if kinds is not None else None))
    monkeypatch.setattr(monitor, "ping", lambda name, body: pings.append(name))
    monkeypatch.setattr(monitor, "unit_active", lambda unit: active.get(unit, True))

    def journal(unit, window):
        if journal_error:
            raise journal_error
        return entries

    monkeypatch.setattr(monitor, "journal_entries", journal)

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true, "db": true}'

    monkeypatch.setattr(monitor.urllib.request, "urlopen", lambda *a, **k: _Resp())
    monkeypatch.setattr(monitor.json, "load", lambda r: {"ok": True, "db": True})

    class _Stop(Exception):
        pass

    def stop(*a, **k):  # the crash-loop and DB checks that follow are out of scope here
        raise _Stop

    monkeypatch.setattr(monitor, "command", stop)
    with pytest.raises(_Stop):
        monitor.main()
    return alerts, pings


def test_monitor_main_pings_when_chert_connected(monitor, monkeypatch):
    alerts, pings = _run_main(monitor, monkeypatch, active={},
                              entries=[(dt.datetime.now(dt.timezone.utc), '"brodie" joined a waiting room.')])
    assert alerts == [] and pings.count("HC_WORKER_URL") == 1


def test_monitor_main_alerts_on_real_chert_failures(monitor, monkeypatch):
    kinds = []
    alerts, pings = _run_main(monitor, monkeypatch, active={"chert-agent": False}, entries=[], kinds=kinds)
    assert alerts == ["Chert agent unhealthy: chert-agent unit is not active"] and "HC_WORKER_URL" not in pings
    assert kinds == ["chert"]   # its own kind, so it cannot be deduped away by another check (D-40)
    alerts, pings = _run_main(monitor, monkeypatch, active={}, entries=[], journal_error=OSError("journal gone"))
    assert len(alerts) == 1 and "chert check failed" in alerts[0] and "HC_WORKER_URL" not in pings
    kinds = []
    alerts, pings = _run_main(monitor, monkeypatch, active={"brodie-worker": False},
                              entries=[(dt.datetime.now(dt.timezone.utc), "Connected to Chert.")], kinds=kinds)
    assert alerts == ["Worker down: brodie-worker unit is not active"] and "HC_WORKER_URL" not in pings
    assert kinds == ["worker"]
