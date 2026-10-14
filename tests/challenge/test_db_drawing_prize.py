"""Migration 20261028_challenge_drawing_prize.sql: drawing_prize in competition_public (D-47).

The view is recreated by this migration, so the older copy columns have to survive it: a web build reading
first_prize or ufc_fighter must not break because a second prize was added next to them.
"""
from __future__ import annotations

import pytest

from db.test.harness import connect

MIGRATION = "db/migrations/20261028_challenge_drawing_prize.sql"


@pytest.fixture
def tx(db):
    c = connect(db, autocommit=False)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_anon_reads_the_drawing_prize_default(tx):
    tx.execute("set local role anon")
    assert tx.execute("select drawing_prize from competition_public").fetchone() == ("$100",)


def test_the_older_copy_columns_survive_the_view_rebuild(tx):
    tx.execute("set local role anon")
    row = tx.execute("select ufc_fighter, first_prize, drawing_prize from competition_public").fetchone()
    assert row == (None, "$100", "$100")


def test_an_operator_value_is_read_back(tx):
    tx.execute("update competition_config set value = to_jsonb('$500'::text) where key = 'drawing_prize'")
    tx.execute("set local role anon")
    assert tx.execute("select drawing_prize from competition_public").fetchone() == ("$500",)


def test_anon_cannot_write_the_prize(tx):
    tx.execute("set local role anon")
    with pytest.raises(Exception):
        tx.execute("update competition_config set value = to_jsonb('$1'::text) where key = 'drawing_prize'")
