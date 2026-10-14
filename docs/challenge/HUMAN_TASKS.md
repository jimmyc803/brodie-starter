# Human tasks (things only a person can do)

Every item has: who, exact steps, where the value goes, and what it unblocks. Run commands from the repo root
(`cd /Users/stanley/brodie-rt-coach`) unless told otherwise. Never paste secrets into chat, tickets or git; secrets go to
AWS SSM Parameter Store (EC2) or Vercel/Supabase dashboards. Numbered items map to SPEC section 13.

Quick index: 1 AWS, 2 Chert login + James, 3 Supabase, 4 Vercel, 5 domain, 6 admins, 7 alert handles, 8 Brodie's number,
9 prizes, 10 judge clips, 11 cue audio, 12 testers, 13 Phase-2 test results, 14 FaceTime outage.

## Status on 2026-10-13 (the system is live)
| # | Item | Status |
|---|---|---|
| 1 | AWS | Done. EC2 `i-0d098dcf3948886ce` (m7i-flex.large, us-east-2), profile `beatmuse`, free plan with $100 credits. The `brodie` SSO profile and `brodie-challenge` account steps below are the original plan and were NOT used |
| 2 | Chert login, iMessage | Done. `MESSAGING_PROVIDER=chert`, project `2c765f80-02fb-4b0c-91ac-723ffece9006`, line (628) 246-3964, verified end to end. Open: decide `HANGUP_MODE=chert_api` after one test call |
| 3a-c | Supabase migrations, template, URLs | Done (migrations applied by hand; see 3a) |
| 3d | Custom SMTP | OPEN. Built-in email sends about 2 per hour; SES still in the sandbox. Until it is verified people join by iMessage text |
| 4, 5 | Vercel, sslip.io | Done: https://brodie-pushups.vercel.app and https://3.13.177.157.sslip.io |
| 7 | Alert handles | Done (one entry, the owner's number) |
| 9 | Prizes | 1st place plus top-3 group call with a UFC fighter (no raffle). OPEN: top-3 verification call and logistics |
| 10 | Judge clips | OPEN (optional): run the j3 real-clip gate or accept launching without it |
| 11 | Cue audio | Bank v2 rendered; re-render and rsync if the cue text changes |
| 12 | Live testers | Blocked by the FaceTime outage (14); remove tester data before the public push |
| 14 | Inbound FaceTime outage | OPEN, upstream (Chert or the Mac owner) |

Note: in the AWS commands in this file, use `--profile beatmuse` and region `us-east-2`.

---

## 1. AWS account (SPEC 13: AWS creds/profile+region+perms)

Who: the friend who owns the AWS Organization (steps A-B) and you (steps C-F).
Unblocks: EC2 provisioning (`infra/provision.sh`), SSM secrets, S3 backups, CloudWatch, SES alert email.

Plan: you get your OWN member account inside your friend's AWS Organization, and sign in through IAM Identity Center (SSO).
No long-lived access keys are ever created.

A. Friend (management account, AWS Console):
1. Organizations > Add an AWS account > Create an AWS account. Name it `brodie-challenge`, give it an email you control.
2. IAM Identity Center > Enable (region us-east-1). Users > Add user (your email). Permission sets > Create
   `BrodieAdmin`. Pick the AWS managed policy `AdministratorAccess` for launch week (tighten afterwards), session 8 hours.
3. AWS accounts > select `brodie-challenge` > Assign users or groups > your user + `BrodieAdmin`.
4. Send you the SSO start URL (looks like `https://d-xxxxxxxxxx.awsapps.com/start`). You accept the invitation email and set an MFA device.
5. Credit sharing check: Billing and Cost Management > Billing preferences > "Credit sharing preferences". Confirm the
   `brodie-challenge` account is allowed to use the organization's credits (and that credits cover EC2/S3/SES). Write
   the answer in `docs/challenge/BLOCKERS.md` if credits do not apply.

B. Friend (optional but recommended): add a Service Control Policy denying regions other than us-east-1.

C. You (operator machine, needs AWS CLI v2: `aws --version`):
```
aws configure sso
```
Answer the prompts: SSO session name `brodie`; SSO start URL = the URL from step A4; SSO region `us-east-1`;
registration scopes `sso:account:access`; browser opens, approve; pick account `brodie-challenge` and role `BrodieAdmin`;
default client region `us-east-1`; output `json`; profile name `brodie`.
```
aws sso login --profile brodie
aws sts get-caller-identity --profile brodie
export AWS_PROFILE=brodie AWS_DEFAULT_REGION=us-east-1
```
The last `get-caller-identity` must print the `brodie-challenge` account id. Repeat `aws sso login --profile brodie` when the session expires.

D. You: set a budget alert (console is simplest): Billing and Cost Management > Budgets > Create budget > Cost budget,
monthly, amount e.g. USD 100, alert at 50% and 80% of actual spend to your email.

E. You: provision (see `docs/challenge/RUNBOOK.md`, "Provision" and "Secrets and bootstrap" for the full text):
```
export TEAM_SSH_CIDRS='YOUR.IP.ADDR/32'      # find yours: curl -s https://checkip.amazonaws.com
export SSH_PUBLIC_KEY_FILE="$HOME/.ssh/id_ed25519.pub"
export BACKUP_BUCKET='pick-a-globally-unique-name'
export ALERT_EMAIL='you@example.com'
export INSTANCE_TYPE=c7i.xlarge
bash infra/provision.sh --dry-run
bash infra/provision.sh
```
Values go to: environment variables for `provision.sh` (same names as in `.env.example`). Confirm the SNS subscription email.

F. You: SES sender: SES console (us-east-1) > Verified identities > verify `SES_FROM_EMAIL` and, while in the SES sandbox, `ALERT_EMAIL`.

Done when: `aws sts get-caller-identity --profile beatmuse` works and `bash infra/provision.sh` finishes.

---

## 2. Chert login on EC2 + James's questions (SPEC 13: Chert login + answers + iMessage creds)

Who: you (login), James at Chert (answers). Unblocks: the real FaceTime line on EC2, the CALLER_ID_SOURCE / MESSAGING_PROVIDER /
HANGUP_MODE / REVEAL_MODE / CARD_DELIVERY flags, live iMessage.

Login (after bootstrap, see RUNBOOK "Secrets and bootstrap"):
```
ssh -i "$HOME/.ssh/id_ed25519" ubuntu@"$PUBLIC_IP"
sudo -u brodie -H bash -c 'cd /opt/brodie && chert login --device'
```
Follow the device-login URL on your laptop. Credentials stay in brodie's home directory. Then set `CHERT_TOKEN_EXPIRES_AT`
(ISO-8601 with timezone, e.g. `2026-10-20T00:00:00-04:00`) in SSM (command in RUNBOOK "Secrets and bootstrap") so the
token-expiry alert works.

SET 2026-10-13 (DONE): `CHERT_TOKEN_EXPIRES_AT=2026-11-12T05:52:35Z`, read off the live credentials
(`expires_at`, epoch ms, in `/home/brodie/.chert/credentials.json`; `chert doctor` says the same thing as
"29 days left"). It is in SSM at `/brodie/challenge/CHERT_TOKEN_EXPIRES_AT` AND appended to `/etc/brodie/env`, because
the host's env file is only rewritten by bootstrap and the monitor reads it from there - setting only SSM would have
left the daily reminder running. The monitor was restarted and its process has the value. Do both again after the next
device login: the new expiry is 30 days out from the login, not from this date.

Send James these questions (answers decide the flags; until answered the safe defaults apply: D-07 in `DECISIONS.md`):
1. Does `chert_call` (the metadata at call start) include the caller's handle/phone/email? -> `CALLER_ID_SOURCE=chert_meta` if yes, else `claim_window`.
   ANSWERED 2026-10-13: Chert (Gary) will pass the caller's handle, but it is not shipped yet and has no date; James
   confirmed the bridge still gives only `call_id`. So `CALLER_ID_SOURCE` stays `claim_window` and D-23 stays dormant.
   Flip to `chert_meta` the day a real call arrives with a handle (nothing else to build; the path is already written
   and tested). Interim, as James suggested: Brodie asks for the caller's queue code at the top of the call (D-36).
2. Is there an iMessage API (send text, inbound webhook) on Brodie's number? Does an existing agent already handle inbound texts?
   If yes: need `CHERT_MSG_URL`, `CHERT_MSG_TOKEN`, `CHERT_WEBHOOK_SECRET` -> `MESSAGING_PROVIDER=chert`; otherwise `web_only` or `mock`.
   ANSWERED 2026-10-12: yes, Chert Messaging API (console.trychert.com/documentation, iMessage project
   3a00424c-c597-4f08-9b3b-4a6b3d3519f5; FaceTime project 2c765f80-02fb-4b0c-91ac-723ffece9006). Setup:
   put the project's signing secret in SSM `/brodie/challenge/CHERT_MSG_TOKEN` (SecureString), then
   `python3 scripts/chert_setup.py --subscribe` registers the webhook and stores `CHERT_WEBHOOK_SECRET`.
   `CHERT_MSG_URL` now defaults to the public API; `CHERT_TENANT` only for multi-tenant projects.
3. Does FaceTime hang up when the agent leaves the room? Is there an API to end a call? -> `HANGUP_MODE=leave_room|chert_api|unverified`.
   Answer from docs.trychert.com/facetime/calls-api: `POST /v1/calls/{id}/end` exists. To use it, create a project API key
   (Developer -> Project API keys, `facetime:write`) and put `CHERT_FACETIME_TOKEN` and `CHERT_PROJECT_ID` in SSM, then set
   `HANGUP_MODE=chert_api` (default stays `unverified` until a live call proves it). Caller identity: Chert exposes only
   `from_handle_hash` (no phone/email), so `CALLER_ID_SOURCE` stays `claim_window`.
4. How long is the line offline after a call? -> `LINE_OFFLINE_GAP_S` (default 180).
   ANSWERED 2026-10-13 (James): "a few minutes" while Chert resets the line, and calls in that gap just ring out.
   Our 180 s default matches; leave it unless real calls show a longer reset.
5. Can `chert dev --agent` run 24/7 on EC2? Token expiry? Is there a production mode?
6. Can we get more than one line? (Design already supports N lines via `LINE_ID`.)
7. What sent the earlier unprompted text from Brodie's number? Could it collide with ours?
8. Outbound iMessage rate limits? -> `OUTBOUND_RATE_PER_MIN`.
9. Can the agent publish video into the call (for the 15 s reveal)? -> `REVEAL_MODE=video|audio_only`.
10. Can we send image attachments over iMessage? -> `CARD_DELIVERY=attachment|link`.
11. Can the line place outbound FaceTime calls (so Brodie rings the person whose turn it is)?
    ANSWERED 2026-10-13 (Gary): yes - `POST /api/v1/calls` with `direction: "outbound"`, `mode: "customer_managed"`,
    `destination` + `destination_type` (`phone`|`email`), docs.trychert.com/facetime/outbound. Two catches that decide
    it for us: outbound is **audio only** (`media: {audio: true, video: false}`), so it cannot carry a judged push-up
    call, and it needs our own LiveKit room and agent (BYOR) rather than the Chert-managed warm room we use today.
    So it is not a replacement for calling in and not a way around B1 - at most an optional "you're up" voice nudge
    (D-37).
12. What happens to a second caller while the line is on a call?
    ANSWERED 2026-10-13 (James + Gary): the line takes one call at a time; other calls are just left ringing and never
    reach the worker. Open point: if no `call.incoming` fires for them, the "calling a busy line puts you in the queue"
    path (D-23) can never run for a second caller even once handles arrive - ask Chert whether a ringing-but-unanswered
    call produces a call record or webhook before relying on it.

Where the answers go: SSM parameters under `/brodie/challenge/` (names above; command in RUNBOOK), then redeploy (RUNBOOK
"Deploy and rollback"). `/health` echoes the active modes so you can confirm: `curl --fail https://YOUR-DOMAIN/health`.
Test items 1, 3, 4 yourself with `docs/challenge/HUMAN_TASKS_discover.md` (see section 13 below).

---

## 3. Supabase (SPEC 13: Supabase confirm)

Who: the Supabase project owner. Project: `beat-muse`. Unblocks: website login, realtime, all data.

### 3a. Apply migrations (needs `SUPABASE_DB_URL`)
Live note: migrations are applied by hand with `supabase --linked` as the project owner. The deploy role `brodie_ops` cannot write `competition_config`, so config changes go through `supabase db query --linked` (for example `select ch_config_set(...)`).

Migrations in `db/migrations/*.sql` run in name order. Deploys do this automatically (`scripts/deploy.sh`); for the very
first apply from your laptop use the Supabase SQL editor (paste each file in order) or psql:
```
export SUPABASE_DB_URL='postgresql://...'   # Supabase > Project Settings > Database > Connection string (Session pooler or direct)
for f in db/migrations/*.sql; do psql -X -v ON_ERROR_STOP=1 "$SUPABASE_DB_URL" -f "$f" || break; done
```
Do not use the transaction-mode pooler. Do not edit migration files that were already applied.

### 3b. Auth email template (exact)
Supabase Dashboard > Authentication > Emails > Templates. The admin login (`pushup-web/app/admin/auth/confirm/route.ts`)
needs the email to contain BOTH a confirm link built from the token hash and the 6-digit code. Edit the "Magic Link" template
(and the "Confirm signup" template if you see one) so the body is:
```html
<h2>Brodie admin sign-in</h2>
<p>Your 6-digit code: <strong>{{ .Token }}</strong></p>
<p>Or <a href="{{ .SiteURL }}/admin/auth/confirm?token_hash={{ .TokenHash }}&type=email">confirm sign-in</a>
   (open it in the same browser where you asked for the code).</p>
<p>If you did not request this, ignore this email.</p>
```
Subject: `Your Brodie admin sign-in code`. The link must use `{{ .TokenHash }}` (not `{{ .ConfirmationURL }}`).
The link only works in the browser that requested the code (login-nonce cookie); the 6-digit code works anywhere.

### 3c. Site URL and redirect allowlist
Authentication > URL Configuration:
- Site URL = your public site, e.g. `https://brodie-pushups.vercel.app` (or your domain). It fills `{{ .SiteURL }}` above.
- Redirect URLs: add `https://brodie-pushups.vercel.app/**` (and your custom domain with `/**`; add `http://localhost:3000/**` only for local testing).

### 3d. SMTP note
OPEN as of 2026-10-13: the built-in Supabase mailer sends about 2 emails per hour, so web sign-in cannot scale. SES SMTP is pending verification and the account is still in the SES sandbox; until it is out of the sandbox people join by iMessage text (`JOIN <name>`). For launch, configure
custom SMTP: Authentication > Emails > SMTP Settings (e.g. an SES SMTP user from section 1F, or Resend/Postmark), set a
verified sender address. Test by requesting an admin code and confirming it arrives within a minute.

### 3e. Keys
Project Settings > API: copy Project URL -> `SUPABASE_URL` (and Vercel `NEXT_PUBLIC_SUPABASE_URL`), anon key -> Vercel
`NEXT_PUBLIC_SUPABASE_ANON_KEY`, service_role key -> `SUPABASE_SERVICE_ROLE_KEY` (SSM and Vercel; never in the browser).

---

## 4. Vercel (SPEC 13: Vercel token/project)

Who: you. Unblocks: the public website (`pushup-web/`), including /admin.
1. Vercel > Add New Project > import this repo > Root Directory `pushup-web` > Framework Next.js. (This is a separate project from `web/` and `docs/`; decision D-03.)
2. Environment variables (Production): `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`,
   `NEXT_PUBLIC_SITE_URL` (public site URL), `DISPATCHER_URL` (`https://<DOMAIN>`, see section 5) and `DISPATCHER_TOKEN` (same value as in SSM).
   Never set `PUSHUP_FIXTURES` in production.
3. Deploy, then open `/`, `/rules`, `/setup`, `/admin/login`.

---

## 5. Domain or sslip.io (SPEC 13: domain or sslip.io approval)

Who: you. Unblocks: HTTPS for the dispatcher (Caddy). Two options:
- Own domain: create an A record `api.yourdomain.com` -> the Elastic IP from provisioning; bootstrap with `DOMAIN=api.yourdomain.com`.
- No domain: approve using `<ELASTIC-IP>.sslip.io` (the default when `DOMAIN` is unset). Record the approval in `BLOCKERS.md`.
Verify: `curl --fail https://<DOMAIN-or-IP.sslip.io>/health`. Port 80 is closed; Caddy uses TLS-ALPN on 443 (RUNBOOK).

---

## 6. Admin emails (SPEC 13: admin emails)

Who: you, after migrations are applied (3a). Unblocks: signing in at `/admin`.
```
export SUPABASE_DB_URL='postgresql://...'
PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py --emails alice@example.com,bob@example.com \
  --actor you@example.com --reason "launch admins" --dry-run
PYTHONPATH=src:. .venv/bin/python scripts/seed_admins.py --emails alice@example.com,bob@example.com \
  --actor you@example.com --reason "launch admins"
```
Goes to: table `admin_allowlist` (lower-cased) plus an `audit_log` row per new admin. Safe to rerun. Then each admin opens
`/admin/login`, requests a code and signs in.

---

## 7. Team alert handles (SPEC 13: team alert handles)

Who: you. Unblocks: alerts to team phones through the messaging adapter (email via SES is the fallback and already works).
The setting is the live config key `team_alert_handles` (a JSON list of phone numbers/iMessage handles). The repo has no
`ADMIN_ALERT_HANDLES` variable; `team_alert_handles` is the real key. Set it with the audited RPC, from the psql session in RUNBOOK
"Live configuration and moderation":
```sql
SELECT ch_config_set('team_alert_handles', '["+15551234567","+15557654321"]'::jsonb, 'you@example.com', 'launch alert handles');
```
Also set the SSM params `ALERT_EMAIL` and `SES_FROM_EMAIL` (section 1).

---

## 8. Brodie's number (SPEC 13: Brodie's line number)

Who: you (ask James for the exact number). Unblocks: the "text JOIN to ..." links on /join and the result cards.
```sql
SELECT ch_config_set('brodie_number', '"+15551234567"'::jsonb, 'you@example.com', 'set Brodie line number');
```
Goes to: `competition_config.brodie_number` (shown by the site view). Also set `site_url` the same way if your site URL differs
from the default `https://brodie-pushups.vercel.app`: `SELECT ch_config_set('site_url', '"https://your-site"'::jsonb, 'you@example.com', 'site url');`
The "You're up! FaceTime <number> now" text names the line's number: with one active line it uses `brodie_number`.
If you run a second line, set each line's own FaceTime number (otherwise the text falls back to the Chert agent name):
`UPDATE lines SET facetime_handle = '+15551234567' WHERE id = 'line-1';` (and the same for `line-2`).

---

## 9. Prizes: first prize and UFC fighter (SPEC 13)

Who: you. Unblocks: accurate prize display on the site and texts.
- First prize (config key `first_prize`, default `"$100"`):
  `SELECT ch_config_set('first_prize', '"$100"'::jsonb, 'you@example.com', 'first prize confirmed');`
- UFC fighter for the top-3 group call (config key `ufc_fighter`, default null, shown as "a UFC fighter" until set):
  `SELECT ch_config_set('ufc_fighter', '"Max Holloway"'::jsonb, 'you@example.com', 'fighter confirmed');`

---

## 10. Judge clip set (SPEC 13: judge clip set; SPEC 6 ship gate; D-19)

Who: 2+ volunteers with consent (clips are testing-only, never uploaded, gitignored). Unblocks: the SHIP GATE; without it the
gate stays INCOMPLETE and the launch decision is yours (see BLOCKERS.md).

Recording setup for every clip: phone on the floor or low surface about 6-8 ft to the side, landscape, head to feet in frame,
good light. Save as .mp4 in `judge_eval/clips/`.

Categories (from SPEC 6). The ship gate needs at least one clip in every cheat category; the counts below are the recommended minimum
(about 10 reps per clip unless noted):

| Category | Clips | What to record | Camera |
|---|---|---|---|
| clean | 4+ (different people/body types) | proper push-ups, full range, chest down, lockout at top | side-left or side-right (at least one of each) |
| knees | 1+ | push-ups from the knees | side |
| half | 1+ | half-depth reps | side |
| sag | 1+ | hips dropping toward the floor | side |
| pike | 1+ | hips raised high | side |
| no_lockout | 1+ | never fully straightening arms at top | side |
| replay | 1+ | phone filming a laptop playing a push-up video | laptop-replay |
| two_people | 1+ | a second person visible in frame while one does push-ups | side |
| fast_sloppy | 1 | very fast, short reps | side |
| partial_frame | 1 | body partly out of frame | side |
| bad_light | 1 | dim lighting | side |
| off_angle | 1 | slightly off-angle (about 30 degrees from true side) | free text |

Labels file: copy and edit (the format is documented at the top of the example):
```
cp judge_eval/labels.example.yaml judge_eval/labels.yaml
```
Per clip: `clip` (file name), `category`, `camera` (free text), `expected_valid` (reps a human would accept; 0 for every cheat clip),
and optional `expected_rejected` as `{reason: n}`. Example:
```yaml
clips:
  - clip: clean_alex_side.mp4
    category: clean
    camera: side-left
    expected_valid: 10
  - clip: knees_sam_side.mp4
    category: knees
    camera: side-right
    expected_valid: 0
    expected_rejected: {knees_down: 8}
  - clip: laptop_replay.mp4
    category: replay
    camera: laptop-replay
    expected_valid: 0
```
Run the gate (prints per-clip table, aggregate and verdict; exit 0 = passed, 1 = failed/incomplete):
```
PYTHONPATH=src:. .venv/bin/python -m judge_eval.run --bench
```
Live judge is j3 lenient with liveness off (D-34). The gate is the real-clip check; it FAILS (does not skip) without clips, and its
expectations were re-baselined for j3 in `91c9c93` (clean 93% accepted / count error at most 1, off-angle reps accepted, knees and two people never accepted):
```
JUDGE_EVAL_CLIPS=/path/to/clips JUDGE_EVAL_LABELS=/path/to/labels PYTHONPATH=src:. .venv/bin/python -m pytest judge_eval/check_real_clips.py
```
If you change thresholds on purpose, update the pinned expectations in that file deliberately. The older bench criteria below describe the strict j2 gate.

Pass criteria (strict bench): 0 accepted reps across cheat clips, at least 90% of clean reps accepted, per-clip clean count error at most 1.
Without video, `--synthetic` runs the built-in synthetic categories. Specific known problem (D-19): ghost second-person false
rejects on front-view clips; side-view footage with two people is needed to tune. Send the results JSON from
`judge_eval/results/` to the team; threshold changes go through `scripts/rejudge.py` (dry run first).

---

## 11. Re-render cue audio (needed once, after the cue set exists)

Who: anyone with the team Gemini token. Unblocks: spoken live feedback ("Knees up", "Time!" etc.).
```
export GEMINI_API_KEY='...team token...'
# GEMINI_BASE_URL in .env.local points to a dead relay: do NOT set it, and `unset GEMINI_BASE_URL` before rendering
PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --backend gemini --dry-run   # list strings to render, no API call
PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --backend gemini             # render missing clips into data/cues_audio_gemini
PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --bank v2                    # the default voice: Puck + coach direction, mastered, verified by ear, best of 2 takes -> data/cues_audio_v2
```
`data/` is gitignored, so the rendered audio is NOT deployed by git. Copy it to the EC2 host and point the worker at it with
`CUE_AUDIO_DIR` (an SSM parameter; the worker falls back to its bundled banks and reports missing strings if the folder is wrong):
```
scp -i "$HOME/.ssh/id_ed25519" -r data/cues_audio_gemini ubuntu@"$PUBLIC_IP":/tmp/cues_audio_gemini
```
The v2 bank (the one live) is `data/cues_audio_v2`; render it with `env -u GEMINI_BASE_URL PYTHONPATH=src:. .venv/bin/python -m facetime.cues_tts --bank v2`,
then copy it to the host: `rsync -av -e "ssh -i $HOME/.ssh/id_ed25519" data/cues_audio_v2/ ubuntu@3.13.177.157:/tmp/cues_audio_v2/`, move it to
`/opt/brodie/data/cues_audio_v2` (owner `brodie`), set `CUE_AUDIO_DIR=/opt/brodie/data/cues_audio_v2` in SSM and restart the worker. The same steps apply to the older gemini bank:
then on the host move it to `/opt/brodie/data/cues_audio_gemini` (owner `brodie`), set `CUE_AUDIO_DIR=/opt/brodie/data/cues_audio_gemini`
in SSM, and restart the worker (RUNBOOK "Restart, logs and line recovery").

---

## 12. Live testers

Who: 3-5 friends with iPhones (FaceTime), 2 of them not on the team. Unblocks: the final end-to-end rehearsal.
Each tester: FaceTime Brodie's number, do 10 push-ups side-view, text `JOIN <name>`, `YES`, `QUEUE`, `STATUS`, `TOP`, `STOP`,
`START`. Record failures in `BLOCKERS.md`. Do this before opening registration (LAUNCH_CHECKLIST T-24h).

---

## 13. Phase-2 Chert discovery test (needs one tester with FaceTime)

Follow `docs/challenge/HUMAN_TASKS_discover.md` exactly (it starts `scripts/discover_chert.py` and `chert dev`). Paste the
results table into the section below, then set `HANGUP_MODE`, `LINE_OFFLINE_GAP_S` and `CALLER_ID_SOURCE` in SSM and redeploy.

### Phase 2 results (fill in)
| Test | Observation | Seconds | Notes |
|---|---|---|---|
| A: hung up after agent left? | | | |
| B: first successful call-back | | | |
| C: chert_call has caller handle? | | | |
| C: participant identity format | | | |
| dispatch lag (job -> connected) | | | |

---

## 14. Inbound FaceTime outage (OPEN since 2026-10-13 04:23)

Who: you, with Chert (James) and whoever owns the Mac behind the line. Unblocks: all calls, live testers, `HANGUP_MODE=chert_api`.
Symptom: no inbound FaceTime detected on the Mac since 04:23 on 2026-10-13, and Chert shows no call records. This is upstream, not our code.
1. Ask Chert whether the line is healthy; check the Mac (awake, signed in to FaceTime and iMessage, line enabled).
2. Place one test call from a phone. Confirm it reaches the worker (EC2: `sudo journalctl -u chert-agent -u brodie-worker --since '-5 min' --no-pager`).
3. Only then try `HANGUP_MODE=chert_api`: set it in SSM, redeploy, make one test call and confirm it hangs up cleanly at the end. If not, set it back to `unverified`.
4. Remove tester data before the public push (see LAUNCH_CHECKLIST T-24h).
