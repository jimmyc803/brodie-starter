"""Web-only join / queue / status (CONTRACTS C4 /web/*; SPEC §3 row 2 MESSAGING_PROVIDER=web_only fallback).

Auth: `Authorization: Bearer <Supabase user access token>`, verified locally (signature, exp, aud=authenticated,
issuer, role=authenticated, non-anonymous, uuid `sub`). HS256 tokens need SUPABASE_JWT_SECRET; asymmetric tokens
(ES256/RS256/EdDSA) are checked against the project JWKS. The algorithm family is pinned to the configured key type,
so a token can never be verified with the wrong kind of key (no alg confusion, no `none`).

Identity: the competitor is resolved ONLY from the verified `sub` via ch_user_by_auth; no endpoint accepts a user_id,
and request bodies forbid unknown fields. Every response describes the caller's own record only.

Rate limits: per client IP before auth (cheap flood guard) and per verified user after it.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime
from threading import Lock
from typing import Any, Callable, Literal

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from challenge.messaging.commands import validate_display_name
from challenge.messaging.providers import normalize_handle
from challenge.scoring import eta_range
from challenge.store import Store, StoreError

logger = logging.getLogger("challenge.dispatcher.web")

_ASYMMETRIC = ("ES256", "RS256", "EdDSA")


class AuthError(Exception):
    """Token rejected (401)."""


class AuthUnavailable(Exception):
    """Verification could not run (JWKS unreachable / not configured) (503)."""


class JwtVerifier:
    """Verifies Supabase user access tokens.

    hs_secret: legacy shared secret (SUPABASE_JWT_SECRET) for HS256 tokens.
    jwks: kid -> public key resolver for asymmetric tokens (default: PyJWKClient on {SUPABASE_URL}/auth/v1/.well-known/jwks.json).
    issuer: expected `iss` ({SUPABASE_URL}/auth/v1); None skips the check.
    """

    def __init__(self, hs_secret: str | None = None, jwks: Callable[[str | None], Any] | None = None,
                 issuer: str | None = None, audience: str = "authenticated"):
        self.hs_secret, self.jwks, self.issuer, self.audience = hs_secret or None, jwks, issuer, audience

    @property
    def configured(self) -> bool:
        return bool(self.hs_secret or self.jwks)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "JwtVerifier":
        env = os.environ if env is None else env
        url = (env.get("SUPABASE_URL") or "").rstrip("/")
        resolver: Callable[[str | None], Any] | None = None
        if url:
            client = jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True, lifespan=600, timeout=5)

            def _resolve(kid: str | None) -> Any:
                if not kid:
                    raise AuthError("missing kid")
                try:
                    return client.get_signing_key(kid).key
                except jwt.PyJWKClientConnectionError as e:
                    raise AuthUnavailable(str(e)) from e
                except jwt.PyJWKClientError as e:  # unknown kid / empty set: the token is not ours
                    raise AuthError(str(e)) from e

            resolver = _resolve
        return cls(hs_secret=env.get("SUPABASE_JWT_SECRET"), jwks=resolver, issuer=f"{url}/auth/v1" if url else None)

    def verify(self, token: str) -> dict[str, Any]:
        if not self.configured:
            raise AuthUnavailable("no JWT verification key configured")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise AuthError("malformed token") from e
        alg = header.get("alg")
        if alg == "HS256" and self.hs_secret:
            key: Any = self.hs_secret
        elif alg in _ASYMMETRIC and self.jwks:
            key = self.jwks(header.get("kid"))
        else:
            raise AuthError(f"unsupported alg {alg!r}")
        try:
            claims = jwt.decode(token, key, algorithms=[alg], audience=self.audience, issuer=self.issuer,
                                options={"require": ["exp", "sub", "aud"], "verify_iss": self.issuer is not None})
        except jwt.PyJWTError as e:
            raise AuthError(type(e).__name__) from e
        if claims.get("role") != "authenticated" or claims.get("is_anonymous") is True:
            raise AuthError("not a signed-in user")
        try:
            claims["sub"] = str(uuid.UUID(str(claims["sub"])))
        except ValueError as e:
            raise AuthError("bad sub") from e
        return claims


# TODO(task 25): swap for challenge/dispatcher/ratelimit.py once it lands (not in this branch yet).
class _Limiter:
    """Thread-safe sliding 60 s window per key; empty keys are dropped so memory stays bounded."""

    def __init__(self, per_min: int, now: Callable[[], float] = time.monotonic):
        self.per_min, self.now, self.hits, self.lock = per_min, now, defaultdict(deque), Lock()

    def check(self, key: str) -> bool:
        with self.lock:
            t, q = self.now(), self.hits[key]
            while q and t - q[0] >= 60:
                q.popleft()
            if len(q) >= self.per_min:
                return False
            q.append(t)
            if len(self.hits) > 10_000:
                for k in [k for k, v in self.hits.items() if not v or t - v[-1] >= 60]:
                    del self.hits[k]
            return True


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JoinIn(_Body):
    display_name: str = Field(max_length=40)
    handle: str = Field(max_length=254)
    age_ok: bool
    rules_ok: bool


class QueueIn(_Body):
    action: Literal["join", "leave"]


class OptIn(_Body):
    opted_out: bool


def _me_payload(r: dict[str, Any], email: str | None, caller_id_source: str) -> dict[str, Any]:
    """Shape ch_web_me for the site. Only fields about the caller; never another user's id or handle."""
    q_status, pos = r.get("queue_status"), r.get("queue_position")
    eta = None
    if q_status == "waiting" and pos:
        lines = max(int(r.get("lines_active") or 1), 1)
        lo, hi = eta_range(int(pos), float(r.get("avg_cycle_s") or 0) / lines, float(r.get("remaining_s") or 0))
        eta = {"lo_min": lo, "hi_min": hi}
    return {
        "registered": True,
        "email": email,
        "display_name": r.get("display_name"),
        "handle": r.get("handle"),
        "points": r.get("points", 0),
        "points_today": r.get("points_today", 0),
        "valid_reps": r.get("valid_reps", 0),
        "rank": r.get("rank"),
        "total_users": r.get("total_users", 0),
        "calls_today": r.get("calls_today", 0),
        "calls_left": r.get("calls_left", 0),
        "daily_call_cap": r.get("daily_call_cap"),
        "streak": r.get("streak", 0),
        "avatar_level": r.get("avatar_level", 1),
        "opted_out": bool(r.get("opted_out")),
        "banned": bool(r.get("banned")),
        "queue": {"status": q_status, "position": pos, "eta": eta},
        "claim": r.get("claim"),
        "in_call": bool(r.get("in_call")),
        # ch_call_start only accepts walk-ins when the caller is identified by handle (C2 chert_meta).
        "line_open": bool(r.get("line_open")) and caller_id_source == "chert_meta",
        "brodie_number": r.get("brodie_number"),
        "started": bool(r.get("started")),
        "frozen": bool(r.get("frozen")),
    }


def create_router(get_store: Callable[[], Store], clock: Callable[[], datetime], *, enabled: bool,
                  verifier: JwtVerifier, caller_id_source: str,
                  ip_per_min: int | None = None, user_per_min: int | None = None) -> APIRouter:
    router = APIRouter(prefix="/web")
    ip_limiter = _Limiter(ip_per_min or int(os.environ.get("WEB_RATE_PER_IP_MIN", "6000")))
    user_limiter = _Limiter(user_per_min or int(os.environ.get("WEB_RATE_PER_USER_MIN", "120")))
    if enabled and not verifier.configured:
        logger.warning("web join enabled but no SUPABASE_JWT_SECRET / SUPABASE_URL: /web/* will return 503")

    def rpc(fn: str, args: dict) -> Any:
        try:
            return get_store().rpc(fn, args)
        except StoreError as e:
            logger.error("store error: %s", e)
            raise HTTPException(503, "store unavailable") from e

    def caller(request: Request, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        if not enabled:
            raise HTTPException(404, "web join disabled")
        if not ip_limiter.check(request.client.host if request.client else "?"):
            raise HTTPException(429, "rate limited")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(401, "missing bearer token", headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = verifier.verify(token.strip())
        except AuthError as e:
            logger.info("web auth rejected: %s", e)
            raise HTTPException(401, "invalid token", headers={"WWW-Authenticate": "Bearer"}) from None
        except AuthUnavailable as e:
            logger.error("web auth unavailable: %s", e)
            raise HTTPException(503, "auth unavailable") from None
        if not user_limiter.check(claims["sub"]):
            raise HTTPException(429, "rate limited")
        user = rpc("ch_user_by_auth", {"p_auth_user_id": claims["sub"]})
        email = claims.get("email")
        return {"auth_id": claims["sub"], "email": email.lower() if isinstance(email, str) else None,
                "user_id": user.get("user_id")}

    def me_for(who: dict[str, Any]) -> dict[str, Any]:
        if not who["user_id"]:
            return {"registered": False, "email": who["email"]}
        r = rpc("ch_web_me", {"p_user_id": who["user_id"], "p_now": clock()})
        if not r.get("user_id"):
            return {"registered": False, "email": who["email"]}
        return _me_payload(r, who["email"], caller_id_source)

    def registered(who: dict[str, Any]) -> str:
        if not who["user_id"]:
            raise HTTPException(409, "not registered")
        return who["user_id"]

    @router.get("/me")
    def me(who: dict = Depends(caller)) -> dict:
        out = me_for(who)
        out["server_time"] = clock().isoformat()
        return out

    @router.post("/join")
    def join(body: JoinIn, who: dict = Depends(caller)) -> dict:
        if not (body.age_ok and body.rules_ok):
            return {"ok": False, "reason": "confirm_required", "me": me_for(who)}
        name = body.display_name.strip()
        if not validate_display_name(name)[0]:
            return {"ok": False, "reason": "bad_name", "me": me_for(who)}
        handle = normalize_handle(body.handle)
        if handle is None:
            return {"ok": False, "reason": "bad_handle", "me": me_for(who)}
        r = rpc("ch_web_join", {"p_auth_user_id": who["auth_id"], "p_display_name": name, "p_handle": handle,
                                "p_now": clock()})
        if r.get("ok"):
            who = {**who, "user_id": r["user_id"]}
        return {"ok": bool(r.get("ok")), "reason": r.get("reason"), "me": me_for(who)}

    @router.post("/queue")
    def queue(body: QueueIn, who: dict = Depends(caller)) -> dict:
        uid = registered(who)
        if body.action == "join":
            r = rpc("ch_queue_join", {"p_user_id": uid, "p_now": clock()})
            out = {"ok": bool(r.get("ok")), "reason": r.get("reason")}
        else:
            r = rpc("ch_queue_leave", {"p_user_id": uid, "p_reason": "left", "p_now": clock()})
            out = {"ok": bool(r.get("ok")), "reason": "left" if r.get("was_queued") else "not_queued"}
        out["me"] = me_for(who)
        return out

    @router.post("/opt")
    def opt(body: OptIn, who: dict = Depends(caller)) -> dict:
        uid = registered(who)
        r = rpc("ch_set_opt", {"p_user_id": uid, "p_opted_out": body.opted_out, "p_now": clock()})
        return {"ok": bool(r.get("ok")), "reason": r.get("reason", "ok"), "me": me_for(who)}

    return router


def web_enabled(provider: str, env: dict[str, str] | None = None) -> bool:
    """/web/* is live in web_only mode, or anywhere when WEB_JOIN_ENABLED=1 (staging / dual-channel)."""
    env = os.environ if env is None else env
    return provider == "web_only" or env.get("WEB_JOIN_ENABLED") == "1"


__all__ = ["JwtVerifier", "AuthError", "AuthUnavailable", "create_router", "web_enabled"]
