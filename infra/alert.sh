#!/usr/bin/env bash
set -euo pipefail
message=${1:-Brodie infrastructure alert}
# Optional check name. It reaches the dispatcher as the alert kind, which is part of the dedupe key, so two
# different host problems inside one dedupe window are two texts instead of one.
kind=${2:-infra}
[[ $kind =~ ^[A-Za-z0-9_.:@/-]{1,64}$ ]] || kind=infra
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
chmod 700 "$tmp"
python3 - "$message" "$tmp" "$kind" <<'PY'
import json, pathlib, sys
message, root, kind = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3]
(root / 'alert.json').write_text(json.dumps({'component': kind, 'message': message}))
(root / 'email.json').write_text(json.dumps({'Subject': {'Data': f'Brodie infrastructure alert [{kind}]'}, 'Body': {'Text': {'Data': message}}}))
PY
if [[ -n ${DISPATCHER_TOKEN:-} ]] && curl --fail --silent --show-error --max-time 10 \
  -H "X-Brodie-Token: $DISPATCHER_TOKEN" -H 'Content-Type: application/json' \
  --data-binary "@$tmp/alert.json" http://127.0.0.1:8080/internal/alert >/dev/null; then
  exit 0
fi
: "${ALERT_EMAIL:?team email required}" "${SES_FROM_EMAIL:?verified SES sender required}"
aws ses send-email --from "$SES_FROM_EMAIL" --destination "ToAddresses=$ALERT_EMAIL" --message "file://$tmp/email.json" >/dev/null
