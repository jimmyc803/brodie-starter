"""Seed the admin allowlist (who may sign in at /admin on the public site).

    export SUPABASE_DB_URL='postgresql://...'   # direct/session connection string from Supabase (or CHALLENGE_DB_DSN)
    PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py \
        --emails alice@example.com,bob@example.com --actor you@example.com --reason "launch admins"

Inserts into admin_allowlist (idempotent; emails are stored lower-case) and writes one audit_log row per new admin,
all in one transaction. Use --dry-run to print what would change without writing. No secret is printed.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import psycopg

_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")


def parse_emails(raw: str) -> list[str]:
    """Split a comma/space separated list, lower-case, validate, de-duplicate (order kept)."""
    out: list[str] = []
    for part in re.split(r"[,\s]+", raw.strip()):
        if not part:
            continue
        email = part.lower()
        if not _EMAIL.match(email):
            raise ValueError(f"not a valid email address: {part!r}")
        if email not in out:
            out.append(email)
    if not out:
        raise ValueError("no emails given")
    return out


def seed_admins(conn: psycopg.Connection, emails: list[str], actor: str, reason: str, dry_run: bool = False) -> dict:
    """Add emails to admin_allowlist. Returns {"added": [...], "existing": [...]}."""
    if not actor or not actor.strip():
        raise ValueError("actor is required")
    if not reason or not reason.strip():
        raise ValueError("reason is required")
    added: list[str] = []
    existing: list[str] = []
    with conn.transaction():
        for email in (e.strip().lower() for e in emails):
            if dry_run:
                row = conn.execute("select 1 from admin_allowlist where lower(email) = %s", (email,)).fetchone()
                (existing if row else added).append(email)
                continue
            row = conn.execute(
                "insert into admin_allowlist (email) select %s where not exists "
                "(select 1 from admin_allowlist where lower(email) = %s) returning email",
                (email, email),
            ).fetchone()
            if row is None:
                existing.append(email)
                continue
            added.append(email)
            conn.execute(
                "insert into audit_log (actor, action, target, before, after, reason) "
                "values (%s, 'admin_seed', %s, null, jsonb_build_object('email', %s::text), %s)",
                (actor.strip(), email, email, reason.strip()),
            )
    return {"added": added, "existing": existing}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--emails", required=True, help="comma-separated admin emails")
    ap.add_argument("--actor", required=True, help="who is making this change (your email)")
    ap.add_argument("--reason", required=True, help="why (written to audit_log)")
    ap.add_argument("--dry-run", action="store_true", help="show what would change, write nothing")
    ap.add_argument("--dsn", default=None, help="Postgres URL (default: CHALLENGE_DB_DSN or SUPABASE_DB_URL env)")
    args = ap.parse_args(argv)
    dsn = args.dsn or os.environ.get("CHALLENGE_DB_DSN") or os.environ.get("SUPABASE_DB_URL")
    if not dsn:
        print("error: set SUPABASE_DB_URL (or CHALLENGE_DB_DSN) or pass --dsn", file=sys.stderr)
        return 2
    try:
        emails = parse_emails(args.emails)
        with psycopg.connect(dsn) as conn:
            res = seed_admins(conn, emails, args.actor, args.reason, args.dry_run)
    except (ValueError, psycopg.Error) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    verb = "would add" if args.dry_run else "added"
    print(f"{verb}: {', '.join(res['added']) or '-'}")
    print(f"already admin: {', '.join(res['existing']) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
