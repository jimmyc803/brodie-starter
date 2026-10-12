from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from hypothesis import given, strategies as st

from challenge import scoring as sc
from challenge.config import DEFAULTS, Config
from challenge.store import SupaStore, StoreError, store_from_env
from challenge.timeutil import (ET, et_day, et_midnight_after, in_quiet_hours, next_quiet_end, parse_ts)

UTC = timezone.utc


def test_parse_ts():
    assert parse_ts("2026-10-12T20:00:00-04:00") == datetime(2026, 10, 13, 0, 0, tzinfo=UTC)
    assert parse_ts("2026-10-12T20:00:00Z").tzinfo is not None
    assert parse_ts(datetime(2026, 1, 1)).utcoffset() == timedelta(0)


def test_et_day_boundaries_oct_12_19():
    # EDT (UTC-4) until Nov 1: ET midnight == 04:00Z
    assert et_day("2026-10-13T03:59:59Z") == date(2026, 10, 12)
    assert et_day("2026-10-13T04:00:00Z") == date(2026, 10, 13)
    assert et_midnight_after("2026-10-12T20:00:00-04:00") == datetime(2026, 10, 13, 4, 0, tzinfo=UTC)
    for d in range(12, 19):
        ts = datetime(2026, 10, d, 12, tzinfo=UTC)
        m = et_midnight_after(ts)
        assert m > ts and et_day(m) == et_day(ts) + timedelta(days=1)
        assert m.astimezone(ET).hour == 0


def test_et_midnight_dst_change():
    # Fall back Nov 1 2026: that ET day is 25h; next midnight is 05:00Z
    assert et_midnight_after("2026-11-01T12:00:00Z") == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)
    # Spring forward Mar 8 2026 (23h day)
    assert et_midnight_after("2026-03-08T12:00:00Z") == datetime(2026, 3, 9, 4, 0, tzinfo=UTC)


def test_quiet_hours_wrap():
    q = [23, 9]
    assert in_quiet_hours("2026-10-13T03:00:00Z", q)       # 23:00 ET
    assert in_quiet_hours("2026-10-13T12:59:59Z", q)       # 08:59 ET
    assert not in_quiet_hours("2026-10-13T13:00:00Z", q)   # 09:00 ET
    assert not in_quiet_hours("2026-10-13T02:59:59Z", q)   # 22:59 ET
    assert in_quiet_hours("2026-10-13T06:00:00Z")          # default 02:00 ET
    assert not in_quiet_hours("2026-10-13T16:00:00Z", [23, 9])
    assert in_quiet_hours("2026-10-13T07:00:00Z", [1, 5]) and not in_quiet_hours("2026-10-13T10:00:00Z", [1, 5])


def test_next_quiet_end():
    assert next_quiet_end("2026-10-13T03:00:00Z") == datetime(2026, 10, 13, 13, 0, tzinfo=UTC)  # 23:00 -> 9:00 ET next day
    assert next_quiet_end("2026-10-13T06:00:00Z") == datetime(2026, 10, 13, 13, 0, tzinfo=UTC)  # 02:00 -> 09:00 same day
    t = parse_ts("2026-10-13T18:00:00Z")
    assert next_quiet_end(t) == t


@given(st.datetimes(min_value=datetime(2026, 10, 12), max_value=datetime(2026, 10, 20)))
def test_next_quiet_end_never_quiet(dt):
    e = next_quiet_end(dt.replace(tzinfo=UTC))
    assert e >= dt.replace(tzinfo=UTC) and not in_quiet_hours(e)


WEND = "2026-10-18T23:59:59-04:00"
PH = (parse_ts("2026-10-14T16:00:00Z"), parse_ts("2026-10-14T17:00:00Z"))


def test_power_hour_per_rep_timestamp():
    f = lambda at: sc.rep_points(at, True, False, False, WEND, PH, 2)
    assert f("2026-10-14T16:00:00Z") == (True, 2, 2, None)           # start inclusive
    assert f("2026-10-14T16:59:59Z") == (True, 2, 2, None)
    assert f("2026-10-14T17:00:00Z") == (True, 1, 1, None)           # at ends_at is 1x
    assert f("2026-10-14T15:59:59Z") == (True, 1, 1, None)
    assert sc.rep_points("2026-10-14T16:30:00Z", True, False, False, WEND, None, 2)[1] == 1


def test_rep_invalidation():
    assert sc.rep_points("2026-10-14T16:30:00Z", False, False, False, WEND, PH, 2) == (False, 2, 0, None)
    assert sc.rep_points("2026-10-14T16:30:00Z", True, True, False, WEND, PH, 2)[::2] == (False, 0)
    assert sc.rep_points("2026-10-14T16:30:00Z", True, False, True, WEND, PH, 2) == (False, 2, 0, "liveness_fail")


def test_after_freeze():
    assert sc.rep_points("2026-10-19T03:59:58Z", True, False, False, WEND, None, 2) == (True, 1, 1, None)
    assert sc.rep_points("2026-10-19T03:59:59Z", True, False, False, WEND, None, 2) == (False, 1, 0, "after_freeze")
    assert sc.rep_points("2026-10-19T05:00:00Z", True, False, False, WEND, None, 2)[3] == "after_freeze"


def test_counted_toward_cap():
    assert sc.counted_toward_cap("accept", 30, 0, 30)
    assert not sc.counted_toward_cap("accept", 29.9, 0, 30)
    assert sc.counted_toward_cap("accept", 5, 1, 30)
    assert not sc.counted_toward_cap("reject", 100, 5, 30)
    assert not sc.counted_toward_cap("accept", None, None, 30)


def test_streak():
    today = date(2026, 10, 15)
    d = lambda *n: {date(2026, 10, x) for x in n}
    assert sc.streak(d(13, 14, 15), today) == 3
    assert sc.streak(d(13, 14), today) == 2            # today not yet
    assert sc.streak(d(12, 13, 15), today) == 1        # gap
    assert sc.streak(d(12, 13), today) == 0            # gap yesterday
    assert sc.streak(set(), today) == 0


def test_avatar_levels_1_to_10():
    th = DEFAULTS["avatar_level_thresholds"]
    assert sc.avatar_level(0, th) == 1
    assert sc.avatar_level(24, th) == 1
    assert sc.avatar_level(25, th) == 2
    assert sc.avatar_level(449, th) == 6
    assert sc.avatar_level(450, th) == 7
    assert sc.avatar_level(1200, th) == 10
    assert sc.avatar_level(10**6, th) == 10
    assert {sc.avatar_level(p, th) for p in range(0, 1300)} == set(range(1, 11))


@given(st.integers(0, 5000), st.integers(0, 5000))
def test_avatar_monotonic(a, b):
    th = DEFAULTS["avatar_level_thresholds"]
    lo, hi = sorted((a, b))
    assert 1 <= sc.avatar_level(lo, th) <= sc.avatar_level(hi, th) <= 10


def test_rank_order_tiebreak():
    rows = [
        {"id": "zero", "points": 0, "joined_at": "2026-10-12T10:00:00Z"},
        {"id": "b", "points": 10, "reached_at": "2026-10-14T12:00:00Z", "joined_at": "2026-10-12T10:00:00Z"},
        {"id": "a", "points": 10, "reached_at": "2026-10-13T12:00:00Z", "joined_at": "2026-10-12T11:00:00Z"},
        {"id": "top", "points": 30, "reached_at": "2026-10-15T12:00:00Z", "joined_at": "2026-10-12T12:00:00Z"},
        {"id": "c", "points": 10, "reached_at": "2026-10-13T12:00:00Z", "joined_at": "2026-10-12T09:00:00Z"},
        {"id": "zero2", "points": 0, "joined_at": "2026-10-12T09:00:00Z"},
    ]
    assert [r["id"] for r in sc.rank_order(rows)] == ["top", "c", "a", "b", "zero2", "zero"]


def test_eta():
    assert sc.eta_range(1, 400, 0) == (0, 5)
    lo, hi = sc.eta_range(2, 420, 180)  # 600s -> 10 min
    assert (lo, hi) == (10, 15)
    assert sc.format_eta(lo, hi) == "~10–15 min"
    assert sc.eta_range(3, 400, 100)[0] == 15  # 900s


class FakeStore:
    def __init__(self, data=None, fail=False):
        self.data, self.fail, self.calls = data, fail, 0

    def rpc(self, fn, args):
        self.calls += 1
        assert fn == "ch_config_get"
        if self.fail:
            raise StoreError("down")
        return self.data


def test_config_fallback_and_ttl():
    now = [0.0]
    s = FakeStore({"daily_call_cap": 7})
    c = Config(s, ttl_s=15, clock=lambda: now[0])
    assert c.get("daily_call_cap") == 7
    assert c.get("claim_window_s") == 90  # default for missing key
    assert s.calls == 1
    s.data = {"daily_call_cap": 9}
    now[0] = 14
    assert c.get("daily_call_cap") == 7
    now[0] = 16
    assert c.get("daily_call_cap") == 9 and s.calls == 2
    s.fail = True
    now[0] = 40
    assert c.get("daily_call_cap") == 9  # keeps last good on error
    assert c.all()["call_count_s"] == 180
    with pytest.raises(KeyError):
        c.get("nope")


def test_config_store_down_uses_defaults():
    c = Config(FakeStore(fail=True))
    assert c.get("power_multiplier") == 2
    assert set(c.all()) == set(DEFAULTS)


def test_defaults_has_all_c2_keys():
    keys = """window_start window_end call_count_s call_reveal_s daily_call_cap claim_window_s line_offline_gap_s
    min_counted_call_s in_call_timeout_extra_s power_hour_window power_multiplier rank_drop_min rank_drop_throttle_h
    quiet_hours recap_hour streak_risk_hour raffle_min_valid_reps raffle_prize avatar_level_thresholds judge_thresholds
    registration_open competition_frozen swearing site_url brodie_number team_alert_handles challenge_coach_id
    outbound_rate_per_min""".split()
    assert set(keys) <= set(DEFAULTS)


def test_supastore_rpc():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["h"], seen["body"] = str(req.url), req.headers, req.read()
        return httpx.Response(200, json={"ok": True})

    s = SupaStore("https://x.supabase.co/", "KEY", transport=httpx.MockTransport(handler))
    out = s.rpc("ch_tick", {"p_now": datetime(2026, 10, 13, tzinfo=UTC), "p_x": [1]})
    assert out == {"ok": True}
    assert seen["url"] == "https://x.supabase.co/rest/v1/rpc/ch_tick"
    assert seen["h"]["apikey"] == "KEY" and seen["h"]["authorization"] == "Bearer KEY"
    assert b"2026-10-13T00:00:00+00:00" in seen["body"]


def test_supastore_errors():
    s = SupaStore("https://x", "K", transport=httpx.MockTransport(lambda r: httpx.Response(400, text="boom")))
    with pytest.raises(StoreError, match="400"):
        s.rpc("ch_tick", {})

    def boom(r):
        raise httpx.ConnectError("no")

    with pytest.raises(StoreError):
        SupaStore("https://x", "K", transport=httpx.MockTransport(boom)).rpc("f", {})
    with pytest.raises(StoreError):
        s.rpc("f; drop table x", {})


def test_store_from_env(monkeypatch):
    from challenge.store import PgStore
    monkeypatch.setenv("CHALLENGE_DB_DSN", "postgresql://x/y")
    assert isinstance(store_from_env(), PgStore)
    monkeypatch.delenv("CHALLENGE_DB_DSN")
    monkeypatch.setenv("SUPABASE_URL", "https://x")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    assert isinstance(store_from_env(), SupaStore)
    monkeypatch.delenv("SUPABASE_URL")
    with pytest.raises(StoreError):
        store_from_env()
