"""Dispatcher HTTP API (CONTRACTS C4): worker-facing endpoints + health.

Event idempotency: `idem_key` is recorded in ch_event_log by ch_event_run in the same transaction as the
effect; a duplicate key returns the stored result without re-running it (the underlying RPCs are
also idempotent per call_id). Post-call intents are written atomically by ch_postcall.
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from challenge.config import Config
from challenge.dispatcher import admin, postcall, web
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.postcall import Outbox, StoreOutbox
from challenge.dispatcher.jobs import Jobs, run_loop
from challenge.dispatcher.powerhour import require_secret
from challenge.dispatcher.ratelimit import DEFAULT_PER_MIN, RateLimiter, rate_limit
from challenge.messaging.outbox import Outbox as SendOutbox
from challenge.messaging.providers import provider_from_env
from challenge.scoring import eta_range, format_eta
from challenge.store import Json, Store, StoreError, store_from_env

logger = logging.getLogger("challenge.dispatcher")


class StartIn(BaseModel):
    call_id: str
    line_id: str
    handle: str | None = None


HEARTBEAT_DETAIL_MAX = 2048  # bytes of JSON


class HeartbeatIn(BaseModel):
    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    scope: Literal["supervisor", "job"] = "supervisor"
    healthy: bool = True
    detail: dict[str, Any] = {}


class EventIn(BaseModel):
    kind: Literal["call_started", "call_ended", "reps_committed"]
    call_id: str
    idem_key: str
    at: datetime | None = None
    payload: dict[str, Any] = {}


def create_app(store: Store | None = None, outbox: Outbox | None = None,
               clock: Callable[[], datetime] | None = None, flags: Flags | None = None,
               token: str | None = None, rate_per_min: int | None = None,
               jobs: Jobs | None = None,
               web_verifier: web.JwtVerifier | None = None, web_join: bool | None = None) -> FastAPI:
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

    live_cfg: list[Config] = []

    def call_config() -> dict:
        """The numbers the worker's call timeline and judge use (competition_config, cached 15 s; defaults on a DB error)."""
        if not live_cfg:
            live_cfg.append(Config(get_store()))
        c = live_cfg[0]
        return {"call_count_s": c.get("call_count_s"), "call_reveal_s": c.get("call_reveal_s"),
                "judge_thresholds": c.get("judge_thresholds")}

    def power_hour_active(now: datetime) -> bool | None:
        try:
            ph = get_store().rpc("ch_power_hour", {"p_now": now})
        except StoreError as e:  # the call goes on; only the cue is lost
            logger.error("power hour lookup failed: %s", e)
            return None
        return bool(isinstance(ph, dict) and ph.get("active"))

    @app.post("/calls/start", dependencies=[Depends(auth)])
    def calls_start(body: StartIn) -> dict:
        """C4 + optional fields on accept (task 30, noted in PLAN): power_hour_active (bool, null when unknown) for the
        in-call power hour cue, config {call_count_s, call_reveal_s, judge_thresholds} for the worker's timeline."""
        now = clock()
        r = rpc("ch_call_start", {"p_call_id": body.call_id, "p_line_id": body.line_id,
                                  "p_handle": body.handle, "p_mode": flags.CALLER_ID_SOURCE, "p_now": now})
        out = {"decision": r["decision"], "user_id": r.get("user_id"), "reason": r["reason"], "cue": r.get("cue")}
        if r["decision"] == "accept":
            out["power_hour_active"] = power_hour_active(now)
            out["config"] = call_config()
        if flags.CALLER_ID_SOURCE == "chert_meta" and out["decision"] == "reject":
            out.update(_call_to_queue(body, out, now))
        return out

    def _call_to_queue(body: StartIn, out: dict, now: datetime) -> dict:
        """Calling a busy line is the same as texting QUEUE: a known caller is put in line and texted
        their spot; an unknown caller is texted how to JOIN. Only possible with caller ID (chert_meta).
        Idempotent per call_id: a replayed start re-joins as 'already' and the text dedupes on call:<id>.
        Best effort: a failure here never changes the start decision the worker already needs."""
        try:
            if out["reason"] == "not_registered" and body.handle:
                get_outbox().enqueue(handle=body.handle, template="not_registered", ctx={},
                                     dedupe_key=f"call:{body.call_id}", proactive=False)
                return {}
            if out["reason"] != "not_your_turn" or not out["user_id"]:
                return {}
            q = get_store().rpc("ch_queue_join", {"p_user_id": out["user_id"], "p_now": now})
            if q["reason"] not in ("ok", "already", "opted_out_ok"):
                return {}
            view = get_store().rpc("ch_queue_view", {"p_now": now})
            ctx = {**q, "eta": format_eta(*eta_range(q["position"] or 1, view["avg_cycle_s"]))}
            get_outbox().enqueue(user_id=out["user_id"], template="call_queued", ctx=ctx,
                                 dedupe_key=f"call:{body.call_id}", proactive=False)
            return {"reason": "queued", "cue": "queued", "position": q["position"]}
        except (StoreError, KeyError, TypeError) as e:
            logger.error("call %s: auto-queue failed: %s", body.call_id, e)
            return {}

    @app.post("/calls/heartbeat", dependencies=[Depends(auth)])
    def calls_heartbeat(body: HeartbeatIn) -> dict:
        """Worker liveness: ch_heartbeat('worker:<line_id>' for the supervisor, 'worker:<line_id>:job' for a job in a
        call) with {detail, healthy}; the aggregate 'worker' row the alerts read is refreshed only by a healthy beat, so
        a wedged job lets it go stale. detail <= 2 KB; line_id must be a line in line_state."""
        if len(json.dumps(body.detail, default=str)) > HEARTBEAT_DETAIL_MAX:
            raise HTTPException(413, "heartbeat detail too large")
        now = clock()
        lines = {x["line_id"] for x in rpc("ch_queue_view", {"p_now": now}).get("lines", [])}
        if body.line_id not in lines:
            raise HTTPException(404, "unknown line")
        detail = {**body.detail, "line_id": body.line_id, "scope": body.scope, "healthy": body.healthy}
        comps = [f"worker:{body.line_id}" + (":job" if body.scope == "job" else "")]
        if body.healthy:
            comps.append("worker")
        else:
            logger.error("worker heartbeat unhealthy: line %s scope %s detail %s", body.line_id, body.scope, body.detail)
        for comp in comps:
            rpc("ch_heartbeat", {"p_component": comp, "p_detail": detail, "p_now": now})
        return {"ok": True, "healthy": body.healthy}

    @app.post("/calls/event", dependencies=[Depends(auth)])
    def calls_event(ev: EventIn) -> dict:
        logger.info("event %s call=%s idem=%s", ev.kind, ev.call_id, ev.idem_key)
        if ev.idem_key != f"{ev.call_id}:{ev.kind}":  # ch_event_run matches on idem_key alone: bind it to this call and kind
            raise HTTPException(400, "idem_key must be <call_id>:<kind>")
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
            if r.get("points") is not None:  # ch_commit_reps' authoritative points (C7.v); rank has no RPC: not forwarded
                resp["points"] = r["points"]
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
    app.include_router(web.create_router(
        get_store, clock, enabled=web.web_enabled(flags.MESSAGING_PROVIDER) if web_join is None else web_join,
        verifier=web_verifier or web.JwtVerifier.from_env(), caller_id_source=flags.CALLER_ID_SOURCE))
    return app


app = create_app()
