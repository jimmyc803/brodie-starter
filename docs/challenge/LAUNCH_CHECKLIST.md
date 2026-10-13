# Launch checklist (go-live order)

Times are relative to the competition start `window_start` (config; default 2026-10-12 20:00 ET) and freeze `window_end`
(2026-10-18 23:59:59 ET). Status 2026-10-13: the system is LIVE (site https://brodie-pushups.vercel.app, dispatcher
https://3.13.177.157.sslip.io, EC2 `i-0d098dcf3948886ce`, region us-east-2, AWS profile `beatmuse`). Boxes below marked
(done) were verified live; the rest are still to do. Do not tick a box without running its verify command. "EC2" commands run over SSH on the host
(RUNBOOK "Secrets and bootstrap"). `$DOMAIN` is `3.13.177.157.sslip.io`.

## T-48h: infrastructure and data
- [x] (done) AWS access works. Verify: `aws sts get-caller-identity --profile beatmuse`
- [x] (done) EC2 provisioned. Verify: `bash infra/provision.sh --dry-run` shows no changes, and `ssh -i ~/.ssh/id_ed25519 ubuntu@$PUBLIC_IP true`
- [x] (done) Secrets in SSM (RUNBOOK). Verify: `aws ssm get-parameters-by-path --path /brodie/challenge/ --query 'Parameters[].Name' --profile beatmuse` lists LIVEKIT_*, AGENT_NAME, SUPABASE_*, GEMINI_API_KEY, DISPATCHER_TOKEN, SUPABASE_DB_URL, BACKUP_BUCKET, ALERT_EMAIL, SES_FROM_EMAIL
- [x] (done) Bootstrap + Chert login done. Verify (EC2): `sudo python3 /opt/brodie/current/infra/with-env.py runuser -u brodie -- chert doctor`
- [x] (done) Migrations applied to Supabase (by hand: `supabase --linked` as owner; config via `supabase db query --linked`, since `brodie_ops` cannot write `competition_config`). Verify: `psql "$SUPABASE_DB_URL" -c "select count(*) from competition_config"` (non-zero) and `psql "$SUPABASE_DB_URL" -c "select * from schema_migrations"` lists every file in `db/migrations/`
- [x] (done) First deploy (live release `4c08082`). Verify (EC2): `sudo systemctl status brodie-worker chert-agent brodie-dispatcher brodie-reconciler.timer --no-pager` all active; `curl --fail https://$DOMAIN/health` returns `"ok": true`
- [x] (done) Vercel site deployed with env vars (HUMAN_TASKS 4). Verify: open `/`, `/rules`, `/setup`, `/join`
- [ ] Supabase email template and Site URL done; custom SMTP NOT done (built-in email sends about 2 per hour; SES still in sandbox, B2). Until SMTP works, people join by iMessage text. Verify once SMTP is set: request an admin code at `/admin/login`; the email has a 6-digit code and a confirm link
- [ ] Admin emails seeded (check they are still right) (HUMAN_TASKS 6). Verify: `PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py --emails you@example.com --actor you@example.com --reason check --dry-run` prints `already admin: you@example.com`

## T-36h: judge and flags
- [ ] Ship gate: the j3 real-clip check passes, or the owner accepts launching without it (note it in `DECISIONS.md`). The judge is lenient j3 and the liveness cheater test is OFF (`liveness_enabled` false in `judge_thresholds`, D-34). Verify live config: `supabase db query --linked "select ch_config_get()->'judge_thresholds'"` shows `liveness_enabled` false. Verify gate: `JUDGE_EVAL_CLIPS=... JUDGE_EVAL_LABELS=... PYTHONPATH=src:. .venv/bin/python -m pytest judge_eval/check_real_clips.py` (it fails, not skips, without clips; HUMAN_TASKS 10)
- [ ] Cue bank v2 rendered and on EC2 (HUMAN_TASKS 11). Verify: `env -u GEMINI_BASE_URL PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --bank v2 --dry-run` lists nothing missing, and `/opt/brodie/data/cues_audio_v2` exists on EC2
- [x] (done) Chert flags set: `MESSAGING_PROVIDER=chert`, `CALLER_ID_SOURCE=claim_window`, `HANGUP_MODE=unverified`, `REVEAL_MODE=audio_only`. `HANGUP_MODE=chert_api` is held until inbound FaceTime works and one test call ends cleanly. Verify: `curl -s https://$DOMAIN/health` shows the five flags and any `fallbacks` you accept
- [ ] Config values set (`team_alert_handles` done): `brodie_number` ((628) 246-3964), `team_alert_handles`, `site_url`, `first_prize`, `ufc_fighter` (HUMAN_TASKS 7-9). Verify (psql): `SELECT ch_config_get();`
- [ ] Offline test suites green. Verify: `PYTHONPATH=src:. .venv/bin/python -m pytest -q -p no:cacheprovider tests/challenge infra scripts/harness` (about 1040 passed; `test_scheduler_state_machine[1-line]` is known flaky, rerun it)

## T-24h: rehearsal
- [ ] Inbound FaceTime works again (open incident B1). Verify: one real call from a tester reaches the worker and `chert-agent` logs it
- [ ] Live testers complete the scripted flow (HUMAN_TASKS 12), including a real FaceTime call that counts, ends at 3:15, and produces a result text/link
- [ ] Alert drill passes (RUNBOOK "Monitoring and alert drills"). Verify (EC2): `sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/alert.sh 'Planned alert drill'` reaches email/handles
- [ ] Backup and restore rehearsal passes (RUNBOOK). Verify (EC2): `sudo systemctl start brodie-backup.service` then `sudo python3 /opt/brodie/current/infra/with-env.py bash /opt/brodie/current/infra/restore_test.sh`
- [ ] healthchecks.io pings green. Verify in the dashboard: both checks "up"
- [ ] Test data cleaned out before the public push (B3). Verify (psql): `select count(*) from calls` is 0 or only expected rows; void or remove tester calls through the audited admin RPCs (RUNBOOK "Live configuration and moderation")

## T-1h to T-0
- [ ] Line state idle. Verify: `curl -s https://$DOMAIN/health` shows `line_states` idle and `"ok": true`
- [ ] Registration open, not frozen. Verify (psql): `SELECT ch_config_get();` has `registration_open` true and `competition_frozen` false
- [ ] Deploy hold: no deploys during the week unless following RUNBOOK. Verify: `bash scripts/deploy.sh --dry-run` only prints the plan
- [ ] Announce: share the site link and Brodie's number

## During the week (daily)
- [ ] Morning: `curl -s https://$DOMAIN/health`; `/admin` health page shows recent heartbeats
- [ ] Check logs (EC2): `sudo journalctl -u brodie-worker -u chert-agent -u brodie-dispatcher --since '-24 hours' --no-pager | grep -i error`
- [ ] Reconciler timer firing every 60 s (EC2): `sudo systemctl list-timers 'brodie-reconciler*'` and `sudo journalctl -u brodie-reconciler --since '-10 min' --no-pager | tail`; no `commit_conflict` alerts
- [ ] Review rejected-rep complaints in `/admin`; use void/adjust with a written reason (RUNBOOK)
- [ ] Backup ran (EC2): `sudo journalctl -u brodie-backup -n 30 --no-pager`
- [ ] Sunday 20:00 ET "ending soon" text expected; verify in `/admin` messages (provider is Chert iMessage)
- [ ] Chert token expiry: confirm `CHERT_TOKEN_EXPIRES_AT` is after Sunday (RUNBOOK "Restart, logs and line recovery")

## After the freeze (Sun 2026-10-18 23:59:59 ET)
- [ ] Scoring frozen. Verify (psql): `SELECT ch_config_get();` shows `competition_frozen` true (set it with `ch_config_set` if the job did not: RUNBOOK) and the site shows "FINAL - pending verification"
- [ ] No open calls. Verify: `curl -s https://$DOMAIN/health` line states are idle/offline
- [ ] Rejudge dry run, review, apply only if approved (RUNBOOK "Live configuration and moderation")
- [ ] Top 3 verification call completed before payout
- [ ] Final backup taken and restore-tested; export the audit log; delete tester data; shut down EC2 or keep per your decision

## Pre-launch tester reset: KEEP these participants (owner instruction, 2026-10-13)
Any reset or wipe of tester data must exclude these users (their clients row, challenge stats, calls, queue and messages):
- `7dea8571-7a70-40a9-a95b-1c3088b8e822` (display name Benjamin_Friedman)
- `db6678e1-44c7-479f-ad4d-17a708f06207` (display name ethan)
The reset itself still needs the owner's explicit go-ahead.
