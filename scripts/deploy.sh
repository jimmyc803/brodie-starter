#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --dry-run ]]; then
  printf '%s\n' "Deploy plan for $root:" 'record previous SHA; git pull --ff-only; uv pip sync; apply ordered migrations with schema_migrations; install/restart changed units; retry /health'
  exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: deploy.sh [--dry-run]' >&2; exit 2; }
[[ $EUID == 0 && $root == /opt/brodie ]] || { echo 'Run as root from /opt/brodie using infra/with-env.py' >&2; exit 1; }
: "${SUPABASE_DB_URL:?required}"
install -d -m 0700 /var/lib/brodie
exec 9>/var/lib/brodie/deploy.lock
flock -n 9 || { echo 'Another deployment or rollback is running' >&2; exit 1; }
cd "$root"
git_as_user() { runuser -u brodie -- git "$@"; }
[[ -z $(git_as_user status --porcelain --untracked-files=no) ]] || { echo 'Tracked checkout changes; refusing deploy' >&2; exit 1; }
previous=$(git_as_user rev-parse HEAD)
branch=$(git_as_user symbolic-ref --short -q HEAD || cat /var/lib/brodie/deploy-branch)
printf '%s\n' "$branch" >/var/lib/brodie/deploy-branch
git_as_user checkout "$branch"
git_as_user pull --ff-only
current=$(git_as_user rev-parse HEAD)
if [[ $current != "$previous" || ! -f /var/lib/brodie/previous-sha ]]; then
  printf '%s\n' "$previous" >/var/lib/brodie/previous-sha.new
  mv /var/lib/brodie/previous-sha.new /var/lib/brodie/previous-sha
fi
systemctl stop brodie-reconciler.timer brodie-backup.timer brodie-heartbeat-check brodie-worker chert-agent brodie-dispatcher brodie-reconciler.service
runuser -u brodie -- uv pip sync --python "$root/.venv/bin/python" requirements.txt
python3 infra/migrations.py
for unit in infra/systemd/*; do
  if ! cmp -s "$unit" "/etc/systemd/system/$(basename "$unit")"; then
    install -m 0644 "$unit" /etc/systemd/system/
  fi
done
systemctl daemon-reload
systemctl enable --now brodie-worker chert-agent brodie-dispatcher brodie-heartbeat-check brodie-reconciler.timer brodie-backup.timer
bash infra/health.sh
printf '%s\n' "$current" >/var/lib/brodie/deployed-sha
echo "Deployed $current (previous $previous)"
