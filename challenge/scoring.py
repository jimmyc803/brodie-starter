"""Python mirror of the SQL scoring rules (CONTRACTS C2 derived rules), used for tests and previews."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from challenge.timeutil import parse_ts


def rep_points(at, valid: bool, in_challenge: bool, liveness_fail: bool, window_end,
               power_hour: tuple | None, mult: int) -> tuple[bool, int, int, str | None]:
    """-> (valid_final, multiplier, points, extra_reason). Power hour is [start, end): a rep at ends_at is 1x."""
    at_u = parse_ts(at)
    multiplier = 1
    if power_hour is not None:
        start, end = parse_ts(power_hour[0]), parse_ts(power_hour[1])
        if start <= at_u < end:
            multiplier = mult
    after_freeze = not (at_u < parse_ts(window_end))
    extra = None
    if valid and after_freeze:
        extra = "after_freeze"
    elif valid and liveness_fail:
        extra = "liveness_fail"
    valid_final = bool(valid) and not after_freeze and not in_challenge and not liveness_fail
    return valid_final, multiplier, (multiplier if valid_final else 0), extra


def counted_toward_cap(decision: str, duration_s: float | None, rep_count: int | None, min_s: float) -> bool:
    if decision != "accept":
        return False
    return (duration_s or 0) >= min_s or (rep_count or 0) >= 1


def streak(days_with_valid: set[date], today: date) -> int:
    d = today if today in days_with_valid else today - timedelta(days=1)
    n = 0
    while d in days_with_valid:
        n += 1
        d -= timedelta(days=1)
    return n


def avatar_level(points: int, thresholds: list[int]) -> int:
    """1 + count of thresholds[1:] <= points."""
    return 1 + sum(1 for t in thresholds[1:] if t <= points)


_MAX = datetime.max.replace(tzinfo=timezone.utc)


def _far(v):
    return parse_ts(v) if v is not None else _MAX


def rank_order(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Points desc, then reached_at asc, then joined_at asc. Zero-point users come after (stable on joined_at)."""
    def key(r):
        pts = r.get("points") or 0
        if pts <= 0:
            return (1, 0, _MAX, _far(r.get("joined_at")))
        return (0, -pts, _far(r.get("reached_at")), _far(r.get("joined_at")))
    return sorted(rows, key=key)


def eta_range(position: int, avg_cycle_s: float, remaining_s: float = 0) -> tuple[int, int]:
    """Minutes-range estimate for a 1-based queue position, bucketed to 5 min: (lo, hi)."""
    wait_min = max(0.0, remaining_s + max(position - 1, 0) * avg_cycle_s) / 60.0
    lo = int(math.floor(wait_min / 5.0)) * 5
    return lo, lo + 5


def format_eta(lo: int, hi: int) -> str:
    return f"~{lo}–{hi} min"
