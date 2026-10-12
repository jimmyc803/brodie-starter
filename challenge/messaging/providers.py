"""Synchronous messaging adapters; retrying and deduplication belong to the outbox.

ASSUMED pending Chert docs: POST /messages with {handle, body} for text or
{handle, image_url, caption} for images returns {id: str}. Inbound JSON is
{messages: [{id, handle, body, received_at}]} with ISO-8601 aware timestamps.
X-Chert-Signature is the HMAC-SHA256 hex digest of the exact request bytes.
MockProvider uses the same inbound envelope for local round-trip testing.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import re
from typing import Protocol
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
        if not item["id"].strip() or handle is None:
            raise ValueError("Invalid inbound message id or handle")
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


class ChertProvider:
    name = "chert"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self.base_url = os.environ.get("CHERT_MSG_URL", "").strip().rstrip("/")
        self._token = os.environ.get("CHERT_MSG_TOKEN", "").strip()
        self._secret = os.environ.get("CHERT_WEBHOOK_SECRET", "").strip()
        if not all((self.base_url, self._token, self._secret)):
            raise NotConfigured("Chert requires CHERT_MSG_URL, CHERT_MSG_TOKEN, CHERT_WEBHOOK_SECRET")
        self._client = client

    def _send(self, payload: dict[str, str]) -> str:
        request = self._client.post if self._client is not None else httpx.post
        response = request(
            f"{self.base_url}/messages",
            headers={"Authorization": f"Bearer {self._token}"},
            json=payload,
            timeout=10.0,
        )
        response.raise_for_status()
        result = response.json()
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or not result["id"].strip()
        ):
            raise ValueError("Chert response must contain a nonempty message id")
        logger.info("Messaging outbound provider=chert")
        return result["id"]

    def send_text(self, handle: str, body: str) -> str:
        return self._send({"handle": handle, "body": body})

    def send_image(self, handle: str, image_url: str, caption: str) -> str:
        return self._send({"handle": handle, "image_url": image_url, "caption": caption})

    def verify(self, headers: dict, body: bytes) -> bool:
        signatures = [
            value for key, value in headers.items()
            if key.lower() == "x-chert-signature"
        ]
        if len(signatures) != 1 or not isinstance(signatures[0], str):
            return False
        signature = signatures[0]
        if not re.fullmatch(r"[0-9a-fA-F]{64}", signature):
            return False
        expected = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.lower())

    def parse_inbound(self, headers: dict, body: bytes) -> list[Inbound]:
        if not self.verify(headers, body):
            raise ValueError("Invalid Chert webhook signature")
        return _parse_messages(body, self.name)


def provider_from_env() -> MessagingProvider:
    name = os.environ.get("MESSAGING_PROVIDER", "mock").strip().lower()
    factories = {"mock": MockProvider, "web_only": WebOnlyProvider, "chert": ChertProvider}
    if name not in factories:
        raise NotConfigured(f"Unknown MESSAGING_PROVIDER: {name}")
    provider = factories[name]()
    logger.info("Messaging provider selected MESSAGING_PROVIDER=%s", provider.name)
    return provider
