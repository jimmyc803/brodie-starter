"""Shared fixtures for challenge tests.

pg_cluster (session): throwaway Postgres 17 cluster (db/test/harness.py) with a migrated template database.
pg_dsn     (session): DSN of the cluster's maintenance database `postgres` (superuser).
db         (module):  DSN of a fresh database cloned from the template (shim + schema + all migrations applied).
conn       (function): autocommit superuser psycopg connection to `db`.
"""
from __future__ import annotations

import re

import pytest

from db.test.harness import PgCluster, connect


@pytest.fixture(scope="session")
def pg_cluster():
    cluster = PgCluster.start()
    try:
        cluster.build_template()
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture(scope="session")
def pg_dsn(pg_cluster) -> str:
    return pg_cluster.dsn()


@pytest.fixture(scope="module")
def db(pg_cluster, request) -> str:
    name = "t_" + re.sub(r"[^a-z0-9_]", "_", request.module.__name__.rsplit(".", 1)[-1].lower())[:55]
    dsn = pg_cluster.clone(name)
    yield dsn
    pg_cluster.drop(name)


@pytest.fixture
def conn(db):
    c = connect(db)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture(autouse=True)
def _jobs_off(monkeypatch):
    """The dispatcher's background jobs loop must not run under TestClient; jobs tests drive run_due directly."""
    monkeypatch.setenv("JOBS_ENABLED", "0")
