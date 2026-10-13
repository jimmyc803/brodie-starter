#!/usr/bin/env python3
"""Split SUPABASE_DB_URL into libpq environment variables.

libpq only expands a connection URI passed as the dbname *argument*; a URI in PGDATABASE is taken as a literal
database name, so the client silently falls back to the local socket. Passing the URI on argv would expose the
password in `ps`, so callers get PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE/PGSSLMODE instead.

    python3 infra/pgenv.py pg_dump --schema=public ...   # exec the command with the split env
"""
from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, unquote, urlsplit


def pg_env(url: str, base: dict | None = None) -> dict:
    parts = urlsplit(url)
    if parts.scheme not in ('postgres', 'postgresql') or not parts.hostname:
        raise SystemExit('SUPABASE_DB_URL must be a postgresql:// URI')
    env = dict(os.environ if base is None else base)
    env.update(PGHOST=parts.hostname, PGPORT=str(parts.port or 5432), PGDATABASE=unquote(parts.path.lstrip('/')) or 'postgres',
               PGCONNECT_TIMEOUT=env.get('PGCONNECT_TIMEOUT', '10'))
    if parts.username:
        env['PGUSER'] = unquote(parts.username)
    if parts.password:
        env['PGPASSWORD'] = unquote(parts.password)
    sslmode = parse_qs(parts.query).get('sslmode')
    env['PGSSLMODE'] = sslmode[0] if sslmode else 'require'
    return env


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise SystemExit('usage: pgenv.py COMMAND [ARGS...]')
    os.execvpe(sys.argv[1], sys.argv[1:], pg_env(os.environ['SUPABASE_DB_URL']))
