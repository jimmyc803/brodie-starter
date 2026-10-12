"""Post-call processing (SPEC §4 step 8). Intents are written by the DB function ch_postcall.

Outbox/StoreOutbox remain the injectable interface for non-transactional senders (jobs, commands)."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Protocol

from challenge.store import Store

logger = logging.getLogger("challenge.dispatcher")


class Outbox(Protocol):
    def enqueue(self, *, user_id: str | None = None, handle: str | None = None, template: str,
                ctx: dict[str, Any], dedupe_key: str, proactive: bool) -> dict: ...


class StoreOutbox:
    """Outbox backed by ch_outbox_enqueue. Body stays null: the sender renders template+ctx (C7).
    ctx['media_url'] (if present) is also sent as the row's media_url. Quiet hours and the
    proactive/STOP gate are enforced by the sender, so `proactive` is advisory here."""

    def __init__(self, store: Store, clock: Callable[[], datetime]):
        self.store = store
        self.clock = clock

    def enqueue(self, *, user_id: str | None = None, handle: str | None = None, template: str,
                ctx: dict[str, Any], dedupe_key: str, proactive: bool) -> dict:
        if not user_id and not handle:
            raise ValueError("user_id or handle required")
        return self.store.rpc("ch_outbox_enqueue", {
            "p_handle": handle, "p_user_id": user_id, "p_template": template, "p_body": None,
            "p_media_url": ctx.get("media_url"), "p_dedupe_key": dedupe_key, "p_not_before": None,
            "p_now": self.clock(), "p_ctx": ctx})


def process(call_id: str, *, store: Store, clock: Callable[[], datetime], card_delivery: str) -> dict:
    """Post-call work (SPEC §4 step 8) runs entirely inside ch_postcall: one transaction writes the
    post_call intent, the unthrottled rank_drop intents and calls.postcall_done_at. Idempotent. If it
    fails nothing is written and ch_postcall_pending lets the jobs loop retry it."""
    return store.rpc("ch_postcall", {"p_call_id": call_id, "p_now": clock(), "p_card_delivery": card_delivery})
