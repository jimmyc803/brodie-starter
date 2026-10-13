"""Power hour scheduling (SPEC §2): one hour per ET day, random start inside power_hour_window, never the
same hour two days running. Selection is seeded by (secret salt, date) so it is reproducible for the
team but not guessable. Rows are written once (ch_power_hour_ensure is insert-or-keep)."""
from __future__ import annotations

import hashlib
import logging
import os
import random
from datetime import date, datetime, time, timedelta
from typing import Any

from challenge.store import Store
from challenge.timeutil import ET, UTC, et_day, parse_ts

logger = logging.getLogger("challenge.jobs")


MIN_SECRET_LEN = 16


def require_secret() -> None:
    """Startup guard: outside test/demo modes an empty or short salt would make power hours guessable."""
    mode = os.environ.get("CHALLENGE_MODE", "").strip().lower()
    if mode in ("", "demo", "test", "off"):
        return
    if len(os.environ.get("POWER_HOUR_SECRET", "")) < MIN_SECRET_LEN:
        raise RuntimeError(f"POWER_HOUR_SECRET must be set (>= {MIN_SECRET_LEN} chars) when CHALLENGE_MODE={mode}")


def _salt() -> str:
    return os.environ.get("POWER_HOUR_SECRET", "")


def pick_hour(day: date, lo: int, hi: int, exclude: int | None = None,
              min_hour: int | None = None, salt: str | None = None) -> int:
    """Start hour h with lo <= h and h + 1 <= hi (the whole hour sits inside the window)."""
    salt = _salt() if salt is None else salt
    floor = lo if min_hour is None else max(lo, min_hour)
    cands = [h for h in range(floor, hi) if h != exclude] or [h for h in range(lo, hi) if h != exclude]
    if not cands:
        raise ValueError(f"empty power hour window [{lo}, {hi}]")
    seed = hashlib.sha256(f"{salt}|{day.isoformat()}".encode()).digest()
    return random.Random(int.from_bytes(seed[:8], "big")).choice(cands)


def start_at(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour), tzinfo=ET).astimezone(UTC)


def fmt_range(starts: datetime | str, ends: datetime | str) -> str:
    s, e = parse_ts(starts).astimezone(ET), parse_ts(ends).astimezone(ET)
    a, b = s.strftime("%I:%M %p").lstrip("0"), e.strftime("%I:%M %p").lstrip("0")
    if a[-2:] == b[-2:]:
        a = a[:-3]
    return f"{a}–{b}"


class PowerHours:
    def __init__(self, store: Store, cfg: Any):
        self.store, self.cfg = store, cfg
        self._ensured: set[date] = set()

    def _row(self, day: date) -> dict | None:
        return self.store.rpc("ch_power_hour_row", {"p_date_et": day})

    def _hour_of(self, row: dict | None) -> int | None:
        return parse_ts(row["starts_at"]).astimezone(ET).hour if row else None

    def ensure_day(self, day: date, now: datetime) -> dict:
        """Row for `day`, creating it (and a missing predecessor's baseline pick) if needed."""
        lo, hi = (int(x) for x in self.cfg.get("power_hour_window"))
        existing = self._row(day)
        if existing:
            return existing
        prev = self._row(day - timedelta(days=1))
        prev_hour = self._hour_of(prev)
        if prev_hour is None:  # reproducible baseline: what the previous day would have drawn
            prev_hour = pick_hour(day - timedelta(days=1), lo, hi)
        min_hour = None
        w_start = parse_ts(self.cfg.get("window_start")).astimezone(ET)
        if day == w_start.date():  # a power hour before the competition opens is wasted
            min_hour = w_start.hour + (1 if w_start.minute or w_start.second else 0)
        hour = pick_hour(day, lo, hi, exclude=prev_hour, min_hour=min_hour)
        row = self.store.rpc("ch_power_hour_ensure", {
            "p_date_et": day, "p_starts_at": start_at(day, hour), "p_now": now})
        logger.info("power hour %s starts %02d:00 ET", day, hour)
        return row

    def ensure(self, now: datetime) -> None:
        """Rows for today and tomorrow (ET), never past the final competition day."""
        today = et_day(now)
        last = et_day(self.cfg.get("window_end"))
        for day in (today, today + timedelta(days=1)):
            if day > last or day in self._ensured:
                continue
            self.ensure_day(day, now)
            self._ensured.add(day)
