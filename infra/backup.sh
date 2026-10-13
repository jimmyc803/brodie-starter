#!/usr/bin/env bash
set -euo pipefail
: "${SUPABASE_DB_URL:?required}" "${BACKUP_BUCKET:?required}"
umask 077
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
stamp=$(date -u +%Y/%m/%d/%Y%m%dT%H%M%SZ)
# pgenv.py splits the URI into PG* env vars so the password never appears in argv.
python3 "$(dirname "$0")/pgenv.py" pg_dump --schema=public --format=custom --no-owner --no-acl | gzip >"$tmp/database.dump.gz"
gzip -t "$tmp/database.dump.gz"
aws s3 cp "$tmp/database.dump.gz" "s3://$BACKUP_BUCKET/$stamp.dump.gz" --sse AES256 --only-show-errors
echo "Backup uploaded: $stamp.dump.gz"
