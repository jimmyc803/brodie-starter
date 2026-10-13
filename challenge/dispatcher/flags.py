"""Env flags (CONTRACTS C4), read once at startup, logged, echoed in /health."""
from __future__ import annotations

import logging
import os
from typing import Literal

from pydantic import BaseModel, Field

logger = logging.getLogger("challenge.dispatcher")

# flag -> (primary value, human description of the fallback behaviour)
_FALLBACKS = {
    "CALLER_ID_SOURCE": ("chert_meta", "claim-window attribution; walk-ins are rejected"),
    "MESSAGING_PROVIDER": ("chert", "no real iMessage delivery"),
    "HANGUP_MODE": ("leave_room", "hangup not verified; relies on time's-up cue"),
    "REVEAL_MODE": ("video", "audio-only reveal"),
    "CARD_DELIVERY": ("attachment", "result card sent as a link"),
}


class Flags(BaseModel):
    CALLER_ID_SOURCE: Literal["chert_meta", "claim_window"] = "claim_window"
    MESSAGING_PROVIDER: Literal["chert", "web_only", "mock"] = "mock"
    HANGUP_MODE: Literal["leave_room", "chert_api", "unverified", "delete_room"] = "unverified"
    REVEAL_MODE: Literal["video", "audio_only"] = "audio_only"
    CARD_DELIVERY: Literal["attachment", "link"] = "link"
    LINE_OFFLINE_GAP_S: int | None = Field(default=None, ge=0)
    OUTBOUND_RATE_PER_MIN: int | None = Field(default=None, ge=1)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Flags":
        env = os.environ if env is None else env
        raw = {k: v.strip() for k in cls.model_fields if (v := env.get(k)) is not None and v.strip() != ""}
        return cls(**raw)

    def public(self) -> dict[str, str]:
        """The five mode flags echoed by /health."""
        return {k: getattr(self, k) for k in _FALLBACKS}

    def fallbacks(self) -> dict[str, str]:
        return {k: why for k, (primary, why) in _FALLBACKS.items() if getattr(self, k) != primary}

    def log_startup(self) -> None:
        for k, v in self.model_dump().items():
            logger.info("flag %s=%s", k, v)
            print(f"flag {k}={v}", flush=True)
        for k, why in self.fallbacks().items():
            logger.warning("FALLBACK MODE %s=%s: %s", k, getattr(self, k), why)
