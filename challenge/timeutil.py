"""ET (America/New_York) time helpers. All stored timestamps are UTC-aware."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc


def parse_ts(v: str | datetime) -> datetime:
    """ISO string or datetime -> tz-aware UTC datetime. Naive input is taken as UTC."""
    if isinstance(v, str):
        s = v.strip()
        if s.endswith(("Z", "z")):
            s = s[:-1] + "+00:00"
        v = datetime.fromisoformat(s)
    if v.tzinfo is None:
        v = v.replace(tzinfo=UTC)
    return v.astimezone(UTC)


def et_day(ts: str | datetime) -> date:
    return parse_ts(ts).astimezone(ET).date()


def et_midnight_after(ts: str | datetime) -> datetime:
    """The next ET midnight strictly after ts, as aware UTC."""
    nxt = et_day(ts) + timedelta(days=1)
    return datetime.combine(nxt, time(0, 0), tzinfo=ET).astimezone(UTC)


def _quiet_hit(hour: int, quiet: tuple[int, int] | list[int]) -> bool:
    start, end = quiet
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def in_quiet_hours(ts: str | datetime, quiet: tuple[int, int] | list[int] = (23, 9)) -> bool:
    return _quiet_hit(parse_ts(ts).astimezone(ET).hour, quiet)


def next_quiet_end(ts: str | datetime, quiet: tuple[int, int] | list[int] = (23, 9)) -> datetime:
    """Earliest instant >= ts that is outside quiet hours (ts itself if not quiet), aware UTC."""
    t = parse_ts(ts)
    if not in_quiet_hours(t, quiet):
        return t
    local = t.astimezone(ET)
    end = quiet[1]
    d = local.date()
    if local.hour >= end:  # evening side of the wrap: ends tomorrow
        d += timedelta(days=1)
    return datetime.combine(d, time(end, 0), tzinfo=ET).astimezone(UTC)
