"""Inbound commands and leased delivery against migrated Postgres."""
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from challenge.config import Config
from challenge.dispatcher.app import create_app
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.postcall import StoreOutbox
from challenge.messaging.handler import handle_inbound
from challenge.messaging.outbox import Outbox
from challenge.messaging.providers import Inbound, MockProvider
from challenge.store import PgStore

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 13, 10, tzinfo=ET)
HANDLE = "+15555550123"


@pytest.fixture
def env(db, conn, monkeypatch):
    monkeypatch.setenv("MESSAGING_PROVIDER", "mock")
    monkeypatch.setenv("CHALLENGE_ALLOW_MOCK_WEBHOOK", "1")
    monkeypatch.delenv("OUTBOUND_RATE_PER_MIN", raising=False)
    monkeypatch.setenv("CARD_DELIVERY", "link")
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, updated_at=now()")
    conn.execute("update competition_config set value='20' where key='outbound_rate_per_min'")
    conn.execute("update competition_config set value='false' where key='competition_frozen'")
    store = PgStore(db)
    cfg = Config(store, ttl_s=0)
    provider = MockProvider()
    clock = {"now": T0}
    outbox = Outbox(store, cfg, provider, clock=lambda: clock["now"])
    outbox._at, outbox._tokens = T0, 20.0  # warmed smoother; bucket tests build a fresh (empty) Outbox
    return conn, store, cfg, provider, outbox, clock


def command(env, text, handle=HANDLE, message_id=None):
    conn, store, cfg, _, outbox, clock = env
    inbound = Inbound(message_id or uuid4().hex, handle, text, clock["now"])
    handle_inbound(store, cfg, outbox, inbound, clock["now"])
    return conn.execute("select template, ctx from messages where direction='out' order by id desc limit 1").fetchone()


def register(env):
    assert command(env, "JOIN Athlete")[0] == "join_confirm_prompt"
    assert command(env, "YES")[0] == "welcome"
    return env[1].rpc("ch_user_by_handle", {"p_handle": HANDLE})["user_id"]


def enqueue(env, key, template="help", proactive=False, ctx=None):
    return env[4].enqueue(handle=HANDLE, template=template, ctx=ctx or {},
                          dedupe_key=key, proactive=proactive)


@pytest.mark.parametrize("text,template", [
    ("HELP", "help"), ("nonsense", "unknown"), ("RULES", "rules"), ("POWER", "power"),
    ("TOP", "top"), ("QUEUE", "not_registered"), ("STATUS", "not_registered"),
    ("LEAVE", "not_registered"), ("YES", "not_registered"),
    ("JOIN ab", "join_bad_name"), ("JOIN fucker", "join_bad_name"),
    ("STOP", "stop_ack"), ("START", "start_ack"),
])
def test_unregistered_commands(env, text, template):
    assert command(env, text)[0] == template
    assert env[4].run_once(T0) == 1
    assert env[3].sent[0]["body"]


def test_registered_commands_and_queue(env):
    conn, store, _, provider, outbox, _ = env
    user_id = register(env)
    assert command(env, "JOIN Athlete")[0] == "help"
    assert command(env, "JOIN Athlete", handle="+15555550999")[0] == "join_taken"
    assert command(env, "QUEUE")[0] == "queue_line_open"
    assert command(env, "LEAVE")[0] == "left_queue"
    conn.execute("update line_state set state='offline', offline_until=%s", (T0 + timedelta(hours=1),))
    template, ctx = command(env, "QUEUE")
    assert template == "queue_joined"
    assert ctx["position"] == 1 and ctx["calls_left"] == 5 and ctx["eta"] == "~0–5 min"
    assert command(env, "QUEUE")[0] == "queue_already"
    template, ctx = command(env, "STATUS")
    assert template == "status" and ctx["position"] == 1 and ctx["calls_left"] == 5
    assert command(env, "TOP")[0] == "top"
    assert command(env, "LEAVE")[0] == "left_queue"
    assert store.rpc("ch_user_status", {"p_user_id": user_id, "p_now": T0})["queue_position"] is None
    assert outbox.run_once(T0) == 11
    assert len(provider.sent) == 11


def test_stop_removes_claim_and_suppresses_existing_intents(env):
    conn, store, _, provider, outbox, _ = env
    user_id = register(env)
    command(env, "QUEUE")
    store.rpc("ch_tick", {"p_now": T0})
    enqueue(env, "pending", "ph_start", True)
    command(env, "STOP")
    assert store.rpc("ch_user_by_handle", {"p_handle": HANDLE})["opted_out"]
    assert not conn.execute("select 1 from queue where user_id=%s and status in ('waiting','notified')", (user_id,)).fetchone()
    assert not conn.execute("select 1 from line_state where user_id=%s and state='claimed'", (user_id,)).fetchone()
    outbox.run_once(T0)
    assert conn.execute("select status from messages where dedupe_key='pending'").fetchone()[0] == "suppressed"
    assert sum("You're opted out" in item["body"] for item in provider.sent) == 1
    assert not any("Power hour is LIVE" in item["body"] or "You're up!" in item["body"] for item in provider.sent)
    command(env, "START")
    assert not store.rpc("ch_user_by_handle", {"p_handle": HANDLE})["opted_out"]


def test_power_hour_and_status(env):
    conn = env[0]
    register(env)
    conn.execute("insert into power_hours(date_et, starts_at, ends_at, announced_at) values (%s,%s,%s,%s)",
                 (T0.date(), T0 + timedelta(hours=3), T0 + timedelta(hours=4), T0))
    assert command(env, "POWER")[1]["power_hour"] == "01:00 PM–02:00 PM"
    assert command(env, "STATUS")[1]["power_hour"] == "01:00 PM–02:00 PM"


def test_webhook_dedupe_and_default_store_outbox(env):
    conn, store, _, _, _, clock = env
    app = create_app(store, clock=lambda: clock["now"], flags=Flags(), token="test")
    with TestClient(app) as client:
        payload = {"messages": [{"id": "one", "handle": HANDLE, "body": "JOIN Athlete", "received_at": T0.isoformat()}]}
        assert client.post("/webhooks/mock", json=payload).json() == {"ok": True, "handled": 1}
        assert client.post("/webhooks/mock", json=payload).json() == {"ok": True, "handled": 0}
        assert conn.execute("select count(*) from messages").fetchone()[0] == 2
        assert client.post("/webhooks/mock", json={}).status_code == 400
        assert client.post("/webhooks/chert", json=payload).status_code == 404


def test_webhook_auth(env, monkeypatch):
    _, store, _, _, outbox, _ = env
    monkeypatch.delenv("CHALLENGE_ALLOW_MOCK_WEBHOOK")
    with TestClient(create_app(store, outbox, flags=Flags(), token="test")) as client:
        assert client.post("/webhooks/mock", json={}).status_code == 401
    monkeypatch.setenv("MESSAGING_PROVIDER", "chert")
    monkeypatch.setenv("CHERT_MSG_URL", "https://example.test")
    monkeypatch.setenv("CHERT_MSG_TOKEN", "test")
    monkeypatch.setenv("CHERT_WEBHOOK_SECRET", "test-secret")
    raw = json.dumps({"messages": [{"id": "signed", "handle": HANDLE, "body": "HELP", "received_at": T0.isoformat()}]}).encode()
    signature = hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    with TestClient(create_app(store, outbox, clock=lambda: T0, flags=Flags(MESSAGING_PROVIDER="chert"), token="test")) as client:
        assert client.post("/webhooks/mock", content=raw).status_code == 404
        assert client.post("/webhooks/chert", content=raw).status_code == 401
        assert client.post("/webhooks/chert", content=raw, headers={"X-Chert-Signature": signature}).json()["handled"] == 1
        assert client.post("/webhooks/chert", content=raw + b" ", headers={"X-Chert-Signature": signature}).status_code == 401


def test_quiet_boundary_release_and_bypass(env):
    conn, _, _, provider, outbox, clock = env
    clock["now"] = T0.replace(hour=22, minute=59)
    enqueue(env, "before", "ph_start", True)
    assert outbox.run_once(clock["now"]) == 1
    clock["now"] = T0.replace(hour=23)
    enqueue(env, "quiet", "ph_start", True)
    release = (T0 + timedelta(days=1)).replace(hour=9)
    assert conn.execute("select not_before from messages where dedupe_key='quiet'").fetchone()[0] == release
    enqueue(env, "reply")
    enqueue(env, "turn", "youre_up", True, {"claim_window_s": 90})
    enqueue(env, "post", "post_call", True, {"valid_reps": 10, "rejected_reps": 1,
            "points_earned": 10, "points": 10, "rank": 1, "streak": 1, "result_url": "https://example.test/r/1"})
    assert outbox.run_once(clock["now"]) == 3
    assert outbox.run_once(release - timedelta(seconds=1)) == 0
    assert outbox.run_once(release) == 1
    assert len(provider.sent) == 5


def test_send_time_quiet_check_and_nonproactive_welcome(env):
    conn, store, _, _, outbox, clock = env
    clock["now"] = T0.replace(hour=23)
    legacy = StoreOutbox(store, lambda: clock["now"])
    legacy.enqueue(handle=HANDLE, template="ph_start", ctx={}, dedupe_key="db-intent", proactive=True)
    handle_inbound(store, env[2], legacy, Inbound("join", HANDLE, "JOIN Athlete", clock["now"]), clock["now"])
    handle_inbound(store, env[2], legacy, Inbound("yes", HANDLE, "YES", clock["now"]), clock["now"])
    assert outbox.run_once(clock["now"]) == 2
    assert conn.execute("select status, not_before from messages where dedupe_key='db-intent'").fetchone() == (
        "queued", (T0 + timedelta(days=1)).replace(hour=9))


def test_dedupe_and_token_bucket(env):
    conn, store, cfg, provider, _, clock = env
    outbox = Outbox(store, cfg, provider, clock=lambda: clock["now"])
    conn.execute("update competition_config set value='2' where key='outbound_rate_per_min'")
    assert not enqueue(env, "same")["duplicate"]
    assert enqueue(env, "same")["duplicate"]
    for i in range(4):
        enqueue(env, str(i))
    assert outbox.run_once(T0) == 1
    assert outbox.run_once(T0) == 0
    assert outbox.run_once(T0 + timedelta(seconds=29)) == 0
    assert outbox.run_once(T0 + timedelta(seconds=30)) == 1
    assert outbox.run_once(T0 + timedelta(seconds=60)) == 1
    assert outbox.run_once(T0 + timedelta(seconds=90)) == 1
    assert len(provider.sent) == 4


def test_rate_limit_shared_across_instances(env):
    conn, store, cfg, provider, a, clock = env
    conn.execute("update competition_config set value='4' where key='outbound_rate_per_min'")
    b = Outbox(store, cfg, provider, clock=lambda: clock["now"])
    for i in range(12):
        enqueue(env, f"shared{i}")
    total = 0
    for offset in (0, 0, 30, 30, 59, 59):
        for box in (a, b):
            total += box.run_once(T0 + timedelta(seconds=offset))
    assert total == 4 == len(provider.sent)


def test_run_once_survives_claim_and_mark_failures(env, monkeypatch):
    conn, store, _, provider, outbox, _ = env
    enqueue(env, "flaky")
    real = store.rpc
    calls = {"claim": 0}
    def rpc(fn, args=None):
        if fn == "ch_outbox_claim" and calls["claim"] == 0:
            calls["claim"] += 1
            raise RuntimeError("db down")
        return real(fn, args)
    monkeypatch.setattr(store, "rpc", rpc)
    assert outbox.run_once(T0) == 0
    assert conn.execute("select status from messages where direction='out'").fetchone()[0] == "queued"
    assert outbox.run_once(T0 + timedelta(seconds=1)) == 1


def test_mark_sent_retried_then_gives_up(env, monkeypatch):
    conn, store, _, provider, outbox, _ = env
    monkeypatch.setattr("challenge.messaging.outbox._MARK_BACKOFF_S", 0)
    real = store.rpc
    fails = {"n": 2}
    def rpc(fn, args=None):
        if fn == "ch_outbox_mark" and args["p_status"] == "sent" and fails["n"] > 0:
            fails["n"] -= 1
            raise RuntimeError("db down")
        return real(fn, args)
    monkeypatch.setattr(store, "rpc", rpc)
    enqueue(env, "mark1")
    assert outbox.run_once(T0) == 1
    assert conn.execute("select status from messages where direction='out'").fetchone()[0] == "sent"
    fails["n"] = 99
    enqueue(env, "mark2")
    assert outbox.run_once(T0 + timedelta(seconds=30)) == 1
    assert conn.execute("select status from messages where dedupe_key='mark2'").fetchone()[0] == "sending"
    assert len(provider.sent) == 2


def test_webhook_retry_after_handler_failure_and_bad_handle(env, monkeypatch):
    conn, store, _, _, _, clock = env
    import challenge.dispatcher.webhooks as hooks
    app = create_app(store, clock=lambda: clock["now"], flags=Flags(), token="test")
    payload = {"messages": [{"id": "stop1", "handle": HANDLE, "body": "STOP", "received_at": T0.isoformat()}]}
    real = hooks.handle_inbound
    def boom(*args, **kwargs):
        raise RuntimeError("handler down")
    monkeypatch.setattr(hooks, "handle_inbound", boom)
    with TestClient(app) as client:
        assert client.post("/webhooks/mock", json=payload).status_code == 503
        monkeypatch.setattr(hooks, "handle_inbound", real)
        assert client.post("/webhooks/mock", json=payload).json() == {"ok": True, "handled": 1}
        assert client.post("/webhooks/mock", json=payload).json() == {"ok": True, "handled": 0}
        assert conn.execute("select count(*) from messages where direction='out'").fetchone()[0] == 1
        for bad in ("", "not a handle"):
            bad_payload = {"messages": [{"id": "b" + bad[:1], "handle": bad, "body": "HELP", "received_at": T0.isoformat()}]}
            response = client.post("/webhooks/mock", json=bad_payload)
            assert response.status_code == 200
            assert response.json() == {"ok": False, "reason": "bad_handle"}


def test_msg_migration_rpcs(env):
    conn, store, *_ = env
    rec = store.rpc("ch_inbound_record", {"p_provider_message_id": "m1", "p_handle": HANDLE, "p_body": "x", "p_now": T0})
    assert store.rpc("ch_inbound_is_done", {"p_id": rec["id"]}) is False
    assert store.rpc("ch_inbound_done", {"p_id": rec["id"], "p_now": T0}) == {"ok": True}
    assert store.rpc("ch_inbound_is_done", {"p_id": rec["id"]}) is True
    assert store.rpc("ch_outbox_sent_recent", {"p_now": T0, "p_window_s": 60}) == 0
    for fn in ("ch_inbound_done", "ch_inbound_is_done", "ch_outbox_sent_recent"):
        assert conn.execute("select has_function_privilege('anon', %s::regproc, 'execute')", (fn,)).fetchone()[0] is False
        assert conn.execute("select has_function_privilege('service_role', %s::regproc, 'execute')", (fn,)).fetchone()[0] is True


def test_retry_then_success(env, monkeypatch):
    conn, _, _, provider, outbox, _ = env
    original = provider.send_text
    def fail(handle, body):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(provider, "send_text", fail)
    enqueue(env, "retry")
    assert outbox.run_once(T0) == 0
    assert conn.execute("select status, attempts, not_before from messages").fetchone() == ("queued", 1, T0 + timedelta(seconds=2))
    monkeypatch.setattr(provider, "send_text", original)
    assert outbox.run_once(T0 + timedelta(seconds=1)) == 0
    assert outbox.run_once(T0 + timedelta(seconds=2)) == 1
    assert conn.execute("select status, attempts from messages").fetchone() == ("sent", 2)


def test_max_attempts(env, monkeypatch):
    def fail(handle, body):
        raise RuntimeError("provider unavailable")
    monkeypatch.setattr(env[3], "send_text", fail)
    enqueue(env, "fail")
    now = T0
    for attempt in range(1, 6):
        assert env[4].run_once(now) == 0
        now += timedelta(seconds=2 ** attempt)
    assert env[0].execute("select status, attempts from messages").fetchone() == ("failed", 5)
    assert env[4].run_once(now) == 0


def test_lease_reclaim_and_fenced_mark(env):
    conn, store, _, provider, outbox, _ = env
    enqueue(env, "lease")
    old = store.rpc("ch_outbox_claim", {"p_limit": 1, "p_now": T0})[0]
    assert outbox.run_once(T0 + timedelta(seconds=59)) == 0
    assert outbox.run_once(T0 + timedelta(seconds=60)) == 1
    outbox._mark(old, "queued", error="late failure", retry_at=T0)
    assert conn.execute("select status, attempts from messages").fetchone() == ("sent", 2)
    assert len(provider.sent) == 1


@pytest.mark.parametrize("delivery", ["attachment", "link"])
def test_card_delivery(env, monkeypatch, delivery):
    monkeypatch.setenv("CARD_DELIVERY", delivery)
    enqueue(env, "card", ctx={"media_url": "https://example.test/card.png"})
    assert env[4].run_once(T0) == 1
    assert ("image_url" in env[3].sent[0]) == (delivery == "attachment")


def test_environment_rate_override(env, monkeypatch):
    monkeypatch.setenv("OUTBOUND_RATE_PER_MIN", "1")
    enqueue(env, "first")
    enqueue(env, "second")
    assert env[4].run_once(T0) == 1
    assert env[4].run_once(T0) == 0


def test_queue_in_call_and_at_cap(env):
    _, store, _, _, _, clock = env
    register(env)
    started = store.rpc("ch_call_start", {"p_call_id": "active", "p_line_id": "line-1",
                                         "p_handle": HANDLE, "p_mode": "chert_meta", "p_now": T0})
    assert started["decision"] == "accept"
    assert command(env, "QUEUE")[0] == "queue_in_call"
    for index in range(5):
        now = T0 + timedelta(minutes=10 * index)
        call_id = "active" if index == 0 else f"cap-{index}"
        if index:
            store.rpc("ch_tick", {"p_now": now})
            assert store.rpc("ch_call_start", {"p_call_id": call_id, "p_line_id": "line-1",
                "p_handle": HANDLE, "p_mode": "chert_meta", "p_now": now})["decision"] == "accept"
        store.rpc("ch_call_end", {"p_call_id": call_id, "p_ended_at": now + timedelta(seconds=40),
                                  "p_count_end_at": now + timedelta(seconds=40), "p_rep_count": 0, "p_now": now + timedelta(seconds=40)})
    clock["now"] = T0 + timedelta(hours=1)
    assert command(env, "QUEUE")[0] == "queue_at_cap"
