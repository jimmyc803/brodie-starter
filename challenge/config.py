"""Live competition config with defaults. Values come from rpc ch_config_get, cached for ttl_s."""
from __future__ import annotations

import time
from typing import Any, Callable

from challenge.store import Store, StoreError

DEFAULTS: dict[str, Any] = {
    "window_start": "2026-10-12T20:00:00-04:00",
    "window_end": "2026-10-18T23:59:59-04:00",
    "call_count_s": 180,
    "call_reveal_s": 15,
    "daily_call_cap": 5,
    "claim_window_s": 90,
    "line_offline_gap_s": 180,
    "min_counted_call_s": 30,
    "in_call_timeout_extra_s": 60,
    "power_hour_window": [12, 22],
    "power_multiplier": 2,
    "rank_drop_min": 2,
    "rank_drop_throttle_h": 3,
    "quiet_hours": [23, 9],
    "recap_hour": 10,
    "streak_risk_hour": 20,
    "avatar_level_thresholds": [0, 25, 60, 120, 200, 300, 450, 650, 900, 1200],
    "judge_thresholds": {
        "min_conf": 0.5, "frame_conf_frac": 0.9, "knee_min_deg": 160, "knee_floor_margin": 0.04,
        "hip_line_max_dev_deg": 15, "depth_elbow_max_deg": 90, "depth_margin": 0.05, "lockout_min_deg": 160,
        "min_rep_s": 0.8, "max_cadence_rpm": 60,
        "classifier_veto": ["pushups - shallow", "pushups - insufficient", "pushups - elevated hips"],
        "classifier_veto_substrings": ["knee", "sag"], "liveness_window_s": [45, 150],
        "liveness_timeout_s": 4, "cue_min_gap_s": 4,
    },
    "registration_open": True,
    "competition_frozen": False,
    "swearing": False,
    "site_url": "https://brodie-pushups.vercel.app",
    "brodie_number": None,
    "team_alert_handles": [],
    "challenge_coach_id": None,
    "outbound_rate_per_min": 20,
}


class Config:
    def __init__(self, store: Store, ttl_s: float = 15, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.ttl_s = ttl_s
        self._clock = clock
        self._data: dict[str, Any] = {}
        self._at: float | None = None

    def _refresh(self) -> None:
        now = self._clock()
        if self._at is not None and now - self._at < self.ttl_s:
            return
        try:
            got = self.store.rpc("ch_config_get", {})
            if isinstance(got, dict):
                self._data = got
        except StoreError:
            pass  # keep the last good snapshot (or DEFAULTS); retry after ttl
        self._at = now

    def all(self) -> dict[str, Any]:
        self._refresh()
        return {**DEFAULTS, **self._data}

    def get(self, key: str) -> Any:
        self._refresh()
        if key in self._data:
            return self._data[key]
        return DEFAULTS[key]
