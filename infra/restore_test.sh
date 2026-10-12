#!/usr/bin/env bash
set -euo pipefail
: "${BACKUP_BUCKET:?required}"
command -v pg_virtualenv >/dev/null || { echo 'Install postgresql-common and matching PostgreSQL server version' >&2; exit 1; }
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
key=$(aws s3api list-objects-v2 --bucket "$BACKUP_BUCKET" --query "reverse(sort_by(Contents[?ends_with(Key, '.dump.gz')], &LastModified))[0].Key" --output text)
[[ -n $key && $key != None ]] || { echo 'No backup found' >&2; exit 1; }
aws s3 cp "s3://$BACKUP_BUCKET/$key" "$tmp/database.dump.gz" --only-show-errors
gzip -dc "$tmp/database.dump.gz" >"$tmp/database.dump"
# pg_virtualenv creates and removes an isolated local cluster, even on failure.
unset PGHOST PGPORT PGUSER PGPASSWORD PGDATABASE PGSERVICE PGSERVICEFILE
pg_virtualenv bash -s -- "$tmp/database.dump" <<'SH'
set -euo pipefail
psql -X -v ON_ERROR_STOP=1 -c 'CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role; CREATE ROLE supabase_admin; CREATE ROLE authenticator;'
createdb brodie_restore
pg_restore --exit-on-error --no-owner --no-acl --dbname brodie_restore "$1"
psql -X -v ON_ERROR_STOP=1 --dbname brodie_restore <<'SQL'
SELECT format('SELECT %L AS table_name, count(*) AS rows FROM public.%I;', name, name)
FROM unnest(ARRAY['clients','calls','reps','competition_config','line_state']) AS name \gexec
DO $$ BEGIN
 IF NOT EXISTS (SELECT 1 FROM public.competition_config) THEN
   RAISE EXCEPTION 'Restored competition_config is empty';
 END IF;
END $$;
SQL
SH
echo "Restore verified: $key"
