#!/usr/bin/env bash
set -euo pipefail
message=${1:-Brodie infrastructure alert}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
chmod 700 "$tmp"
python3 - "$message" "$tmp" <<'PY'
import json, pathlib, sys
message, root = sys.argv[1], pathlib.Path(sys.argv[2])
(root / 'alert.json').write_text(json.dumps({'component': 'infra', 'message': message}))
(root / 'email.json').write_text(json.dumps({'Subject': {'Data': 'Brodie infrastructure alert'}, 'Body': {'Text': {'Data': message}}}))
PY
if [[ -n ${DISPATCHER_TOKEN:-} ]] && curl --fail --silent --show-error --max-time 10 \
  -H "X-Brodie-Token: $DISPATCHER_TOKEN" -H 'Content-Type: application/json' \
  --data-binary "@$tmp/alert.json" http://127.0.0.1:8080/internal/alert >/dev/null; then
  exit 0
fi
: "${ALERT_EMAIL:?team email required}" "${SES_FROM_EMAIL:?verified SES sender required}"
aws ses send-email --from "$SES_FROM_EMAIL" --destination "ToAddresses=$ALERT_EMAIL" --message "file://$tmp/email.json" >/dev/null
