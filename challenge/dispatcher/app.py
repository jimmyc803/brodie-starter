"""Dispatcher HTTP API (CONTRACTS C4): worker-facing endpoints + health.

Event idempotency: `idem_key` is accepted and logged, but dedupe is enforced by the DB, which is
the source of truth: ch_call_start/ch_call_end/ch_commit_reps are idempotent per call_id, so a
duplicate event has a single effect; post-call texts are dedupe-keyed in the outbox.
"""
from __future__ import annotations

import hmac
import logging
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from challenge.config import Config
from challenge.dispatcher import postcall
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.postcall import Outbox, StoreOutbox
from challenge.store import Store, StoreError, store_from_env

logger = logging.getLogger("challenge.dispatcher")


class StartIn(BaseModel):
    call_id: str
    line_id: str
    handle: str | None = None


class EventIn(BaseModel):
    kind: Literal["call_started", "call_ended", "reps_committed"]
    call_id: str
    idem_key: str
    at: datetime | None = None
    payload: dict[str, Any] = {}


class _RateLimiter:
    def __init__(self, per_min: int, now: Callable[[], float] = time.monotonic):
        self.per_min, self.now, self.hits = per_min, now, defaultdict(deque)

    def check(self, key: str) -> bool:
        t, q = self.now(), self.hits[key]
        while q and t - q[0] >= 60:
            q.popleft()
        if len(q) >= self.per_min:
            return False
        q.append(t)
        return True


def create_app(store: Store | None = None, outbox: Outbox | None = None,
               clock: Callable[[], datetime] | None = None, flags: Flags | None = None,
               token: str | None = None, rate_per_min: int | None = None) -> FastAPI:
    clock = clock or (lambda: datetime.now(timezone.utc))
    flags = flags or Flags.from_env()
    flags.log_startup()
    token = token if token is not None else os.environ.get("DISPATCHER_TOKEN", "")
    if not token:
        logger.warning("DISPATCHER_TOKEN unset: all worker endpoints will reject requests")
    limiter = _RateLimiter(rate_per_min or int(os.environ.get("DISPATCHER_RATE_PER_MIN", "600")))
    app = FastAPI(title="brodie-dispatcher")
    app.state.flags = flags
    app.state.store = store
    app.state.outbox = outbox

    def get_store() -> Store:
        if app.state.store is None:  # lazy so importing the module needs no env
            app.state.store = store_from_env()
        return app.state.store

    def get_outbox() -> Outbox:
        if app.state.outbox is None:
            app.state.outbox = StoreOutbox(get_store(), clock)
        return app.state.outbox

    def auth(request: Request, x_brodie_token: str | None = Header(default=None)) -> None:
        if not limiter.check(request.client.host if request.client else "?"):
            raise HTTPException(429, "rate limited")
        if not token or x_brodie_token is None or not hmac.compare_digest(
                x_brodie_token.encode(), token.encode()):
            raise HTTPException(401, "bad token")

    def rpc(fn: str, args: dict) -> Any:
        try:
            return get_store().rpc(fn, args)
        except StoreError as e:
            logger.error("store error: %s", e)
            raise HTTPException(503, "store unavailable") from e

    @app.post("/calls/start", dependencies=[Depends(auth)])
    def calls_start(body: StartIn) -> dict:
        r = rpc("ch_call_start", {"p_call_id": body.call_id, "p_line_id": body.line_id,
                                  "p_handle": body.handle, "p_mode": flags.CALLER_ID_SOURCE, "p_now": clock()})
        return {"decision": r["decision"], "user_id": r.get("user_id"), "reason": r["reason"], "cue": r.get("cue")}

    @app.post("/calls/event", dependencies=[Depends(auth)])
    def calls_event(ev: EventIn) -> dict:
        now, p = clock(), ev.payload
        logger.info("event %s call=%s idem=%s", ev.kind, ev.call_id, ev.idem_key)
        if ev.kind == "call_started":
            return {"ok": True}  # state change already done by /calls/start
        if ev.kind == "call_ended":
            r = rpc("ch_call_end", {"p_call_id": ev.call_id, "p_ended_at": p.get("ended_at"),
                                    "p_count_end_at": p.get("count_end_at"), "p_rep_count": p.get("rep_count"),
                                    "p_now": now})
            return {"ok": bool(r.get("ok")), "reason": r.get("reason")}
        r = rpc("ch_commit_reps", {"p_call_id": ev.call_id, "p_payload": p, "p_now": now})
        if not r.get("ok"):
            return {"ok": False, "reason": r.get("reason")}
        try:
            post = postcall.process(ev.call_id, store=get_store(), outbox=get_outbox(), config=Config(get_store()),
                                    clock=clock, card_delivery=flags.CARD_DELIVERY, commit=r,
                                    reps=p.get("reps") or [], mode=flags.CALLER_ID_SOURCE)
        except Exception:  # commit is durable; the worker must not retry the commit because texting failed
            logger.exception("postcall failed for %s", ev.call_id)
            return {"ok": True, "already": bool(r.get("already")), "postcall": "failed"}
        return {"ok": True, "already": bool(r.get("already")), "postcall": post}

    @app.get("/health")
    def health() -> dict:
        db, lines = False, []
        try:
            view = get_store().rpc("ch_queue_view", {"p_now": clock()})
            db, lines = True, [{"line_id": x["line_id"], "state": x["state"]} for x in view.get("lines", [])]
        except Exception as e:
            logger.error("health db check failed: %s", e)
        return {"ok": db, "db": db, "provider": flags.MESSAGING_PROVIDER, "flags": flags.public(),
                "fallbacks": flags.fallbacks(), "line_states": lines}

    return app


app = create_app()
