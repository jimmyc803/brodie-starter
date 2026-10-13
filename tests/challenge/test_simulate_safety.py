"""scripts/simulate.py truncates tables: it must never be able to touch a real database (task 24 fix round, C7.s)."""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import psycopg
import pytest

from db.test.harness import connect

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def sim():
    spec = importlib.util.spec_from_file_location("simulate_under_test", ROOT / "scripts" / "simulate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    yield mod
    sys.modules.pop(spec.name, None)


REMOTE = [
    "host=db.abcdefgh.supabase.co port=5432 dbname=postgres user=postgres",
    "postgresql://postgres:secret@db.abcdefgh.supabase.co:5432/postgres",
    "postgresql://postgres@aws-0-us-east-1.pooler.supabase.com:6543/postgres",
    "host=localhost,db.example.com dbname=postgres",
    "host=localhost hostaddr=10.1.2.3 dbname=postgres",
    "postgresql://u@[2001:db8::1]:5432/x",
    "host=192.168.1.20 dbname=postgres",
    "service=prod",
]


@pytest.mark.parametrize("dsn", REMOTE)
def test_refuses_non_local_dsn_before_connecting(sim, monkeypatch, dsn):
    for k in ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(k, raising=False)

    def no_connect(*a, **kw):
        raise AssertionError("simulate.py connected to a refused DSN")

    monkeypatch.setattr(psycopg, "connect", no_connect)
    env_before = dict(os.environ)
    with pytest.raises(sim.UnsafeTarget):
        sim.check_local_dsn(dsn)
    assert sim.main(["--dsn", dsn, "--no-report"]) == 2
    assert dict(os.environ) == env_before, "refusal must happen before the script edits the environment"


@pytest.mark.parametrize("dsn", ["", "dbname=postgres", "host=/tmp/chpg123/s port=5432 dbname=postgres",
                                 "host=localhost port=5432", "postgresql://postgres@127.0.0.1:5432/postgres",
                                 "postgresql://u@[::1]/x", "host=127.0.0.1 hostaddr=127.0.0.1"])
def test_accepts_local_dsn(sim, monkeypatch, dsn):
    for k in ("PGHOST", "PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE"):
        monkeypatch.delenv(k, raising=False)
    sim.check_local_dsn(dsn)


def test_libpq_env_cannot_smuggle_a_remote_host(sim, monkeypatch):
    monkeypatch.setenv("PGHOST", "db.abcdefgh.supabase.co")
    with pytest.raises(sim.UnsafeTarget):
        sim.check_local_dsn("dbname=postgres")
    sim.check_local_dsn("host=/tmp/s dbname=postgres")  # an explicit local host wins over PGHOST
    monkeypatch.delenv("PGHOST")
    monkeypatch.setenv("PGSERVICE", "prod")
    with pytest.raises(sim.UnsafeTarget):
        sim.check_local_dsn("host=localhost")


def test_refuses_database_it_did_not_create_or_with_clients(sim, pg_cluster, db):
    with connect(db) as c:  # the module's migrated test database: not a sim_ name
        with pytest.raises(sim.UnsafeTarget, match="not created by the simulation"):
            sim.check_target_db(c)
    dsn, name = sim.create_sim_database(pg_cluster.dsn())
    try:
        assert name.startswith("sim_") and len(name) == 16
        with connect(dsn) as c:
            sim.check_target_db(c)  # fresh + migrated + empty: allowed
            coach = c.execute("select (value #>> '{}')::uuid from competition_config"
                              " where key='challenge_coach_id'").fetchone()[0]
            c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,'r','real_1',now())",
                      (coach,))
            with pytest.raises(sim.UnsafeTarget, match="already has 1 clients"):
                sim.check_target_db(c)
    finally:
        sim.drop_sim_database(pg_cluster.dsn(), name)
    with connect(pg_cluster.dsn()) as c:
        assert c.execute("select count(*) from pg_database where datname = %s", (name,)).fetchone()[0] == 0
    with pytest.raises(sim.UnsafeTarget):
        sim.drop_sim_database(pg_cluster.dsn(), "postgres")
