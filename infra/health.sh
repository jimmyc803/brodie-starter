#!/usr/bin/env bash
set -euo pipefail
for ((attempt = 1; attempt <= 30; attempt++)); do
  if curl --fail --silent --max-time 5 http://127.0.0.1:8080/health | python3 -c 'import json,sys; h=json.load(sys.stdin); sys.exit(0 if h.get("ok") is True and h.get("db") not in (False,None,"error","down") else 1)' 2>/dev/null; then
    echo 'Dispatcher health passed'
    exit 0
  fi
  sleep 3
done
echo 'Dispatcher health failed; inspect journal and run rollback.sh if appropriate' >&2
exit 1
