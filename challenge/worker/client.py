"""Dispatcher HTTP client for the FaceTime worker (CONTRACTS C4).

Every POST carries X-Brodie-Token and is retried with exponential backoff on transport errors, timeouts and
retryable statuses (408/425/429/5xx); other 4xx fail at once (a retry cannot fix them). Retrying is safe because
the dispatcher is idempotent: ch_call_start on call_id, /calls/event on idem_key (default `<call_id>:<kind>`, the
same key the reconciler replays from the local checkpoint).

    c = DispatcherClient(base_url, token, timeout=3, retries=3)
    await c.start_call(call_id, line_id, handle)        -> {decision, user_id, reason, cue, power_hour_active?, config?}
    await c.event(kind, call_id, payload, at=None)      -> {ok, duplicate, ...}
    await c.heartbeat(line_id, detail)                  -> {ok}
Failures raise DispatcherError (the caller decides how to degrade; nothing here swallows an error).
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

log = logging.getLogger("challenge.worker.client")

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
EVENT_KINDS = ("call_started", "call_ended", "reps_committed")
START_MIN_RETRIES = 6          # /calls/start with a deadline: retries until the deadline (P1-2), idempotent on call_id


class DispatcherError(Exception):
    """The dispatcher could not be reached or refused the request."""

    def __init__(self, msg: str, status: int | None = None, retryable: bool = True):
        super().__init__(msg)
        self.status = status
        self.retryable = retryable


def idem_key(call_id: str, kind: str) -> str:
    return f"{call_id}:{kind}"


def utc_iso(ts: float | None = None) -> str:
    """Epoch seconds (None = now) as an ISO-8601 UTC timestamp."""
    return datetime.fromtimestamp(time.time() if ts is None else float(ts), tz=timezone.utc).isoformat()


class DispatcherClient:
    def __init__(self, base_url: str, token: str, timeout: float = 3.0, retries: int = 3, *,
                 backoff_s: float = 0.5, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Callable[[float], Awaitable[Any]] | None = None,
                 monotonic: Callable[[], float] = time.monotonic):
        if not base_url:
            raise ValueError("DispatcherClient needs a base_url (DISPATCHER_URL)")
        if not token:
            raise ValueError("DispatcherClient needs a token (DISPATCHER_TOKEN)")
        if retries < 0:
            raise ValueError(f"retries must be >= 0, got {retries}")
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.backoff_s = float(backoff_s)
        self._sleep = sleep or asyncio.sleep
        self._mono = monotonic
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout, transport=transport,
                                         headers={"X-Brodie-Token": token})

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None, **kw: Any) -> "DispatcherClient":
        env = os.environ if env is None else env
        return cls(env.get("DISPATCHER_URL", "").strip(), env.get("DISPATCHER_TOKEN", "").strip(),
                   timeout=float(env.get("DISPATCHER_TIMEOUT_S") or 3), retries=int(env.get("DISPATCHER_RETRIES") or 3), **kw)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, body: dict, *, retries: int | None = None, deadline_s: float | None = None) -> dict:
        attempts = 1 + (self.retries if retries is None else int(retries))
        t0 = self._mono()
        last: DispatcherError | None = None
        for i in range(attempts):
            timeout = self.timeout
            if deadline_s is not None:
                left = deadline_s - (self._mono() - t0)
                if left <= 0:
                    break
                timeout = min(timeout, left)
            try:
                r = await self._client.post(path, json=body, timeout=timeout)
            except httpx.HTTPError as e:
                last = DispatcherError(f"POST {path}: {type(e).__name__}: {e}")
            else:
                if r.status_code < 300:
                    try:
                        out = r.json()
                    except ValueError as e:
                        raise DispatcherError(f"POST {path}: bad JSON in the response", r.status_code, False) from e
                    if not isinstance(out, dict):
                        raise DispatcherError(f"POST {path}: response is not an object", r.status_code, False)
                    return out
                last = DispatcherError(f"POST {path}: HTTP {r.status_code}", r.status_code, r.status_code in RETRYABLE_STATUS)
                if not last.retryable:
                    raise last
            if i < attempts - 1:
                delay = self.backoff_s * (2 ** i)
                if deadline_s is not None:
                    delay = min(delay, max(0.0, deadline_s - (self._mono() - t0)))
                log.warning("%s (attempt %d/%d); retrying in %.2f s", last, i + 1, attempts, delay)
                await self._sleep(delay)
        raise last or DispatcherError(f"POST {path}: no attempt fit in the {deadline_s} s deadline")

    async def start_call(self, call_id: str, line_id: str, handle: str | None = None, *,
                         deadline_s: float | None = None, retries: int | None = None) -> dict:
        """POST /calls/start. deadline_s bounds the whole retry loop (the gatekeeper must answer within seconds); within
        a deadline at least START_MIN_RETRIES retries are made (fast failures keep retrying until the deadline). Safe:
        ch_call_start is idempotent on call_id."""
        body: dict[str, Any] = {"call_id": call_id, "line_id": line_id}
        if handle:
            body["handle"] = handle
        if retries is None and deadline_s is not None:
            retries = max(self.retries, START_MIN_RETRIES)
        r = await self._post("/calls/start", body, retries=retries, deadline_s=deadline_s)
        if r.get("decision") not in ("accept", "reject"):
            raise DispatcherError(f"/calls/start: unexpected decision {r.get('decision')!r}", None, False)
        return r

    async def event(self, kind: str, call_id: str, payload: dict, *, at: str | None = None,
                    key: str | None = None) -> dict:
        """POST /calls/event with idem_key `<call_id>:<kind>` (or `key`)."""
        if kind not in EVENT_KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        return await self._post("/calls/event", {"kind": kind, "call_id": call_id, "idem_key": key or idem_key(call_id, kind),
                                                 "at": at or utc_iso(), "payload": payload})

    async def heartbeat(self, line_id: str, detail: dict | None = None, *, scope: str = "job", healthy: bool = True) -> dict:
        """POST /calls/heartbeat (one attempt: the next beat is the retry)."""
        return await self._post("/calls/heartbeat", {"line_id": line_id, "scope": scope, "healthy": bool(healthy),
                                                     "detail": detail or {}}, retries=0)


def heartbeat_sync(base_url: str, token: str, line_id: str, detail: dict | None = None, timeout: float = 3.0,
                   transport: httpx.BaseTransport | None = None, *, healthy: bool = True) -> dict:
    """Blocking heartbeat for the worker's supervisor thread (no event loop there). Raises DispatcherError."""
    try:
        with httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport,
                          headers={"X-Brodie-Token": token}) as c:
            r = c.post("/calls/heartbeat", json={"line_id": line_id, "scope": "supervisor", "healthy": bool(healthy),
                                                 "detail": detail or {}})
    except httpx.HTTPError as e:
        raise DispatcherError(f"POST /calls/heartbeat: {type(e).__name__}: {e}") from e
    if r.status_code >= 300:
        raise DispatcherError(f"POST /calls/heartbeat: HTTP {r.status_code}", r.status_code, r.status_code in RETRYABLE_STATUS)
    try:
        return r.json()
    except ValueError as e:
        raise DispatcherError("POST /calls/heartbeat: bad JSON in the response", r.status_code, False) from e
