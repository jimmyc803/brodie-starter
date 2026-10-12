"""Migration 20261015_challenge_power.sql: ch_power_hour lookup."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from db.test.harness import connect

ET = ZoneInfo("America/New_York")


@pytest.fixture
def tx(db):
    c = connect(db, autocommit=False)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def ph(c, now):
    return c.execute("select ch_power_hour(%s)", (now,)).fetchone()[0]


def test_service_role_only(tx):
    row = tx.execute(
        "select has_function_privilege('anon', 'ch_power_hour(timestamptz)', 'execute'),"
        " has_function_privilege('service_role', 'ch_power_hour(timestamptz)', 'execute')").fetchone()
    assert row == (False, True)


def test_none_scheduled(tx):
    assert ph(tx, datetime(2026, 10, 14, 12, tzinfo=ET)) is None


def test_hidden_until_announced_or_started(tx):
    tx.execute("insert into power_hours(date_et, starts_at, ends_at) values (%s, %s, %s)",
               ("2026-10-14", datetime(2026, 10, 14, 18, tzinfo=ET), datetime(2026, 10, 14, 19, tzinfo=ET)))
    assert ph(tx, datetime(2026, 10, 14, 17, tzinfo=ET)) is None
    r = ph(tx, datetime(2026, 10, 14, 18, 30, tzinfo=ET))
    assert r["active"] and not r["over"] and not r["announced"]
    tx.execute("update power_hours set announced_at = %s", (datetime(2026, 10, 14, 17, tzinfo=ET),))
    r = ph(tx, datetime(2026, 10, 14, 17, 30, tzinfo=ET))
    assert r["announced"] and not r["active"]
    assert ph(tx, datetime(2026, 10, 14, 19, tzinfo=ET))["over"]


def test_et_day_boundary(tx):
    tx.execute("insert into power_hours(date_et, starts_at, ends_at, announced_at) values (%s, %s, %s, %s)",
               ("2026-10-14", datetime(2026, 10, 14, 21, tzinfo=ET), datetime(2026, 10, 14, 22, tzinfo=ET),
                datetime(2026, 10, 14, 9, tzinfo=ET)))
    # 23:59 ET on the 14th is already the 15th in UTC; still the 14th's power hour
    assert ph(tx, datetime(2026, 10, 14, 23, 59, tzinfo=ET))["date_et"] == "2026-10-14"
    assert ph(tx, datetime(2026, 10, 15, 0, 1, tzinfo=ET)) is None
