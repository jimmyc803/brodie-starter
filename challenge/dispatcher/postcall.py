"""Post-call processing (SPEC §4 step 8): result text + rank-drop texts via an injected Outbox."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Protocol

from challenge.config import Config
from challenge.store import Store, StoreError

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


def process(call_id: str, *, store: Store, outbox: Outbox, config: Config, clock: Callable[[], datetime],
            card_delivery: str, commit: dict, reps: list[dict], mode: str) -> dict:
    """Run after ch_commit_reps succeeded. Safe to repeat: post_call is dedupe-keyed; rank deltas
    are consumed by the DB (rank_state), so they run only on the first (not `already`) commit."""
    now = clock()
    # Idempotent replay of ch_call_start returns the stored decision (and user_id) for this call.
    started = store.rpc("ch_call_start", {"p_call_id": call_id, "p_line_id": None, "p_handle": None,
                                          "p_mode": mode, "p_now": now})
    user_id = (started or {}).get("user_id")
    if not user_id:
        return {"post_call": False, "rank_drops": 0}
    st = store.rpc("ch_user_status", {"p_user_id": user_id, "p_now": now}) or {}
    site = str(config.get("site_url")).rstrip("/")
    url = f"{site}/r/{call_id}"
    valid = int(commit.get("valid_reps") or 0)
    ctx: dict[str, Any] = {
        "valid_reps": valid, "rejected_reps": max(len(reps) - valid, 0),
        "points_earned": commit.get("points") or 0, "points": st.get("points", 0),
        "rank": st.get("rank") if st.get("rank") is not None else "-", "streak": st.get("streak", 0),
        "result_url": url, "call_id": call_id}
    if card_delivery == "attachment":
        ctx["media_url"] = f"{url}/card.png"
    outbox.enqueue(user_id=user_id, template="post_call", ctx=ctx, dedupe_key=f"post_call:{call_id}", proactive=True)
    drops = 0
    if not commit.get("already"):
        for d in store.rpc("ch_rank_deltas", {"p_now": now}) or []:
            if d.get("throttled"):
                continue
            gap = (d.get("ahead_points") or 0) - (d.get("points") or 0)
            outbox.enqueue(user_id=d["user_id"], template="rank_drop", proactive=True,
                           dedupe_key=f"rank_drop:{call_id}:{d['user_id']}",
                           ctx={"old_rank": d["old_rank"], "rank": d["new_rank"], "next_rank": d["new_rank"] - 1,
                                "points_gap": max(gap, 0), "points": d.get("points"),
                                "ahead_display_name": d.get("ahead_display_name")})
            drops += 1
    return {"post_call": True, "rank_drops": drops}
