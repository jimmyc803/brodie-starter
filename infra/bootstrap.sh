#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run as root' >&2; exit 1; }
: "${REPO_URL:?Git clone URL required}" "${PUBLIC_IP:?Elastic IP required}"
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}
SSM_PREFIX=${SSM_PREFIX:-/brodie/challenge/}
export DEBIAN_FRONTEND=noninteractive
apt-get update
# Supabase runs Postgres 17; Ubuntu 24.04 ships 16, whose pg_dump refuses a newer server. Use the PGDG repo.
apt-get install -y postgresql-common
/usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
apt-get install -y git curl ca-certificates unzip python3 python3-venv postgresql-client-17 postgresql-17 caddy xz-utils jq libportaudio2 libglib2.0-0 libgl1
id brodie >/dev/null 2>&1 || useradd --create-home --shell /bin/bash brodie
install -d -m 0755 -o brodie -g brodie /opt/brodie
install -d -m 0700 /etc/brodie /var/lib/brodie
if [[ ! -d /opt/brodie/.git ]]; then
  runuser -u brodie -- git clone "$REPO_URL" /opt/brodie
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
if ! command -v aws >/dev/null; then
  curl --fail --silent --show-error --location https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip -o "$tmp/aws.zip"
  unzip -q "$tmp/aws.zip" -d "$tmp"
  "$tmp/aws/install"
fi
python3 -m venv /opt/uv
/opt/uv/bin/pip install uv
ln -sf /opt/uv/bin/uv /usr/local/bin/uv
# Chert requires Node 22.23.2 or 24.x; Ubuntu's Node 18 is too old.
curl --fail --silent --show-error --location https://nodejs.org/dist/v24.9.0/node-v24.9.0-linux-x64.tar.xz -o "$tmp/node-v24.9.0-linux-x64.tar.xz"
curl --fail --silent --show-error --location https://nodejs.org/dist/v24.9.0/SHASUMS256.txt -o "$tmp/SHASUMS256.txt"
(cd "$tmp" && grep ' node-v24.9.0-linux-x64.tar.xz$' SHASUMS256.txt | sha256sum --check -)
tar -xJf "$tmp/node-v24.9.0-linux-x64.tar.xz" --strip-components=1 -C /usr/local
npm install -g @trychert/facetime@0.1.0-beta.4
umask 077
aws ssm get-parameters-by-path --path "$SSM_PREFIX" --with-decryption --recursive --output json >"$tmp/params.json"
python3 - "$tmp/params.json" <<'PY'
import json, os, pathlib, re, sys
params = json.loads(pathlib.Path(sys.argv[1]).read_text())['Parameters']
if not params:
    raise SystemExit('SSM prefix contains no parameters; refusing an empty env')
entries = {}
for param in params:
    key, value = param['Name'].rsplit('/', 1)[-1], param['Value']
    if not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or any(c in value for c in '\r\n\0') or key in entries:
        raise SystemExit('Invalid, multiline, or duplicate SSM environment key')
    entries[key] = value
required = {'DISPATCHER_TOKEN', 'SUPABASE_DB_URL', 'BACKUP_BUCKET', 'ALERT_EMAIL', 'SES_FROM_EMAIL', 'AGENT_NAME'}
if not required <= entries.keys():
    raise SystemExit('Missing SSM keys: ' + ', '.join(sorted(required - entries.keys())))
target = pathlib.Path('/etc/brodie/env.new')
with target.open('w') as f:
    for key, value in sorted(entries.items()):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"')
        f.write(f'{key}="{escaped}"\n')
target.chmod(0o600)
os.replace(target, '/etc/brodie/env')
PY
python3 /opt/brodie/infra/backup_env.py
install -m 0644 /opt/brodie/infra/systemd/* /etc/systemd/system/
domain=${DOMAIN:-${PUBLIC_IP}.sslip.io}
[[ $domain =~ ^[a-zA-Z0-9.-]+$ ]] || { echo 'Invalid DOMAIN' >&2; exit 2; }
sed "s/CHALLENGE_DOMAIN/$domain/g" /opt/brodie/infra/Caddyfile >/etc/caddy/Caddyfile
chmod 0644 /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile
curl --fail --silent --show-error --location https://amazoncloudwatch-agent.s3.amazonaws.com/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb -o "$tmp/cloudwatch.deb"
dpkg -i "$tmp/cloudwatch.deb"
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s -c file:/opt/brodie/infra/cloudwatch-agent.json
systemctl daemon-reload
systemctl enable caddy brodie-worker chert-agent brodie-dispatcher brodie-heartbeat-check brodie-reconciler.timer brodie-backup.timer
systemctl restart caddy
echo 'Bootstrap complete. Run Chert device login, then deploy using RUNBOOK.md before starting application services.'
