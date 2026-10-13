"""Chert FaceTime end-call client (HANGUP_MODE=chert_api, task 35, CONTRACTS C7.h).

POST {base}/v1/calls/{call_id}/end with `Authorization: Bearer ftk_...`, `X-Chert-Project-Id` and an `Idempotency-Key`
(docs.trychert.com/facetime/calls-api). HTTP 202 acknowledges. The token and project id come from env
CHERT_FACETIME_TOKEN / CHERT_PROJECT_ID and are never logged (nor are request headers or exception texts)."""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Awaitable, Callable

import httpx

log = logging.getLogger("challenge.worker.chert")

BASE_URL = "https://facetime.trychert.com/api"
ATTEMPTS = 3
BACKOFF_S = (0.5, 1.5)          # sleep before attempt 2 and 3
TIMEOUT_S = 5.0
ENV_NAMES = ("CHERT_FACETIME_TOKEN", "CHERT_PROJECT_ID")
# Header-safe credentials only: a control char or space would make h11/httpcore raise LocalProtocolError, whose
# DEBUG trace echoes the header value. Reject before any transport sees it.
_HEADER_SAFE = re.compile(r"^[\x21-\x7e]{1,512}$")
_CALL_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def missing_env() -> list[str]:
    return [k for k in ENV_NAMES if not (os.environ.get(k) or "").strip()]


class ChertEndClient:
    def __init__(self, token: str, project_id: str, *, base_url: str | None = None, timeout: float = TIMEOUT_S,
                 transport: httpx.AsyncBaseTransport | None = None, attempts: int = ATTEMPTS,
                 backoff_s: tuple[float, ...] = BACKOFF_S):
        if not token or not project_id:
            raise ValueError("Chert token and project id are required")
        if not _HEADER_SAFE.match(token) or not _HEADER_SAFE.match(project_id):
            raise ValueError("Chert token or project id contains invalid characters")
        self._headers = {"Authorization": f"Bearer {token}", "X-Chert-Project-Id": project_id}
        self.base_url = (base_url or os.environ.get("CHERT_FACETIME_URL") or BASE_URL).rstrip("/")
        self.timeout, self._transport = float(timeout), transport
        self.attempts, self.backoff_s = int(attempts), tuple(backoff_s)

    @classmethod
    def from_env(cls, **kw) -> "ChertEndClient":
        miss = missing_env()
        if miss:
            raise ValueError(f"{' and '.join(miss)} not set")
        return cls(os.environ["CHERT_FACETIME_TOKEN"].strip(), os.environ["CHERT_PROJECT_ID"].strip(), **kw)

    async def end_call(self, call_id: str, sleep: Callable[[float], Awaitable[object]]) -> bool:
        """True once Chert acknowledged the end request (2xx). A 4xx is final (no retry); a 5xx, a timeout or a
        network error is retried with backoff, then False (the caller falls back to leaving the room)."""
        if not _CALL_ID.match(str(call_id or "")):
            log.error("chert end-call skipped: malformed call id")
            return False
        url = f"{self.base_url}/v1/calls/{call_id}/end"
        headers = {**self._headers, "Idempotency-Key": f"brodie-end-{call_id}", "Content-Type": "application/json"}
        for n in range(1, self.attempts + 1):
            why = ""
            try:
                # httpx's timeout is per-inactivity; wait_for makes it an absolute per-attempt deadline so a
                # trickling response can't hold the room-leave fallback hostage.
                r = await asyncio.wait_for(self._post(url, headers), self.timeout)
                if r.status_code < 300:
                    log.info("chert end-call %s acknowledged (HTTP %d)", call_id, r.status_code)
                    return True
                if r.status_code < 500:
                    log.error("chert end-call %s refused (HTTP %d); not retrying", call_id, r.status_code)
                    return False
                why = f"HTTP {r.status_code}"
            except (httpx.HTTPError, asyncio.TimeoutError) as e:
                why = type(e).__name__
            log.warning("chert end-call %s attempt %d/%d failed (%s)", call_id, n, self.attempts, why)
            if n < self.attempts:
                await sleep(self.backoff_s[min(n - 1, len(self.backoff_s) - 1)] if self.backoff_s else 0.0)
        return False

    async def _post(self, url: str, headers: dict) -> httpx.Response:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as c:
            return await c.post(url, headers=headers, content=b"{}")
