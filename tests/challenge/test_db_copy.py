"""Migration 20261017_challenge_copy.sql: ufc_fighter / first_prize in competition_public."""
from __future__ import annotations

import pytest

from db.test.harness import connect

MIGRATION = "db/migrations/20261017_challenge_copy.sql"


@pytest.fixture
def tx(db):
    c = connect(db, autocommit=False)
    try:
        yield c
    finally:
        c.rollback()
        c.close()


def test_anon_reads_defaults(tx):
    tx.execute("set local role anon")
    assert tx.execute("select ufc_fighter, first_prize from competition_public").fetchone() == (None, "$100")


def test_anon_reads_configured_fighter(tx):
    tx.execute("update competition_config set value = to_jsonb('Max H'::text) where key = 'ufc_fighter'")
    tx.execute("set local role anon")
    assert tx.execute("select ufc_fighter from competition_public").fetchone()[0] == "Max H"


def test_migration_idempotent_keeps_config(tx):
    tx.execute("update competition_config set value = to_jsonb('$250'::text) where key = 'first_prize'")
    tx.execute(open(MIGRATION).read())
    tx.execute("set local role anon")
    assert tx.execute("select first_prize from competition_public").fetchone()[0] == "$250"


def test_view_column_order_and_barrier(tx):
    cols = [r[0] for r in tx.execute(
        "select column_name from information_schema.columns where table_name = 'competition_public' "
        "order by ordinal_position")]
    # Later migrations append to this view; existing columns must keep their order (20261028 added drawing_prize).
    assert cols == ["window_start", "window_end", "frozen", "brodie_number",
                    "site_url", "avatar_level_thresholds", "ufc_fighter", "first_prize", "drawing_prize"]
    opts = tx.execute("select reloptions from pg_class where relname = 'competition_public'").fetchone()[0]
    assert "security_barrier=true" in opts
