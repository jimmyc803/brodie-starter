#!/usr/bin/env python3
"""Apply ordered idempotent migrations while holding a session advisory lock."""
import hashlib
import os
from pathlib import Path
import re
import subprocess

sql = ["SELECT pg_advisory_lock(hashtextextended('brodie-deploy', 0));",
       'CREATE TABLE IF NOT EXISTS public.schema_migrations '
       '(name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now());']
for path in sorted(Path('db/migrations').glob('*.sql')):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', path.name):
        raise SystemExit('Unsafe migration filename')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    sql += [f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM public.schema_migrations WHERE name='{path.name}' AND sha256 <> '{digest}') THEN RAISE EXCEPTION 'Applied migration changed: {path.name}'; END IF; END $$;",
            f"SELECT NOT EXISTS (SELECT 1 FROM public.schema_migrations WHERE name='{path.name}') AS apply_migration \\gset",
            '\\if :apply_migration', f'\\i {path}',
            f"INSERT INTO public.schema_migrations(name,sha256) VALUES ('{path.name}','{digest}');", '\\endif']
env = dict(os.environ, PGDATABASE=os.environ['SUPABASE_DB_URL'], PGCONNECT_TIMEOUT='10')
subprocess.run(['psql', '-X', '-v', 'ON_ERROR_STOP=1'], input='\n'.join(sql) + '\n',
               text=True, env=env, check=True)
