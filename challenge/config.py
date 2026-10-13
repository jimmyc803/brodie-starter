"""Live competition config with defaults. Values come from rpc ch_config_get, cached for ttl_s."""
from __future__ import annotations

import time
from typing import Any, Callable

from challenge.store import Store, StoreError

DEFAULTS: dict[str, Any] = {
    "window_start": "2026-10-12T20:00:00-04:00",
    "window_end": "2026-10-20T23:59:59-04:00",
    "call_count_s": 180,
    "call_reveal_s": 15,
    "daily_call_cap": 5,
    "claim_window_s": 90,
    "claim_grace_s": 10,      # ch_call_start still accepts the claim holder this long after claimed_until
    "worker_stale_s": 120,    # ch_tick holds pops onto a line whose worker heartbeat is older (0 = off)
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
    "judge_thresholds": {   # j4 (challenge/judge/gates.py DEFAULT_THRESHOLDS, docs/challenge/CALIBRATION.md)
        "min_conf": 0.4, "leg_min_conf": 0.7, "frame_conf_frac": 0.6, "knee_min_deg": 145, "knee_floor_margin": 0.1,
        "hip_knee_min_deg": 120,
        "hip_line_max_dev_deg": 30, "hip_pike_max_dev_deg": 40, "depth_elbow_max_deg": 125, "depth_drop_max": 0.88,
        "lockout_min_deg": 130, "incline_max_deg": 25, "decline_max_deg": 65, "min_rep_s": 0.45, "max_cadence_rpm": 100,
        "classifier_veto": [], "classifier_veto_substrings": [],
        "liveness_enabled": False, "liveness_window_s": [45, 150], "liveness_timeout_s": 4, "cue_min_gap_s": 4,
        "cue_repeat_gap_s": 10,
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
