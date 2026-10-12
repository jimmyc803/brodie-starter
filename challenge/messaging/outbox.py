"""Leased delivery with a process-local token bucket and send-time policy checks."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Callable

from challenge.config import Config
from challenge.messaging.providers import MessagingProvider
from challenge.messaging.templates import PROACTIVE_TEMPLATES, render
from challenge.store import Store
from challenge.timeutil import next_quiet_end


class Outbox:
    def __init__(self, store: Store, cfg: Config, provider: MessagingProvider,
                 clock: Callable[[], datetime] | None = None):
        self.store, self.cfg, self.provider = store, cfg, provider
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._tokens = float(self._rate())
        self._at: datetime | None = None
        self._lock = Lock()

    def _rate(self) -> int:
        return max(0, int(os.environ.get("OUTBOUND_RATE_PER_MIN") or
                          self.cfg.get("outbound_rate_per_min")))

    def enqueue(self, *, user_id: str | None = None, handle: str | None = None,
                template: str, ctx: dict[str, Any], dedupe_key: str, proactive: bool) -> dict:
        now = self.clock()
        not_before = now
        if proactive and template not in ("youre_up", "post_call"):
            not_before = next_quiet_end(now, self.cfg.get("quiet_hours"))
        return self.store.rpc("ch_outbox_enqueue", {
            "p_handle": handle, "p_user_id": user_id, "p_template": template,
            "p_body": None, "p_media_url": ctx.get("media_url"), "p_dedupe_key": dedupe_key,
            "p_not_before": not_before, "p_now": now, "p_ctx": {**ctx, "_proactive": proactive},
        })

    def _mark(self, row: dict, status: str, *, provider_id: str | None = None,
              error: str | None = None, retry_at: datetime | None = None) -> None:
        self.store.rpc("ch_outbox_mark", {
            "p_id": row["id"], "p_status": status, "p_provider_message_id": provider_id,
            "p_error": error, "p_retry_at": retry_at, "p_attempt": row["attempts"],
        })

    def run_once(self, now: datetime) -> int:
        with self._lock:
            rate = self._rate()
            elapsed = max(0.0, (now - self._at).total_seconds()) if self._at else 0.0
            self._tokens = min(float(rate), self._tokens + elapsed * rate / 60)
            self._at = max(now, self._at) if self._at else now
            sent = 0
            for _ in range(int(self._tokens)):
                claim_at = max(now, self.clock())
                rows = self.store.rpc("ch_outbox_claim", {"p_limit": 1, "p_now": claim_at})
                if not rows:
                    break
                row = rows[0]
                self._tokens -= 1
                if row["attempts"] > 5:
                    self._mark(row, "failed", error="max_attempts")
                    continue
                ctx = row.get("ctx") or {}
                proactive = ctx.get("_proactive", row["template"] in PROACTIVE_TEMPLATES)
                if proactive:
                    user = self.store.rpc("ch_user_by_handle", {"p_handle": row["handle"]})
                    if user.get("opted_out") or user.get("banned"):
                        self._mark(row, "suppressed", error="opted_out_or_banned")
                        continue
                    if row["template"] not in ("youre_up", "post_call"):
                        release = next_quiet_end(claim_at, self.cfg.get("quiet_hours"))
                        if release > claim_at:
                            self._mark(row, "queued", retry_at=release)
                            continue
                try:
                    body = row["body"]
                    if body is None:
                        body = render(row["template"], ctx, self.cfg.get("swearing"))
                    if row.get("media_url") and os.environ.get("CARD_DELIVERY", "link") == "attachment":
                        provider_id = self.provider.send_image(row["handle"], row["media_url"], body)
                    else:
                        provider_id = self.provider.send_text(row["handle"], body)
                except Exception as exc:
                    self._mark(row, "failed" if row["attempts"] >= 5 else "queued",
                               error=type(exc).__name__,
                               retry_at=claim_at + timedelta(seconds=2 ** row["attempts"]))
                    continue
                self._mark(row, "sent", provider_id=provider_id)
                sent += 1
            return sent
