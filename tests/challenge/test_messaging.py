import hashlib
import hmac
import json
from datetime import datetime, timezone

import httpx
import pytest

from challenge.messaging.commands import parse, validate_display_name
from challenge.messaging.providers import (
    ChertProvider, InvalidHandle, MockProvider, NotConfigured, WebOnlyProvider,
    normalize_handle, provider_from_env,
)
from challenge.messaging.templates import render


@pytest.mark.parametrize(("body", "kind", "arg"), [
    (" join: Coach_1 ", "JOIN", "Coach_1"), ("JOIN _coach_", "JOIN", "_coach_"),
    ("!!!jOiN Alex!!!", "JOIN", "Alex"), ("yes!", "YES", ""),
    ("q", "QUEUE", ""), ("LINE", "QUEUE", ""), ("queu", "QUEUE", ""),
    ("quee", "QUEUE", ""), ("staus", "STATUS", ""), ("statis", "STATUS", ""),
    ("s", "STATUS", ""), ("Me", "STATUS", ""), ("leaderboard", "TOP", ""),
    ("lb", "TOP", ""), ("UNSTOP", "START", ""), ("stop!", "STOP", ""),
    ("STOP please", "STOP", "please"), ("start", "START", ""),
    ("LEAVE", "LEAVE", ""), ("rules", "RULES", ""), ("power", "POWER", ""),
    ("help", "HELP", ""), ("", "UNKNOWN", ""), ("...", "UNKNOWN", ""),
    ("hi", "UNKNOWN", ""), ("que", "UNKNOWN", ""),
    ("totally-unrelated", "UNKNOWN", ""), ("JOIN", "JOIN", ""),
    ("delete my data", "DELETE", ""), ("DELETE", "DELETE", ""), ("Delete Data", "DELETE", ""),
    ("delete me", "DELETE", ""), ("  \"Delete   my data.\"  ", "DELETE", ""),
    ("delete my data!!", "DELETE", ""), ("delete everything", "UNKNOWN", "everything"),
    ("deleet my data", "UNKNOWN", "my data"), ("delete my data, stop", "STOP", "my data, stop"),
])
def test_commands(body, kind, arg):
    command = parse(body)
    assert (command.kind, command.arg) == (kind, arg)


@pytest.mark.parametrize("body", [
    "fine", "like", "mine", "john", "stat", "star", "step", "shop",
    "linx", "leaderboar", "starr", "unstopp", "yess", "joi", "joim",
    "joim: !!!", "nonstop", "stopped", "stopper", "stop_all", "quitx",
    "cance", "unsubscrib", "ends", "stopalls",
])
def test_commands_do_not_fuzzy_match_aliases_or_consent(body):
    assert parse(body).kind == "UNKNOWN"


@pytest.mark.parametrize(("body", "kind", "arg"), [
    ("queu", "QUEUE", ""), ("staus", "STATUS", ""),
    ("leav", "LEAVE", ""), ("rule", "RULES", ""),
    ("powe", "POWER", ""), ("helpp", "HELP", ""),
    ("joim: Coach_1", "JOIN", "Coach_1"),
])
def test_canonical_command_typos(body, kind, arg):
    command = parse(body)
    assert (command.kind, command.arg) == (kind, arg)


@pytest.mark.parametrize("word", ["STOP", "STOPALL", "QUIT", "CANCEL", "UNSUBSCRIBE", "END"])
@pytest.mark.parametrize("style", [str.upper, str.lower, str.title])
@pytest.mark.parametrize("wrapper", ["{}", " !!!{}?! ", "“{}”"])
def test_exact_opt_out_words(word, style, wrapper):
    assert parse(wrapper.format(style(word))).kind == "STOP"


@pytest.mark.parametrize("body", [
    "please stop", "please STOP texting me", "please (sToP)! thanks",
    "QUEUE stop", "START please stop", "YES stop", "JOIN stop", "help\nstop\nplease",
])
def test_standalone_stop_overrides_other_commands(body):
    assert parse(body).kind == "STOP"


@pytest.mark.parametrize("name", ["Amy", "Coach_12", "_name_", "A" * 20])
def test_valid_names(name):
    assert validate_display_name(name) == (True, "")


@pytest.mark.parametrize("name", [
    "", "ab", "a" * 21, "two names", "na-me", "éclair", "abc\n", "🙂abc",
    "xxFuCkxx", "Shit123", "faggot123", "nigger123", "asshole99",
])
def test_invalid_names(name):
    ok, reason = validate_display_name(name)
    assert not ok
    assert reason


@pytest.mark.parametrize(("value", "expected"), [
    ("(415) 555-2671", "+14155552671"), ("415.555.2671", "+14155552671"),
    ("1-415-555-2671", "+14155552671"), ("+44 20 7946 0958", "+442079460958"),
    ("  COACH+tag@Example.COM ", "coach+tag@example.com"),
    ("nope", None), ("123", None), ("+0123456789", None),
    ("+1234567890123456", None), ("4155552671 ext 3", None),
    ("x@y", None), ("a b@example.com", None), ("a@-example.com", None),
    ("++14155552671", None), ("４１５５５５２６７１", None), ("", None),
])
def test_normalize_handle(value, expected):
    assert normalize_handle(value) == expected


def envelope(**overrides):
    item = {"id": "msg-1", "handle": "(415) 555-2671", "body": "QUEUE",
            "received_at": "2026-10-12T12:00:00-04:00"}
    item.update(overrides)
    return json.dumps({"messages": [item]}).encode()


def test_mock_round_trip(caplog, monkeypatch):
    monkeypatch.setenv("CHALLENGE_ALLOW_MOCK_WEBHOOK", "1")
    provider = MockProvider()
    with caplog.at_level("INFO"):
        inbound = provider.parse_inbound({}, envelope())[0]
        message_id = provider.send_text(inbound.handle, "You're in line!")
        image_id = provider.send_image(inbound.handle, "https://example.com/card.png", "Nice work!")
    assert inbound.provider_message_id == "msg-1"
    assert inbound.handle == "+14155552671"
    assert inbound.body == "QUEUE"
    assert inbound.received_at == datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
    assert provider.sent == [
        {"id": message_id, "handle": inbound.handle, "body": "You're in line!"},
        {"id": image_id, "handle": inbound.handle, "image_url": "https://example.com/card.png", "caption": "Nice work!"},
    ]
    assert message_id != image_id
    assert provider.verify({}, b"")
    assert "Messaging inbound" in caplog.text
    assert "Messaging outbound" in caplog.text
    assert inbound.handle not in caplog.text


@pytest.mark.parametrize("value", [None, "", "0", "true", "True", "yes", "01", " 1", "1 ", "1"])
def test_mock_webhook_requires_explicit_opt_in(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CHALLENGE_ALLOW_MOCK_WEBHOOK", raising=False)
    else:
        monkeypatch.setenv("CHALLENGE_ALLOW_MOCK_WEBHOOK", value)
    assert MockProvider().verify({}, envelope()) is (value == "1")


@pytest.mark.parametrize("payload", [
    b"garbage", b"[]", b'{}', b'{"messages":{}}', b'{"messages":[{}]}',
    envelope(id=""), envelope(handle="bad"), envelope(body=None),
    envelope(received_at="2026-10-12T12:00:00"), envelope(received_at="invalid"),
])
def test_malformed_inbound_rejected(payload):
    with pytest.raises(ValueError):
        MockProvider().parse_inbound({}, payload)


@pytest.fixture
def chert_env(monkeypatch):
    monkeypatch.setenv("CHERT_MSG_URL", "https://chert.example/api/v1/")
    monkeypatch.setenv("CHERT_MSG_TOKEN", "test-token")
    monkeypatch.setenv("CHERT_WEBHOOK_SECRET", "test-secret")
    monkeypatch.delenv("CHERT_TENANT", raising=False)


NOW = 1_760_300_000


def signed(body, ts=NOW, secret=b"test-secret"):
    return f"t={ts},v1=" + hmac.new(secret, f"{ts}.".encode() + body, hashlib.sha256).hexdigest()


def chert_event(text="QUEUE", **over):
    event = {"event": "message.received", "event_id": "evt-1", "timestamp": "2026-10-12T16:00:01Z",
             "data": {"chat": {"id": "chat-9", "is_group": False, "owner_handle": {"handle": "+14155550000"}},
                      "message": {"id": "msg-1", "direction": "inbound", "sent_at": "2026-10-12T16:00:00Z",
                                  "sender_handle": {"handle": "(415) 555-2671"},
                                  "parts": [{"type": "text", "value": text}]}}}
    for key, value in over.items():
        event["data"]["message"][key] = value
    return json.dumps(event).encode()


def provider(**kw):
    return ChertProvider(now=lambda: NOW, **kw)


def test_chert_signature(chert_env):
    p, body = provider(), chert_event()
    assert p.verify({"X-Webhook-Signature": signed(body)}, body)
    assert p.verify({"x-webhook-signature": signed(body, NOW * 1000)}, body)  # ms timestamps
    legacy = "v1,%s,%s" % (NOW, signed(body).split("v1=")[1])
    assert p.verify({"x-chert-signature": legacy}, body)
    for bad in ({}, {"X-Webhook-Signature": signed(body, NOW - 301)}, {"X-Webhook-Signature": signed(body, secret=b"x")},
                {"X-Webhook-Signature": "t=%s" % NOW}, {"X-Webhook-Signature": None},
                {"X-Webhook-Signature": signed(body), "x-webhook-signature": signed(body)}):
        assert not p.verify(bad, body)
        with pytest.raises(ValueError, match="signature"):
            p.parse_inbound(bad, body)
    assert not p.verify({"X-Webhook-Signature": signed(body)}, body + b" ")


def test_chert_parse_message_received(chert_env):
    p, body = provider(), chert_event()
    [m] = p.parse_inbound({"X-Webhook-Signature": signed(body)}, body)
    assert (m.provider_message_id, m.handle, m.body) == ("msg-1", "+14155552671", "QUEUE")
    assert m.received_at == datetime(2026, 10, 12, 16, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize("body", [
    json.dumps({"event": "lead_reply", "from": "+14155552671", "text": "hi"}).encode(),
    chert_event(direction="outbound"),
    json.dumps({**json.loads(chert_event()), "data": {**json.loads(chert_event())["data"], "chat": {"is_group": True}}}).encode(),
])
def test_chert_ignores_other_events(chert_env, body):
    assert provider().parse_inbound({"X-Webhook-Signature": signed(body)}, body) == []


def test_chert_bad_sender(chert_env):
    body = chert_event(sender_handle={"handle": "not a handle"})
    with pytest.raises(InvalidHandle):
        provider().parse_inbound({"X-Webhook-Signature": signed(body)}, body)


def test_chert_sends(chert_env, monkeypatch):
    monkeypatch.setenv("CHERT_TENANT", "brodie")
    requests = []

    def transport(request):
        requests.append(request)
        path = request.url.path
        if request.url.host == "cards.example":
            return httpx.Response(200, content=b"PNGDATA", headers={"content-type": "image/png"})
        if path.endswith("/send"):
            return httpx.Response(200, json={"status": "sent", "message_id": f"m-{len(requests)}", "lead_id": "lead-7"})
        if path.endswith("/attachments"):
            return httpx.Response(200, json={"id": "att-1"})
        if path.endswith("/upload"):
            return httpx.Response(200, json={"uploaded": True, "size_bytes": 7})
        return httpx.Response(200, json={"message_id": "m-media"})

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        p = provider(client=client)
        assert p.send_text("+14155552671", "Go!") == "m-1"
        assert p.send_image("+14155552671", "https://cards.example/c.png", "Nice!") == "m-media"
    send = requests[0]
    assert str(send.url) == "https://chert.example/api/v1/send"
    assert send.headers["Authorization"] == "Bearer test-token" and send.headers["x-chert-tenant"] == "brodie"
    body = json.loads(send.content)
    assert body["phone"] == "+14155552671" and body["body"] == "Go!" and body["idempotency_key"]
    paths = [(r.method, r.url.path) for r in requests[1:]]
    assert paths == [("GET", "/c.png"), ("POST", "/api/v1/attachments"), ("PUT", "/api/v1/attachments/att-1/upload"),
                     ("POST", "/api/v1/send"), ("POST", "/api/v1/chats/lead-7/messages")]
    assert json.loads(requests[2].content) == {"filename": "brodie-result.png", "content_type": "image/png", "size_bytes": 7}
    assert requests[3].content == b"PNGDATA"
    assert json.loads(requests[5].content) == {"message": {"parts": [{"type": "media", "attachment_id": "att-1"}]}}


@pytest.mark.parametrize(("status", "payload", "error"), [
    (429, {"error": "rate limited"}, httpx.HTTPStatusError),
    (500, {}, httpx.HTTPStatusError), (200, {}, ValueError), (200, {"message_id": ""}, ValueError),
    (200, {"success": False, "error": {"status": 400, "code": 1003, "message": "bad phone"}}, ValueError),
])
def test_chert_send_errors_propagate(chert_env, status, payload, error):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(status, json=payload))) as client:
        with pytest.raises(error):
            provider(client=client).send_text("+14155552671", "Go!")


def test_chert_transport_failure_propagates(chert_env):
    def transport(request):
        raise httpx.ConnectError("Connection failed", request=request)

    with httpx.Client(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(httpx.ConnectError, match="Connection failed"):
            provider(client=client).send_text("+14155552671", "Go!")


def test_chert_default_base_url(chert_env, monkeypatch):
    monkeypatch.delenv("CHERT_MSG_URL")
    assert ChertProvider().base_url == "https://console.trychert.com/api/v1"


def test_inbound_batch_and_empty_envelope():
    provider = MockProvider()
    first = json.loads(envelope())["messages"][0]
    second = json.loads(envelope(id="msg-2", handle="COACH@example.com"))["messages"][0]
    batch = provider.parse_inbound({}, json.dumps({"messages": [first, second]}).encode())
    assert [item.provider_message_id for item in batch] == ["msg-1", "msg-2"]
    assert batch[1].handle == "coach@example.com"
    assert provider.parse_inbound({}, b'{"messages": []}') == []


@pytest.mark.parametrize("key", ["CHERT_MSG_TOKEN", "CHERT_WEBHOOK_SECRET"])
def test_missing_chert_config(chert_env, monkeypatch, key):
    monkeypatch.delenv(key)
    with pytest.raises(NotConfigured):
        ChertProvider()


def test_provider_selection(chert_env, monkeypatch, caplog):
    monkeypatch.delenv("MESSAGING_PROVIDER", raising=False)
    with caplog.at_level("INFO"):
        assert isinstance(provider_from_env(), MockProvider)
        for name, cls in (("web_only", WebOnlyProvider), ("chert", ChertProvider), ("mock", MockProvider)):
            monkeypatch.setenv("MESSAGING_PROVIDER", name)
            assert isinstance(provider_from_env(), cls)
    assert "MESSAGING_PROVIDER=mock" in caplog.text
    monkeypatch.setenv("MESSAGING_PROVIDER", "typo")
    with pytest.raises(NotConfigured):
        provider_from_env()


def test_web_only_does_not_send(caplog):
    provider = WebOnlyProvider()
    with caplog.at_level("INFO"):
        text_id = provider.send_text("+14155552671", "hello")
        image_id = provider.send_image("+14155552671", "https://example.com/image.png", "hello")
    assert text_id.startswith("web_only-")
    assert image_id.startswith("web_only-") and image_id != text_id
    assert provider.parse_inbound({}, envelope()) == []
    assert not provider.verify({}, envelope())
    assert "suppressed" in caplog.text


KEYS = """welcome join_confirm_prompt join_bad_name join_taken queue_joined queue_line_open
queue_at_cap queue_already queue_in_call youre_up missed_slot queue_update left_queue status
top rules power help stop_ack start_ack unknown post_call rank_drop streak_risk ph_announce
ph_warn ph_start daily_recap ending_soon final_results not_registered call_queued delete_request""".split()
PROACTIVE = """welcome youre_up missed_slot queue_update post_call rank_drop streak_risk
ph_announce ph_warn ph_start daily_recap ending_soon final_results""".split()
CTX = {
    "display_name": "Coach_1", "position": 3, "eta": "10 min", "calls_left": 2,
    "claim_window_s": 90, "line_handle": "+15550001111", "points": 120, "valid_reps": 20, "rank": 7, "streak": 3,
    "power_hour": "16:00–17:00", "daily_call_cap": 5,
    "leaders": "1. Ace 500; 2. Bee 450; 3. Cee 400; 4. Dee 350; 5. Eve 300",
    "rejected_reps": 2, "points_earned": 40, "old_rank": 4, "next_rank": 6,
    "points_gap": 12, "yesterday_points": 80, "ends_at": "Sunday 23:59 ET",
    "site_url": "https://example.com", "rules_url": "https://example.com/rules",
    "result_url": "https://example.com/r/call-1",
}


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize("swearing", [False, True])
def test_all_templates(key, swearing):
    text = render(key, CTX, swearing)
    assert 0 < len(text) <= 320
    assert "{" not in text and "}" not in text
    assert ("Hell yeah!" in text) == swearing
    if key in PROACTIVE:
        assert "STOP" in text
    if key == "post_call":
        assert CTX["result_url"] in text


def test_template_content_and_length():
    consent = render("join_confirm_prompt", CTX, False)
    assert "Reply YES" in consent and "18+" in consent and "US" in consent
    assert "agree to the rules" in consent and CTX["rules_url"] in consent
    for field in ("120", "20", "7", "2", "3", "16:00–17:00"):
        assert field in render("status", CTX, False)
    assert "90s" in render("youre_up", CTX, False)
    assert "FaceTime +15550001111 now" in render("youre_up", CTX, False)  # names the line to call
    long = {**CTX, "display_name": "A" * 1000, "leaders": "Runner 100 points; " * 100}
    for key in ("welcome", "top"):
        text = render(key, long, True)
        assert len(text) <= 320
        assert CTX["site_url"] in text
    assert render("welcome", long, True).endswith("Text STOP to opt out.")


def test_template_errors_are_explicit():
    with pytest.raises(KeyError):
        render("missing", CTX, False)
    with pytest.raises(KeyError):
        render("status", {}, False)
    with pytest.raises(ValueError, match="link"):
        render("post_call", {**CTX, "result_url": "https://example.com/" + "a" * 400}, False)
