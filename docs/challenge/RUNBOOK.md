# Brodie challenge operations

Target: Ubuntu 24.04 amd64 in us-east-1, Python 3.12, Node 24, Chert CLI
0.1.0-beta.4. Use c7i.xlarge first. Benchmark a real three-minute call for
frame throughput, processing latency and memory before considering g4dn; GPU
instances also need a separately validated driver/CUDA installation.

## Provision

Run from the repository on an operator machine with AWS CLI v2 and Python 3.
The provisioning identity needs EC2, IAM, SSM, S3, SNS and CloudWatch management
permissions. Runtime credentials come from the instance role, never static AWS
keys. The script reconciles only the security group it owns; keep other workloads
out of that group. Existing SSH rules outside TEAM_SSH_CIDRS will be removed.

```bash
export AWS_DEFAULT_REGION=us-east-1
export TEAM_SSH_CIDRS='203.0.113.10/32,203.0.113.11/32' # replace with team egress IPs
export SSH_PUBLIC_KEY_FILE="$HOME/.ssh/id_ed25519.pub"
export BACKUP_BUCKET='your-unique-brodie-backups'
export ALERT_EMAIL='ops@your-domain.example'
export INSTANCE_TYPE=c7i.xlarge
bash infra/provision.sh --dry-run
bash infra/provision.sh
```

This imports the public key (never a private key), reuses named resources,
resolves Canonical's Ubuntu AMI through SSM, encrypts the root volume, requires
IMDSv2 and attaches an Elastic IP. Set VPC_ID and SUBNET_ID for a non-default VPC;
the subnet needs Internet routing for downloads and outbound Chert/LiveKit.
Only TCP 443 is public; SSH is limited to the supplied CIDRs. Retain the private
key locally. Confirm the SNS email subscription after provisioning.

## Secrets and bootstrap

Create SecureString parameters under `/brodie/challenge/`. The instance role
can read only that prefix and access only the backup bucket; optionally set
SSM_KMS_KEY_ARN when provisioning if using a customer-managed KMS key.
Supply these names with real values through AWS Console Parameter Store or
this prompt-based command (no secret values in shell history):

```bash
read -r -p 'Parameter name: ' PARAM_NAME
read -r -s -p 'Parameter value: ' PARAM_VALUE; echo
printf '%s' "$PARAM_VALUE" | aws ssm put-parameter \
  --name "/brodie/challenge/$PARAM_NAME" --type SecureString \
  --value file:///dev/stdin --overwrite >/dev/null
unset PARAM_VALUE
```

Required application names: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET,
AGENT_NAME (nonempty assigned dispatch name), SUPABASE_URL,
SUPABASE_SERVICE_ROLE_KEY, GEMINI_API_KEY, DISPATCHER_TOKEN and SUPABASE_DB_URL.
Use a direct/session database connection suitable for migrations and pg_dump,
not a transaction-mode pooler. Also set BACKUP_BUCKET, AWS_DEFAULT_REGION,
ALERT_EMAIL and SES_FROM_EMAIL. Verify the SES sender and, while in the SES
sandbox, the recipient in the same region.

Set CHALLENGE_MODE=competition, LINE_ID to the seeded line, and DISPATCHER_URL
to `http://127.0.0.1:8080`. Choose C4 flags after live discovery: CALLER_ID_SOURCE
(default claim_window), MESSAGING_PROVIDER (default mock), HANGUP_MODE
(default unverified), REVEAL_MODE (audio_only), CARD_DELIVERY (link).
Optional LINE_OFFLINE_GAP_S and OUTBOUND_RATE_PER_MIN override defaults.
A live launch must explicitly review mock/web_only mode and hangup behavior.
Do not copy empty `.env.example` assignments to SSM: empty values are not defaults.

```bash
export PUBLIC_IP='your-elastic-ip'
scp -i "$HOME/.ssh/id_ed25519" infra/bootstrap.sh ubuntu@"$PUBLIC_IP":/tmp/bootstrap.sh
ssh -i "$HOME/.ssh/id_ed25519" ubuntu@"$PUBLIC_IP"
sudo env REPO_URL='https://your-repository-url' PUBLIC_IP='your-elastic-ip' \
  AWS_DEFAULT_REGION=us-east-1 bash /tmp/bootstrap.sh
sudo -u brodie -H bash -c 'cd /opt/brodie && chert login --device'
```

Private repositories need a read-only deploy key configured for brodie before
cloning. Bootstrap installs dependencies, clones `/opt/brodie`, fetches SSM into
root-owned `/etc/brodie/env` and filtered `/etc/brodie/backup-env` mode 0600,
installs units and CloudWatch agent, and enables services for boot. It deliberately leaves application startup to deploy
after login and migrations. Secrets must be single-line values; duplicate leaf
names under the SSM prefix are rejected. Never source or print the env file;
`infra/with-env.py` parses assignments without executing shell content.

Set DOMAIN at bootstrap for an owned DNS name pointing at the EIP; otherwise
Caddy uses `<EIP>.sslip.io`. Caddy uses TLS-ALPN validation over 443 (port 80 is
closed). DNS resolution, CA issuance/rate limits, and approval to use sslip.io
are launch blockers until HTTPS is verified. `/internal/*` is blocked publicly;
other dispatcher routes retain application token/webhook validation.

## Deploy and rollback

The base `db/schema.sql` must already be installed in Supabase. Deploy then
applies all `db/migrations/*.sql` in lexical order using psql ON_ERROR_STOP,
a session advisory lock and `public.schema_migrations` checksums. Existing
migrations are idempotent; previously applied files must never be edited.
Deployment and rollback share a host lock. The checkout at `/opt/brodie` is
only the Git source; deploy fetches its branch from origin without modifying it.
Each SHA is exported to `/opt/brodie/releases/<sha>` with its own virtualenv.
Dependency installation, dependency checks and migrations finish before stopping
services. Migrations must therefore work with both the running and new code.
The integration branch must include the challenge package, reconciler and
required dispatcher dependencies in requirements.txt.

Before stopping the worker or dispatcher, both scripts poll local `/health`
until no lines are `in_call` or `claimed`. Unhealthy, unreachable or unrecognized
health responses fail closed. `DEPLOY_HOLD_MAX_S` defaults to 300 seconds;
timeout aborts without stopping services unless `--force` was supplied. Force
permits interruption after the timeout; it does not make active calls safe.
Close admission in a maintenance window before deploying: this check does not
lock out new claims arriving between the final poll and shutdown. A hold abort
can leave compatible migrations already applied.

```bash
bash scripts/deploy.sh --dry-run # safe on an operator laptop, no credentials
# Initial bootstrap only: no dispatcher exists to answer health yet.
sudo env DEPLOY_HOLD_MAX_S=0 python3 /opt/brodie/infra/with-env.py \
  bash /opt/brodie/scripts/deploy.sh --force
# Subsequent deployments use the tooling from the active release:
sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/scripts/deploy.sh
sudo systemctl status brodie-worker chert-agent brodie-dispatcher --no-pager
curl --fail https://your-domain/health
# Restore the previous release, without rebuilding dependencies:
sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/scripts/rollback.sh
# Emergency override (may interrupt calls), after reviewing the incident:
sudo env DEPLOY_HOLD_MAX_S=0 python3 /opt/brodie/current/infra/with-env.py \
  bash /opt/brodie/current/scripts/rollback.sh --force
```

Activation atomically renames a staged symlink onto `/opt/brodie/current`,
installs release units and restarts services. All units use `current`; releases
share `/opt/brodie/data` through a symlink so checkpoints survive switches.
Successful deployments keep five completed releases, protecting the active and
previous releases. An interrupted build is removed; after a host crash, inspect
and remove an incomplete release directory before retrying its SHA.

The previous release SHA lives at `/var/lib/brodie/previous-sha`; a healthy SHA
is recorded in `deployed-sha`. Health must report an operational dispatcher/DB
within 30 retries. Failed activation may leave services stopped or unhealthy;
inspect logs and explicitly roll back. Rollback switches to the recorded release
and its existing virtualenv and units, retains database migrations, checks health
and records the release it replaced as the new rollback target. The first deploy
has no previous release, including when converting the old in-place layout;
perform that conversion in a maintenance window. No automatic DB rollback occurs.
Only backwards-compatible migrations permit safe code rollback; destructive DB
recovery requires a separately reviewed restore.

## Restart, logs and line recovery

```bash
sudo systemctl restart brodie-worker chert-agent brodie-dispatcher
sudo journalctl -u brodie-worker -u chert-agent -u brodie-dispatcher --since '-15 minutes' --no-pager
sudo systemctl list-timers 'brodie-*'
sudo python3 /opt/brodie/current/infra/with-env.py runuser -u brodie -- chert doctor
sudo systemctl start brodie-reconciler.service
sudo journalctl -u brodie-reconciler -n 50 --no-pager
```

For “line down?”, inspect `/health` line_states, Chert doctor, credentials and
AGENT_NAME/LINE_ID mapping first. A normal post-call offline window is 180s by
default. The dispatcher tick recovers expired claims/calls; do not directly
rewrite line_state while a worker may still be active. After worker recovery,
the reconciler timer processes local checkpoints every minute. Preserve
`/opt/brodie/data/tmp/sessions` during incident response. For token expiry,
repeat `chert login --device` as brodie, update CHERT_TOKEN_EXPIRES_AT (ISO-8601
with timezone) in SSM, refresh secrets, and restart Chert. Login/registration
must be confirmed by a real call before reopening the competition.

## Monitoring and alert drills

Create two healthchecks.io checks, period 60s with suitable grace (at least
120s), and set HC_WORKER_URL and HC_DISPATCHER_URL to their secret ping URLs.
Configure healthchecks.io email escalation independently of EC2 so total host
loss still alerts. Every monitor cycle checks dispatcher/DB, service state and
read-only Chert doctor before sending success. Worker ping body includes
`line registered with Chert`; doctor is a CLI health signal, and a live call
is still required to validate routing. Slow dependencies can lengthen a cycle.

The host monitor alerts on service restart spikes (three per minute), stuck
line_state, failed outbound messages (default five in five minutes, override
OUTBOUND_FAILURE_ALERT_COUNT), stale DB heartbeat records, dispatcher/worker
failure, and token expiry within 24h (or unknown expiry). The local
`/internal/alert` endpoint receives `{component,message}` with X-Brodie-Token;
if unavailable/non-2xx, SES email is the fallback. Until that application
endpoint is integrated, SES is the delivery path. Configure team_alert_handles
through the audited config RPC for the messaging adapter.

CloudWatch alarms cover EC2 CPU >=85%, status failure >=1, memory/disk >=85%
for three minutes, including missing metrics. Check CWAgent InstanceId
aggregates and confirm SNS subscription. Long-running services auto-restart
at 3s with no start-rate limit; OnFailure handles terminal failures and the
monitor catches crash loops. Timer services use Restart=on-failure because
systemd rejects Restart=always for Type=oneshot. Journald holds service logs.

```bash
sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/alert.sh 'Planned alert drill'
sudo systemctl kill --signal=SIGKILL brodie-worker
sleep 5
sudo systemctl show brodie-worker -p ActiveState -p NRestarts
sudo journalctl -u brodie-heartbeat-check --since '-5 minutes' --no-pager
sudo reboot
# Reconnect and confirm services, /health, doctor, timers and both external pings.
```

Do drills with no live contestants. Verify fallback email by stopping the
dispatcher during the planned window and running the alert command again.
Restore services afterward. A one-off crash may auto-recover without a terminal
OnFailure; use the explicit alert drill to test delivery.

## Backup and restore rehearsal

The backup unit runs as `brodie`. Systemd reads root-owned 0600
`/etc/brodie/backup-env`, containing only SUPABASE_DB_URL, BACKUP_BUCKET and
optional AWS_DEFAULT_REGION; AWS credentials come from the instance role.
Bootstrap and deploy refresh this filtered file without exposing application keys.

Nightly at 03:00 UTC the backup timer streams a custom-format pg_dump through
gzip and uploads to `s3://BACKUP_BUCKET/YYYY/MM/DD/<UTC timestamp>.dump.gz`.
The bucket is private, encrypted and versioned. Dump/pipeline errors prevent
upload. Retention is intentionally operator-managed; versioning does not
replace a retention policy. Match PostgreSQL client/server versions to Supabase
before the first backup (pg_dump cannot dump a newer server).

```bash
sudo systemctl start brodie-backup.service
sudo journalctl -u brodie-backup -n 30 --no-pager
sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/restore_test.sh
```

The rehearsal downloads the newest archive, creates an isolated local cluster
with pg_virtualenv, restores with error-stop, counts clients/calls/reps/config/
line_state and requires nonempty config. The temporary cluster is removed on
exit; production is never a restore target. Full Supabase dumps may require
matching extension packages and additional managed roles on the scratch host;
install matching prerequisites before treating a restore as tested. Any missing
extension/role or incompatible dump fails visibly. This repository's offline
tests do not establish that a real Supabase archive restores: a successful
rehearsal is a mandatory deployment gate. Backups contain PII; restrict S3 and
host access and never paste dump contents into tickets.

## Live configuration and moderation

Use the audited RPCs, with operator identity and reason, rather than table
updates. Run an authenticated local psql session without credentials in argv:

```bash
sudo python3 /opt/brodie/current/infra/with-env.py bash -c 'export PGDATABASE="$SUPABASE_DB_URL"; exec psql -X -v ON_ERROR_STOP=1'
```

Then use these examples, replacing identifiers and reasons:

```sql
SELECT ch_config_get();
SELECT ch_config_set('daily_call_cap', '5'::jsonb, 'admin@example.com', 'approved cap');
SELECT ch_admin_ban('00000000-0000-0000-0000-000000000000'::uuid, 'reviewed abuse', 'admin@example.com');
SELECT ch_admin_unban('00000000-0000-0000-0000-000000000000'::uuid, 'appeal upheld', 'admin@example.com');
SELECT ch_admin_void_call('call-id', 'invalid setup reviewed', 'admin@example.com');
SELECT ch_config_set('competition_frozen', 'true'::jsonb, 'admin@example.com', 'early freeze approved');
```

Rejudge and raffle use C4 admin endpoints with an allowlisted admin email.
Load the token only inside the root environment wrapper:

```bash
sudo python3 /opt/brodie/current/infra/with-env.py bash -c 'curl --fail-with-body -sS \
 -H "X-Brodie-Token: $DISPATCHER_TOKEN" -H "X-Admin-Email: admin@example.com" \
 -H "Content-Type: application/json" -d '\''{"apply":false}'\'' \
 http://127.0.0.1:8080/admin/rejudge'
# Review the diff before repeating with apply:true.
sudo python3 /opt/brodie/current/infra/with-env.py bash -c 'curl --fail-with-body -sS \
 -H "X-Brodie-Token: $DISPATCHER_TOKEN" -H "X-Admin-Email: admin@example.com" \
 -H "Content-Type: application/json" -d '\''{"seed":"recorded-public-draw-seed"}'\'' \
 http://127.0.0.1:8080/admin/raffle'
```

Record the raffle seed and returned results. Freeze and settle all calls before
the official draw. Rejudge apply, bans, voids and freeze change contestant
outcomes; execute only the incident's approved action and retain the audit trail.

## Rotate keys

Update the relevant SSM SecureString using the prompt command above. In a
maintenance window rerun bootstrap with the same REPO_URL, PUBLIC_IP and DOMAIN
to atomically refresh `/etc/brodie/env`, then run deploy to restart all consumers.
For DISPATCHER_TOKEN rotate the website/server caller configuration in the same
window. Validate health and a test call before revoking the old upstream key.
Chert credentials live in brodie's home from device login; renew there, never as
root. Confirm `/etc/brodie/env` remains root:root 0600 with `sudo stat
/etc/brodie/env`. Do not display the file or journal secrets.

## Admin access and first-week quick reference

Add or confirm admins (writes `admin_allowlist` plus an audit row; safe to rerun; `--dry-run` previews):

```bash
export SUPABASE_DB_URL='postgresql://...'
PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py --emails alice@example.com,bob@example.com \
  --actor you@example.com --reason "launch admins"
```

Quick health view during the week:

```bash
curl -s https://YOUR-DOMAIN/health
sudo systemctl list-timers 'brodie-*'
sudo journalctl -u brodie-worker -u chert-agent -u brodie-dispatcher --since '-1 hour' --no-pager
```

## Launch and freeze references

Human setup steps: `docs/challenge/HUMAN_TASKS.md`. Ordered go-live list: `docs/challenge/LAUNCH_CHECKLIST.md`.
Open problems: `docs/challenge/BLOCKERS.md`. Judge ship gate: `PYTHONPATH=src:. .venv/bin/python -m judge_eval.run --bench`
(exit 0 only when it passes). Freeze early only with an approved reason:
`SELECT ch_config_set('competition_frozen', 'true'::jsonb, 'admin@example.com', 'reason');` (see "Live configuration and moderation").
