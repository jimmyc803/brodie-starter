"""scripts/seed_admins.py against the migrated test database."""
from __future__ import annotations

import pytest

from db.test.harness import connect
from scripts.seed_admins import main, parse_emails, seed_admins


def test_parse_emails_normalises_and_dedupes():
    assert parse_emails("A@x.com, b@y.org  a@X.com") == ["a@x.com", "b@y.org"]


@pytest.mark.parametrize("raw", ["", " , ", "not-an-email", "a@b"])
def test_parse_emails_rejects_bad_input(raw):
    with pytest.raises(ValueError):
        parse_emails(raw)


def test_seed_inserts_audits_and_is_idempotent(conn):
    r = seed_admins(conn, ["one@x.com", "two@x.com"], "boss@x.com", "launch admins")
    assert r == {"added": ["one@x.com", "two@x.com"], "existing": []}
    assert sorted(x[0] for x in conn.execute("select email from admin_allowlist").fetchall()) == ["one@x.com", "two@x.com"]
    rows = conn.execute(
        "select actor, target, reason, after->>'email' from audit_log where action = 'admin_seed' order by target"
    ).fetchall()
    assert rows == [("boss@x.com", "one@x.com", "launch admins", "one@x.com"),
                    ("boss@x.com", "two@x.com", "launch admins", "two@x.com")]
    r2 = seed_admins(conn, ["ONE@x.com", "three@x.com"], "boss@x.com", "again")
    assert r2 == {"added": ["three@x.com"], "existing": ["one@x.com"]}
    assert conn.execute("select count(*) from audit_log where action = 'admin_seed'").fetchone()[0] == 3


def test_dry_run_writes_nothing(conn):
    before = conn.execute("select count(*) from admin_allowlist").fetchone()[0]
    r = seed_admins(conn, ["dry@x.com"], "boss@x.com", "preview", dry_run=True)
    assert r["added"] == ["dry@x.com"]
    assert conn.execute("select count(*) from admin_allowlist").fetchone()[0] == before
    assert conn.execute("select count(*) from audit_log where target = 'dry@x.com'").fetchone()[0] == 0


@pytest.mark.parametrize("actor,reason", [("", "r"), ("a@x.com", " ")])
def test_actor_and_reason_required(conn, actor, reason):
    with pytest.raises(ValueError):
        seed_admins(conn, ["req@x.com"], actor, reason)
    assert conn.execute("select count(*) from admin_allowlist where email = 'req@x.com'").fetchone()[0] == 0


def test_cli_end_to_end(db, capsys):
    rc = main(["--dsn", db, "--emails", "cli@x.com", "--actor", "boss@x.com", "--reason", "cli test"])
    assert rc == 0
    assert "added: cli@x.com" in capsys.readouterr().out
    with connect(db) as c:
        assert c.execute("select count(*) from admin_allowlist where email = 'cli@x.com'").fetchone()[0] == 1
    assert main(["--dsn", db, "--emails", "bad", "--actor", "a@x.com", "--reason", "r"]) == 1


def test_cli_requires_dsn(monkeypatch):
    monkeypatch.delenv("CHALLENGE_DB_DSN", raising=False)
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert main(["--emails", "a@x.com", "--actor", "a@x.com", "--reason", "r"]) == 2
