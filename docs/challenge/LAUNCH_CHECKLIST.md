# Launch checklist (go-live order)

Times are relative to the competition start `window_start` (config; default 2026-10-12 20:00 ET) and freeze `window_end`
(2026-10-18 23:59:59 ET). Do not tick a box without running its verify command. "EC2" commands run over SSH on the host
(RUNBOOK "Secrets and bootstrap"). `$DOMAIN` is your HTTPS host from HUMAN_TASKS 5.

## T-48h: infrastructure and data
- [ ] AWS SSO works. Verify: `aws sts get-caller-identity --profile brodie`
- [ ] EC2 provisioned. Verify: `bash infra/provision.sh --dry-run` shows no changes, and `ssh -i ~/.ssh/id_ed25519 ubuntu@$PUBLIC_IP true`
- [ ] Secrets in SSM (RUNBOOK). Verify: `aws ssm get-parameters-by-path --path /brodie/challenge/ --query 'Parameters[].Name' --profile brodie` lists LIVEKIT_*, AGENT_NAME, SUPABASE_*, GEMINI_API_KEY, DISPATCHER_TOKEN, SUPABASE_DB_URL, BACKUP_BUCKET, ALERT_EMAIL, SES_FROM_EMAIL
- [ ] Bootstrap + Chert login done. Verify (EC2): `sudo python3 /opt/brodie/current/infra/with-env.py runuser -u brodie -- chert doctor`
- [ ] Migrations applied to Supabase. Verify: `psql "$SUPABASE_DB_URL" -c "select count(*) from competition_config"` (non-zero) and `psql "$SUPABASE_DB_URL" -c "select * from schema_migrations"` lists every file in `db/migrations/`
- [ ] First deploy. Verify (EC2): `sudo systemctl status brodie-worker chert-agent brodie-dispatcher --no-pager` all active; `curl --fail https://$DOMAIN/health` returns `"ok": true`
- [ ] Vercel site deployed with env vars (HUMAN_TASKS 4). Verify: open `/`, `/rules`, `/setup`, `/join`
- [ ] Supabase email template, Site URL, SMTP set (HUMAN_TASKS 3b-3d). Verify: request an admin code at `/admin/login`; the email has a 6-digit code and a confirm link
- [ ] Admin emails seeded (HUMAN_TASKS 6). Verify: `PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py --emails you@example.com --actor you@example.com --reason check --dry-run` prints `already admin: you@example.com`

## T-36h: judge and flags
- [ ] Clip set recorded and ship gate passes (HUMAN_TASKS 10). Verify: `PYTHONPATH=src:. .venv/bin/python -m judge_eval.run --bench; echo exit=$?` prints `exit=0`. If exit=1/INCOMPLETE, written go/no-go decision recorded in `BLOCKERS.md` B3
- [ ] Cue audio rendered and on EC2 (HUMAN_TASKS 11). Verify: `PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --backend gemini --dry-run` lists nothing missing
- [ ] Chert flags decided (HUMAN_TASKS 2, 13). Verify: `curl -s https://$DOMAIN/health` shows the five flags and any `fallbacks` you accept
- [ ] Config values set: `brodie_number`, `team_alert_handles`, `site_url`, `first_prize`, `ufc_fighter` (HUMAN_TASKS 7-9). Verify (psql): `SELECT ch_config_get();`
- [ ] Offline test suites green. Verify: `PYTHONPATH=src:. .venv/bin/python -m pytest -q -p no:cacheprovider tests/challenge infra`

## T-24h: rehearsal
- [ ] Live testers complete the scripted flow (HUMAN_TASKS 12), including a real FaceTime call that counts, ends at 3:15, and produces a result text/link
- [ ] Alert drill passes (RUNBOOK "Monitoring and alert drills"). Verify (EC2): `sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/alert.sh 'Planned alert drill'` reaches email/handles
- [ ] Backup and restore rehearsal passes (RUNBOOK). Verify (EC2): `sudo systemctl start brodie-backup.service` then `sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/restore_test.sh`
- [ ] healthchecks.io pings green. Verify in the dashboard: both checks "up"
- [ ] Test data cleaned out before launch. Verify (psql): `select count(*) from calls` is 0 or only expected rows; void or remove tester calls through the audited admin RPCs (RUNBOOK "Live configuration and moderation")

## T-1h to T-0
- [ ] Line state idle. Verify: `curl -s https://$DOMAIN/health` shows `line_states` idle and `"ok": true`
- [ ] Registration open, not frozen. Verify (psql): `SELECT ch_config_get();` has `registration_open` true and `competition_frozen` false
- [ ] Deploy hold: no deploys during the week unless following RUNBOOK. Verify: `bash scripts/deploy.sh --dry-run` only prints the plan
- [ ] Announce: share the site link and Brodie's number

## During the week (daily)
- [ ] Morning: `curl -s https://$DOMAIN/health`; `/admin` health page shows recent heartbeats
- [ ] Check logs (EC2): `sudo journalctl -u brodie-worker -u chert-agent -u brodie-dispatcher --since '-24 hours' --no-pager | grep -i error`
- [ ] Reconciler timer firing (EC2): `sudo systemctl list-timers 'brodie-*'`
- [ ] Review rejected-rep complaints in `/admin`; use void/adjust with a written reason (RUNBOOK)
- [ ] Backup ran (EC2): `sudo journalctl -u brodie-backup -n 30 --no-pager`
- [ ] Sunday 20:00 ET "ending soon" text expected; verify in `/admin` messages (needs a real provider)
- [ ] Chert token expiry: confirm `CHERT_TOKEN_EXPIRES_AT` is after Sunday (RUNBOOK "Restart, logs and line recovery")

## After the freeze (Sun 2026-10-18 23:59:59 ET)
- [ ] Scoring frozen. Verify (psql): `SELECT ch_config_get();` shows `competition_frozen` true (set it with `ch_config_set` if the job did not: RUNBOOK) and the site shows "FINAL - pending verification"
- [ ] No open calls. Verify: `curl -s https://$DOMAIN/health` line states are idle/offline
- [ ] Rejudge dry run, review, apply only if approved (RUNBOOK "Live configuration and moderation")
- [ ] Top 3 verification call completed before payout
- [ ] Final backup taken and restore-tested; export the audit log; delete tester data; shut down EC2 or keep per your decision
