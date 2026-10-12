#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
for name in brodie-worker chert-agent brodie-dispatcher brodie-heartbeat-check brodie-reconciler brodie-backup; do
  unit="infra/systemd/$name.service"
  for key in 'RestartSec=3' 'StartLimitIntervalSec=0' 'StandardOutput=journal' 'StandardError=journal' 'OnFailure=brodie-alert@%n.service'; do
    grep -qxF "$key" "$unit"
  done
  grep -qxF 'WorkingDirectory=/opt/brodie/current' "$unit"
  if [[ $name == brodie-backup ]]; then
    grep -qxF 'User=brodie' "$unit"
    grep -qxF 'EnvironmentFile=/etc/brodie/backup-env' "$unit"
  else
    grep -qxF 'EnvironmentFile=/etc/brodie/env' "$unit"
  fi
  if [[ $name == brodie-reconciler || $name == brodie-backup ]]; then
    grep -qxF 'Type=oneshot' "$unit"
    grep -qxF 'Restart=on-failure' "$unit"
    grep -qxF "Unit=$name.service" "infra/systemd/$name.timer"
  else
    grep -qxF 'Restart=always' "$unit"
  fi
done
grep -qxF 'OnUnitActiveSec=60' infra/systemd/brodie-reconciler.timer
grep -qxF 'Persistent=true' infra/systemd/brodie-backup.timer
grep -qF -- '--host 127.0.0.1 --port 8080' infra/systemd/brodie-dispatcher.service
bash scripts/deploy.sh --dry-run >/dev/null
bash infra/provision.sh --dry-run >/dev/null
python3 infra/test_infra.py
python3 infra/test_releases.py
if command -v shellcheck >/dev/null; then
  shellcheck infra/*.sh scripts/deploy.sh scripts/rollback.sh
else
  echo 'shellcheck unavailable; bash syntax checks still required'
fi
echo 'Infrastructure acceptance checks passed'
