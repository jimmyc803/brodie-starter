#!/usr/bin/env bash
set -euo pipefail
: "${SUPABASE_DB_URL:?required}" "${BACKUP_BUCKET:?required}"
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
stamp=$(date -u +%Y/%m/%d/%Y%m%dT%H%M%SZ)
# libpq accepts a connection URI as PGDATABASE; it need not appear in argv.
PGDATABASE="$SUPABASE_DB_URL" pg_dump --format=custom --no-owner --no-acl | gzip >"$tmp/database.dump.gz"
gzip -t "$tmp/database.dump.gz"
aws s3 cp "$tmp/database.dump.gz" "s3://$BACKUP_BUCKET/$stamp.dump.gz" --sse AES256 --only-show-errors
echo "Backup uploaded: $stamp.dump.gz"
