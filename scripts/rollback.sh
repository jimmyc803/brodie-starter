#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root using infra/with-env.py' >&2; exit 1; }
cd /opt/brodie
exec 9>/var/lib/brodie/deploy.lock
flock -n 9 || { echo 'Another deployment or rollback is running' >&2; exit 1; }
previous=$(cat /var/lib/brodie/previous-sha)
[[ $previous =~ ^[0-9a-f]{40}$ ]] || { echo 'Invalid previous SHA' >&2; exit 1; }
[[ -z $(runuser -u brodie -- git status --porcelain --untracked-files=no) ]] || { echo 'Tracked checkout changes; refusing rollback' >&2; exit 1; }
runuser -u brodie -- git cat-file -e "$previous^{commit}"
systemctl stop brodie-reconciler.timer brodie-backup.timer brodie-heartbeat-check brodie-worker chert-agent brodie-dispatcher brodie-reconciler.service
runuser -u brodie -- git checkout --detach "$previous"
runuser -u brodie -- uv pip sync --python /opt/brodie/.venv/bin/python requirements.txt
install -m 0644 infra/systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl start brodie-worker chert-agent brodie-dispatcher brodie-heartbeat-check brodie-reconciler.timer brodie-backup.timer
bash infra/health.sh
printf '%s\n' "$previous" >/var/lib/brodie/deployed-sha
echo "Rolled back application to $previous; database migrations were retained"
