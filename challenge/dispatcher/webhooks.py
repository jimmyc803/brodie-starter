"""Verified inbound messaging routes with durable provider-message deduplication."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from challenge.config import Config
from challenge.dispatcher.postcall import Outbox
from challenge.messaging.handler import handle_inbound
from challenge.messaging.providers import InvalidHandle, provider_from_env
from challenge.store import Store

logger = logging.getLogger(__name__)


def create_router(get_store: Callable[[], Store], get_outbox: Callable[[], Outbox],
                  clock: Callable[[], datetime]) -> APIRouter:
    router = APIRouter()

    async def receive(request: Request, name: str) -> dict:
        if request.app.state.flags.MESSAGING_PROVIDER != name:
            raise HTTPException(404, "provider disabled")
        provider = provider_from_env()
        if provider.name != name:
            raise HTTPException(404, "provider disabled")
        body = await request.body()
        headers = dict(request.headers)
        if not provider.verify(headers, body):
            raise HTTPException(401, "invalid signature")
        try:
            messages = provider.parse_inbound(headers, body)
        except InvalidHandle:
            return {"ok": False, "reason": "bad_handle"}
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "invalid inbound payload") from exc

        def process() -> dict:
            store, outbox = get_store(), get_outbox()
            cfg = Config(store)
            count = 0
            for inbound in messages:
                now = clock()
                recorded = store.rpc("ch_inbound_record", {
                    "p_provider_message_id": inbound.provider_message_id,
                    "p_handle": inbound.handle, "p_body": inbound.body, "p_now": now,
                })
                if recorded["duplicate"] and store.rpc("ch_inbound_is_done", {"p_id": recorded["id"]}):
                    continue
                # Re-handled when an earlier attempt never finished; replies dedupe on the outbox key.
                handle_inbound(store, cfg, outbox, inbound, now)
                store.rpc("ch_inbound_done", {"p_id": recorded["id"], "p_now": now})
                count += 1
            return {"ok": True, "handled": count}

        try:
            return await run_in_threadpool(process)
        except Exception as exc:
            logger.error("inbound processing failed: %s", type(exc).__name__)
            raise HTTPException(503, "inbound processing failed") from None

    @router.post("/webhooks/chert")
    async def chert(request: Request) -> dict:
        return await receive(request, "chert")

    @router.post("/webhooks/mock")
    async def mock(request: Request) -> dict:
        return await receive(request, "mock")

    return router
