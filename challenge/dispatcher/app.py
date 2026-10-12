"""Dispatcher HTTP API (CONTRACTS C4): worker-facing endpoints + health.

Event idempotency: `idem_key` is recorded in ch_event_log by ch_event_run in the same transaction as the
effect; a duplicate key returns the stored result without re-running it (the underlying RPCs are
also idempotent per call_id). Post-call intents are written atomically by ch_postcall.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from challenge.config import Config
from challenge.dispatcher import admin, postcall
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.postcall import Outbox, StoreOutbox
from challenge.dispatcher.jobs import Jobs, run_loop
from challenge.dispatcher.powerhour import require_secret
from challenge.dispatcher.ratelimit import DEFAULT_PER_MIN, RateLimiter, rate_limit
from challenge.messaging.outbox import Outbox as SendOutbox
from challenge.messaging.providers import provider_from_env
from challenge.store import Json, Store, StoreError, store_from_env

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


def create_app(store: Store | None = None, outbox: Outbox | None = None,
               clock: Callable[[], datetime] | None = None, flags: Flags | None = None,
               token: str | None = None, rate_per_min: int | None = None,
               jobs: Jobs | None = None) -> FastAPI:
    require_secret()
    clock = clock or (lambda: datetime.now(timezone.utc))
    flags = flags or Flags.from_env()
    flags.log_startup()
    token = token if token is not None else os.environ.get("DISPATCHER_TOKEN", "")
    if not token:
        logger.warning("DISPATCHER_TOKEN unset: all worker endpoints will reject requests")
    jobs_enabled = os.environ.get("JOBS_ENABLED", "1") != "0"

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI):
        task = None
        if jobs_enabled:  # JOBS_ENABLED=0 disables the background loop (tests)
            runner = jobs
            if runner is None:
                st = get_store()
                runner = Jobs(st, Config(st), SendOutbox(st, Config(st), provider_from_env(), clock), clock)
            app.state.jobs = runner
            task = asyncio.create_task(run_loop(runner))
            logger.info("jobs loop started")
        else:
            logger.warning("JOBS_ENABLED=0: jobs loop disabled")
        try:
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    app = FastAPI(title="brodie-dispatcher", lifespan=lifespan)
    app.state.rate_limiter = RateLimiter(
        rate_per_min or int(os.environ.get("DISPATCHER_RATE_PER_MIN", str(DEFAULT_PER_MIN))))
    app.state.token = token
    app.state.clock = clock
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

    app.state.get_store = get_store

    def auth(request: Request, x_brodie_token: str | None = Header(default=None),
             _: None = Depends(rate_limit("worker"))) -> None:
        if not token or x_brodie_token is None or not hmac.compare_digest(
                x_brodie_token.encode(), token.encode()):
            raise HTTPException(401, "bad token")

    def rpc(fn: str, args: dict) -> Any:
        try:
            return get_store().rpc(fn, args)
        except StoreError as e:
            logger.error("store error: %s", e)
            raise HTTPException(503, "store unavailable") from e

    if flags.LINE_OFFLINE_GAP_S is not None:  # C4: env overrides competition_config (audited write)
        want = flags.LINE_OFFLINE_GAP_S
        if get_store().rpc("ch_config_get", {}).get("line_offline_gap_s") != want:
            get_store().rpc("ch_config_set", {"p_key": "line_offline_gap_s", "p_value": Json(want),
                                              "p_actor": "dispatcher", "p_reason": "LINE_OFFLINE_GAP_S env flag"})
            logger.warning("line_offline_gap_s set to %s from LINE_OFFLINE_GAP_S", want)

    @app.post("/calls/start", dependencies=[Depends(auth)])
    def calls_start(body: StartIn) -> dict:
        r = rpc("ch_call_start", {"p_call_id": body.call_id, "p_line_id": body.line_id,
                                  "p_handle": body.handle, "p_mode": flags.CALLER_ID_SOURCE, "p_now": clock()})
        return {"decision": r["decision"], "user_id": r.get("user_id"), "reason": r["reason"], "cue": r.get("cue")}

    @app.post("/calls/event", dependencies=[Depends(auth)])
    def calls_event(ev: EventIn) -> dict:
        logger.info("event %s call=%s idem=%s", ev.kind, ev.call_id, ev.idem_key)
        # Effect + ch_event_log row in one DB transaction; a duplicate idem_key returns the stored result.
        out = rpc("ch_event_run", {"p_idem_key": ev.idem_key, "p_call_id": ev.call_id, "p_kind": ev.kind,
                                   "p_payload": ev.payload, "p_now": clock()})
        r = out["result"]
        resp: dict[str, Any] = {"ok": bool(r.get("ok")), "duplicate": bool(out["duplicate"])}
        if not r.get("ok"):
            resp["reason"] = r.get("reason")
            return resp
        if ev.kind == "call_ended":
            resp["counted_toward_cap"] = r.get("counted_toward_cap")
        if ev.kind == "reps_committed":
            resp["already"] = bool(r.get("already"))
            try:  # idempotent; also retried on duplicates so an earlier failure heals
                resp["postcall"] = postcall.process(ev.call_id, store=get_store(), clock=clock,
                                                    card_delivery=flags.CARD_DELIVERY)
            except Exception:  # commit is durable; ch_postcall_pending lets the jobs loop recover this
                logger.exception("postcall failed for %s; left pending", ev.call_id)
                resp["postcall"] = "pending"
        return resp

    @app.get("/health", dependencies=[Depends(rate_limit("public"))])
    def health() -> dict:
        db, lines = False, []
        try:
            view = get_store().rpc("ch_queue_view", {"p_now": clock()})
            db, lines = True, [{"line_id": x["line_id"], "state": x["state"]} for x in view.get("lines", [])]
        except Exception as e:
            logger.error("health db check failed: %s", e)
        return {"ok": db, "db": db, "provider": flags.MESSAGING_PROVIDER, "flags": flags.public(),
                "fallbacks": flags.fallbacks(), "line_states": lines}

    app.include_router(__import__("challenge.dispatcher.webhooks", fromlist=["create_router"]).create_router(get_store, get_outbox, clock))
    app.include_router(admin.router)
    app.include_router(admin.internal_router)
    return app


app = create_app()
