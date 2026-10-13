"""Synchronous messaging adapters; retrying and deduplication belong to the outbox.

ChertProvider follows the Chert Messaging API (console.trychert.com/documentation, webhook version 2026-05-04):
POST /send {phone, body, idempotency_key} for text; images go register -> upload -> chat message with a media part.
Inbound is a signed `message.received` event; see ChertProvider.parse_inbound.
MockProvider keeps the simple envelope {messages: [{id, handle, body, received_at}]} for local round-trip testing.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import time
from typing import Callable, Protocol
from uuid import uuid4

import httpx


logger = logging.getLogger(__name__)


class NotConfigured(RuntimeError):
    """A selected provider is missing required configuration."""


@dataclass(frozen=True)
class Inbound:
    provider_message_id: str
    handle: str
    body: str
    received_at: datetime


class MessagingProvider(Protocol):
    name: str

    def send_text(self, handle: str, body: str) -> str: ...

    def send_image(self, handle: str, image_url: str, caption: str) -> str: ...

    def parse_inbound(self, headers: dict, body: bytes) -> list[Inbound]: ...

    def verify(self, headers: dict, body: bytes) -> bool: ...


class InvalidHandle(ValueError):
    """An inbound message carried an empty or unusable handle (not retryable)."""


def normalize_handle(value: str) -> str | None:
    """Normalize a phone number or email without guessing international prefixes."""
    value = value.strip()
    if re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", value):
        return value.lower()
    if not re.fullmatch(r"\+?[0-9 () .-]+", value):
        return None
    number = re.sub(r"[ () .-]", "", value)
    if not number.startswith("+"):
        if len(number) == 10:
            number = "+1" + number
        elif len(number) == 11 and number.startswith("1"):
            number = "+" + number
        else:
            return None
    return number if re.fullmatch(r"\+[1-9][0-9]{1,14}", number) else None


def _parse_messages(body: bytes, provider: str) -> list[Inbound]:
    payload = json.loads(body)
    if not isinstance(payload, dict) or not isinstance(payload.get("messages"), list):
        raise ValueError("Expected a messages array")
    messages: list[Inbound] = []
    for item in payload["messages"]:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(key), str)
            for key in ("id", "handle", "body", "received_at")
        ):
            raise ValueError("Invalid inbound message fields")
        handle = normalize_handle(item["handle"])
        if not item["id"].strip():
            raise ValueError("Invalid inbound message id")
        if handle is None:
            raise InvalidHandle("Invalid inbound message handle")
        received_at = datetime.fromisoformat(item["received_at"].replace("Z", "+00:00"))
        if received_at.tzinfo is None:
            raise ValueError("Inbound received_at must include a timezone")
        messages.append(Inbound(
            item["id"], handle, item["body"], received_at.astimezone(timezone.utc)
        ))
    for _ in messages:
        logger.info("Messaging inbound provider=%s", provider)
    return messages


class MockProvider:
    name = "mock"

    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def _send(self, handle: str, **content: str) -> str:
        message_id = f"{self.name}-{uuid4().hex}"
        self.sent.append({"id": message_id, "handle": handle, **content})
        logger.info(
            "Messaging outbound provider=%s kind=%s",
            self.name, "image" if "image_url" in content else "text",
        )
        return message_id

    def send_text(self, handle: str, body: str) -> str:
        return self._send(handle, body=body)

    def send_image(self, handle: str, image_url: str, caption: str) -> str:
        return self._send(handle, image_url=image_url, caption=caption)

    def verify(self, headers: dict, body: bytes) -> bool:
        """Accept mock webhooks only with CHALLENGE_ALLOW_MOCK_WEBHOOK=1."""
        return os.environ.get("CHALLENGE_ALLOW_MOCK_WEBHOOK") == "1"

    def parse_inbound(self, headers: dict, body: bytes) -> list[Inbound]:
        return _parse_messages(body, self.name)


class WebOnlyProvider:
    name = "web_only"

    def _send(self) -> str:
        logger.info("Messaging outbound suppressed provider=web_only")
        return f"web_only-{uuid4().hex}"

    def send_text(self, handle: str, body: str) -> str:
        return self._send()

    def send_image(self, handle: str, image_url: str, caption: str) -> str:
        return self._send()

    def verify(self, headers: dict, body: bytes) -> bool:
        return False

    def parse_inbound(self, headers: dict, body: bytes) -> list[Inbound]:
        return []


CHERT_API = "https://console.trychert.com/api/v1"
CHERT_WEBHOOK_VERSION = "2026-05-04"
SIGNATURE_TOLERANCE_S = 300


class ChertProvider:
    """Chert iMessage line. Env: CHERT_MSG_TOKEN (the project's signing secret, sent as Bearer),
    CHERT_WEBHOOK_SECRET (the webhook subscription secret), optional CHERT_MSG_URL (API base),
    CHERT_TENANT (x-chert-tenant, multi-tenant projects only)."""
    name = "chert"

    def __init__(self, *, client: httpx.Client | None = None, now: Callable[[], float] | None = None) -> None:
        self.base_url = (os.environ.get("CHERT_MSG_URL", "").strip() or CHERT_API).rstrip("/")
        self._token = os.environ.get("CHERT_MSG_TOKEN", "").strip()
        self._secret = os.environ.get("CHERT_WEBHOOK_SECRET", "").strip()
        self._tenant = os.environ.get("CHERT_TENANT", "").strip()
        if not all((self._token, self._secret)):
            raise NotConfigured("Chert requires CHERT_MSG_TOKEN and CHERT_WEBHOOK_SECRET")
        self._client = client
        self._now = now or time.time

    def _headers(self, content_type: str = "application/json") -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": content_type}
        if self._tenant:
            headers["x-chert-tenant"] = self._tenant
        return headers

    def _call(self, method: str, path: str, *, json_body: dict | None = None, content: bytes | None = None,
              content_type: str = "application/json") -> dict:
        client = self._client or httpx.Client()
        try:
            response = client.request(method, f"{self.base_url}{path}", headers=self._headers(content_type),
                                      json=json_body, content=content, timeout=15.0)
        finally:
            if self._client is None:
                client.close()
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or result.get("success") is False:
            error = result.get("error") if isinstance(result, dict) else None
            raise ValueError(f"Chert error: {error.get('code') if isinstance(error, dict) else 'bad response'}")
        return result

    @staticmethod
    def _id(result: dict, *keys: str) -> str:
        for key in keys:
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        data = result.get("data")
        if isinstance(data, dict):
            return ChertProvider._id(data, *keys)
        raise ValueError(f"Chert response must contain one of {keys}")

    def _send(self, handle: str, body: str) -> dict:
        result = self._call("POST", "/send", json_body={"phone": handle, "body": body, "idempotency_key": uuid4().hex})
        logger.info("Messaging outbound provider=chert kind=text")
        return result

    def send_text(self, handle: str, body: str) -> str:
        return self._id(self._send(handle, body), "message_id", "id")

    def send_image(self, handle: str, image_url: str, caption: str) -> str:
        """Caption first (via /send, which also yields the chat id), then the image as a media part."""
        fetch = self._client or httpx.Client()
        try:
            image = fetch.get(image_url, timeout=15.0, follow_redirects=True)
        finally:
            if self._client is None:
                fetch.close()
        image.raise_for_status()
        content_type = image.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
        data = image.content
        attachment = self._id(self._call("POST", "/attachments", json_body={
            "filename": "brodie-result." + (content_type.split("/")[-1] or "png"),
            "content_type": content_type, "size_bytes": len(data)}), "attachment_id", "id")
        self._call("PUT", f"/attachments/{attachment}/upload", content=data, content_type=content_type)
        chat = self._id(self._send(handle, caption), "lead_id", "chat_id", "convo_id")
        result = self._call("POST", f"/chats/{chat}/messages",
                            json_body={"message": {"parts": [{"type": "media", "attachment_id": attachment}]}})
        logger.info("Messaging outbound provider=chert kind=image")
        return self._id(result, "message_id", "id")

    def verify(self, headers: dict, body: bytes) -> bool:
        """HMAC-SHA256(secret, "<ts>.<raw body>") from `X-Webhook-Signature: t=<ts>,v1=<hex>`, or the legacy
        `x-chert-signature: v1,<ts>,<hex>`. Rejects stale timestamps (replay) and ambiguous duplicate headers."""
        def one(name: str) -> str | None:
            values = [v for k, v in headers.items() if k.lower() == name]
            return values[0] if len(values) == 1 and isinstance(values[0], str) else None

        ts = digest = None
        modern = one("x-webhook-signature")
        if modern is not None:
            fields = dict(part.split("=", 1) for part in modern.split(",") if "=" in part)
            ts, digest = fields.get("t"), fields.get("v1")
        else:
            legacy = one("x-chert-signature")
            parts = legacy.split(",") if legacy else []
            if len(parts) == 3 and parts[0] == "v1":
                ts, digest = parts[1], parts[2]
        if not ts or not digest or not re.fullmatch(r"[0-9]{1,13}", ts) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
            return False
        stamp = int(ts) / (1000 if len(ts) > 11 else 1)
        if abs(self._now() - stamp) > SIGNATURE_TOLERANCE_S:
            return False
        expected = hmac.new(self._secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, digest.lower())

    def parse_inbound(self, headers: dict, body: bytes) -> list[Inbound]:
        """One `message.received` event -> at most one Inbound. Other events (incl. legacy `lead_reply`),
        group chats and our own outbound echoes are acknowledged and ignored."""
        if not self.verify(headers, body):
            raise ValueError("Invalid Chert webhook signature")
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object")
        event = payload.get("event") or payload.get("event_type") or payload.get("type")
        if event != "message.received":
            return []
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        chat = data.get("chat") if isinstance(data.get("chat"), dict) else {}
        message = data.get("message") if isinstance(data.get("message"), dict) else {}
        if chat.get("is_group") is True:
            return []
        if str(message.get("direction", "inbound")).lower() in ("outbound", "outgoing", "sent"):
            return []
        sender = message.get("sender_handle")
        handle_raw = (sender.get("handle") if isinstance(sender, dict) else None) or payload.get("from")
        message_id = message.get("id") or payload.get("message_guid") or payload.get("event_id")
        if not isinstance(message_id, str) or not message_id.strip():
            raise ValueError("Invalid inbound message id")
        if not isinstance(handle_raw, str):
            raise InvalidHandle("Missing inbound sender handle")
        handle = normalize_handle(handle_raw)
        if handle is None:
            raise InvalidHandle("Invalid inbound message handle")
        parts = message.get("parts") if isinstance(message.get("parts"), list) else []
        texts = [p["value"] for p in parts if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("value"), str)]
        text = " ".join(texts) if texts else (payload.get("text") if isinstance(payload.get("text"), str) else "")
        received_at = _when(message.get("sent_at")) or _when(payload.get("timestamp")) or datetime.now(timezone.utc)
        logger.info("Messaging inbound provider=chert")
        return [Inbound(message_id, handle, text, received_at)]


def _when(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(value / (1000 if value > 1e11 else 1), timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def provider_from_env() -> MessagingProvider:
    name = os.environ.get("MESSAGING_PROVIDER", "mock").strip().lower()
    factories = {"mock": MockProvider, "web_only": WebOnlyProvider, "chert": ChertProvider}
    if name not in factories:
        raise NotConfigured(f"Unknown MESSAGING_PROVIDER: {name}")
    provider = factories[name]()
    logger.info("Messaging provider selected MESSAGING_PROVIDER=%s", provider.name)
    return provider
