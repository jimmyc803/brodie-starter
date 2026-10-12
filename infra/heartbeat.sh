#!/usr/bin/env bash
set -euo pipefail
cd /opt/brodie
while true; do
  if ! /opt/brodie/.venv/bin/python infra/monitor.py; then
    bash infra/alert.sh 'Heartbeat monitor failed; inspect brodie-heartbeat-check journal' || echo 'Alert delivery failed' >&2
  fi
  sleep 60
done
