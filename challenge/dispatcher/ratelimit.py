"""Shared per-client-IP rate limiter for every dispatcher router (SPEC §12: rate-limit public endpoints).

Usage from any router:  `APIRouter(dependencies=[Depends(rate_limit("webhooks"))])` or per route.
The limiter instance lives on `app.state.rate_limiter` (create_app installs one); if an app has none, one is created
from env on first use. Buckets are keyed by (scope, client IP) so a flood of one endpoint family (e.g. public /health)
cannot starve another (e.g. worker /calls/*).

Client IP = the socket peer. X-Forwarded-For is ignored unless TRUSTED_PROXY=1 (the dispatcher sits behind Caddy on
127.0.0.1); then the LAST entry is used, i.e. the address our own proxy saw, which a client cannot forge.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request

DEFAULT_PER_MIN = 600
WINDOW_S = 60.0


def _env_trusted_proxy() -> bool:
    return os.environ.get("TRUSTED_PROXY", "").strip() == "1"


class RateLimiter:
    """Sliding 60 s window, `per_min` hits per key. Thread-safe (sync endpoints run in a threadpool)."""

    def __init__(self, per_min: int, now: Callable[[], float] = time.monotonic, trusted_proxy: bool | None = None,
                 max_keys: int = 50_000):
        if per_min < 1:
            raise ValueError("per_min must be >= 1")
        self.per_min, self.now, self.max_keys = per_min, now, max_keys
        self.trusted_proxy = _env_trusted_proxy() if trusted_proxy is None else trusted_proxy
        self.hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        with self._lock:
            t = self.now()
            q = self.hits.get(key)
            if q is None:
                if len(self.hits) >= self.max_keys:
                    self._sweep(t)
                q = self.hits[key] = deque()
            while q and t - q[0] >= WINDOW_S:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(t)
            return True

    def _sweep(self, t: float) -> None:
        """Drop keys with no hit inside the window (bounds memory under many distinct clients)."""
        for k in [k for k, q in self.hits.items() if not q or t - q[-1] >= WINDOW_S]:
            del self.hits[k]

    def client_ip(self, request: Request) -> str:
        if self.trusted_proxy:
            xff = request.headers.get("x-forwarded-for", "")
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                return parts[-1]
        return request.client.host if request.client else "unknown"


def get_limiter(request: Request) -> RateLimiter:
    lim = getattr(request.app.state, "rate_limiter", None)
    if lim is None:
        lim = RateLimiter(int(os.environ.get("DISPATCHER_RATE_PER_MIN", str(DEFAULT_PER_MIN))))
        request.app.state.rate_limiter = lim
    return lim


def rate_limit(scope: str) -> Callable[[Request], None]:
    """FastAPI dependency factory: 429 when the caller's IP exceeds the limit within `scope`."""

    def dependency(request: Request) -> None:
        lim = get_limiter(request)
        if not lim.check(f"{scope}|{lim.client_ip(request)}"):
            raise HTTPException(429, "rate limited", headers={"Retry-After": str(int(WINDOW_S))})

    dependency.__name__ = f"rate_limit_{scope}"
    return dependency
