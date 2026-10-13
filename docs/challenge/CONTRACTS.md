# Push-Up Challenge — Frozen Contracts (v1)

Every task builds against this file. Changing a contract = a DECISIONS entry + a note in PLAN.md.
SPEC = docs/challenge/SPEC.md.

## C0. Layout
- `challenge/` — new Python package (repo root, Python 3.12, run with `PYTHONPATH=src:.`).
  - `challenge/timeutil.py`, `challenge/config.py`, `challenge/scoring.py` — pure helpers.
  - `challenge/store.py` — DB access (RPC only).
  - `challenge/judge/` — strict judge (pure + runtime hook).
  - `challenge/messaging/` — providers, commands, templates, outbox.
  - `challenge/dispatcher/` — FastAPI app + jobs loop.
  - `challenge/worker/` — competition call controller used by facetime/worker.py.
- `db/migrations/2026101[2-9]_challenge_*.sql` — migrations (idempotent: `create … if not exists`, `create or replace`, guarded `alter … add column if not exists`).
- `db/test/` — local Postgres harness (Supabase role/auth shims) for tests.
- `judge_eval/` — harness (clips gitignored). `scripts/rejudge.py`, `scripts/discover_chert.py`, `scripts/reconcile_sessions.py`.
- `pushup-web/` — NEW Next.js app (separate Vercel project) for the public site + admin. The existing `web/` coach app is untouched.
- `infra/` — EC2 setup, systemd units, Caddyfile, deploy/rollback/backup scripts.
- Tests: `tests/challenge/test_*.py`, run with `PYTHONPATH=src:. .venv/bin/python -m pytest tests/challenge -q -n auto --dist loadfile`.

## C1. Time
All timestamps stored UTC (`timestamptz`). ET = `America/New_York` (zoneinfo). `et_day(ts) -> date`.
Every RPC takes `p_now timestamptz` (simulation + tests drive time; production passes `now()`).

## C2. Database (new objects; existing tables keep working)

Existing `clients` (uuid PK, `coach_id` FK) — competitors are clients of a seeded coach row
`coaches.name = 'Brodie Challenge'` (id stored in config key `challenge_coach_id`).

```sql
alter table clients add column if not exists display_name text;          -- unique lower(display_name) where not null
alter table clients add column if not exists joined_at timestamptz;
alter table clients add column if not exists age_confirmed_at timestamptz;
alter table clients add column if not exists rules_accepted_at timestamptz;
alter table clients add column if not exists opted_out_at timestamptz;
alter table clients add column if not exists banned_at timestamptz;
alter table clients add column if not exists ban_reason text;
alter table clients add column if not exists auth_user_id uuid;            -- web_only login link (nullable, unique)

client_handles(handle text primary key, client_id uuid not null references clients, kind text check (kind in ('phone','email')),
               linked_via text check (linked_via in ('join','claim_window','admin','web')), created_at timestamptz default now())
join_pending(handle text primary key, display_name text not null, created_at timestamptz not null)

lines(id text primary key, chert_agent_name text not null, active bool not null default true)
line_state(line_id text primary key references lines, state text not null check (state in ('idle','claimed','in_call','offline')),
           user_id uuid, call_id text, claimed_until timestamptz, offline_until timestamptz, in_call_since timestamptz,
           updated_at timestamptz not null, version bigint not null default 0)
queue(id bigserial primary key, user_id uuid not null references clients, line_pref text, entered_at timestamptz not null,
      notified_at timestamptz, claim_expires_at timestamptz, line_id text,
      status text not null check (status in ('waiting','notified','connected','no_show','left','expired')))
  -- unique (user_id) where status in ('waiting','notified')
calls(id text primary key /* chert call_id */, line_id text, user_id uuid, handle_raw text, decision text not null check (decision in ('accept','reject')),
      reject_reason text, connected_at timestamptz not null, count_end_at timestamptz, ended_at timestamptz,
      counted_toward_cap bool not null default false, liveness_result text check (liveness_result in ('pass','fail','skipped') or liveness_result is null),
      void bool not null default false, void_reason text, session_id uuid references sessions, committed_at timestamptz, rep_count int)
alter table reps add column if not exists valid bool, reject_reasons text[], multiplier int, points int, at timestamptz /* absolute rep time */,
      min_elbow_deg_l real, min_elbow_deg_r real, top_elbow_deg real, max_hip_line_dev_deg real /* signed: + sag, - pike */,
      min_knee_deg real, knee_floor_contact bool, shoulder_wrist_drop real, shoulder_elbow_gap real /* min over bottom of (elbow_y - shoulder_y)/torso_len; depth needs ≤ depth_margin */, min_keypoint_conf real, frame_conf_frac real,
      persons_in_frame int, rep_duration_s real, torso_ok bool, side text, classifier_labels text[], in_challenge bool, judge_version text
competition_config(key text primary key, value jsonb not null, updated_by text, updated_at timestamptz not null default now())
power_hours(date_et date primary key, starts_at timestamptz not null, ends_at timestamptz not null, announced_at timestamptz,
            warned_at timestamptz, started_announced_at timestamptz)
messages(id bigserial primary key, direction text check (direction in ('in','out')), handle text not null, user_id uuid, body text,
         media_url text, template text, ctx jsonb /* template context; body may be null and rendered by the sender */, lease_until timestamptz, dedupe_key text unique, provider_message_id text unique, status text not null
         /* in: received|handled ; out: queued|sending|sent|failed|suppressed */, attempts int default 0, last_error text,
         not_before timestamptz, created_at timestamptz not null default now(), sent_at timestamptz)
audit_log(id bigserial primary key, actor text not null, action text not null, target text, before jsonb, after jsonb, reason text, at timestamptz not null default now())
score_adjustments(id bigserial primary key, user_id uuid not null references clients, points int not null, reason text not null, actor text not null, at timestamptz not null default now())
rank_state(user_id uuid primary key references clients, rank int, points int, updated_at timestamptz, last_drop_text_at timestamptz)
admin_allowlist(email text primary key)
heartbeats(component text primary key, at timestamptz not null, detail jsonb)
site_pulse(id int primary key default 1, bumped_at timestamptz not null)   -- anon-readable, realtime; bumped by triggers on calls/reps/line_state/queue/score_adjustments
```

Config keys + seed values (`competition_config`): `window_start` "2026-10-12T20:00:00-04:00", `window_end` "2026-10-18T23:59:59-04:00",
`call_count_s` 180, `call_reveal_s` 15, `daily_call_cap` 5, `claim_window_s` 90, `line_offline_gap_s` 180, `min_counted_call_s` 30,
`in_call_timeout_extra_s` 60, `power_hour_window` [12,22], `power_multiplier` 2, `rank_drop_min` 2, `rank_drop_throttle_h` 3,
`quiet_hours` [23,9], `recap_hour` 10, `streak_risk_hour` 20,
`avatar_level_thresholds` [0,25,60,120,200,300,450,650,900,1200] (points for level 1..10), `judge_thresholds` (see C5),
`registration_open` true, `competition_frozen` false, `swearing` false, `site_url` "https://brodie-pushups.vercel.app",
`brodie_number` null, `team_alert_handles` [], `challenge_coach_id` (uuid), `outbound_rate_per_min` 20.

### Derived rules (implemented in SQL functions, mirrored in challenge/scoring.py for tests)
- `calls_today(user, p_now)` = count of calls with user_id, counted_toward_cap, `et_day(connected_at) = et_day(p_now)`. Void calls still count.
- counted_toward_cap = decision='accept' AND (ended_at−connected_at ≥ min_counted_call_s OR rep_count ≥ 1).
- Rep scoring at commit: `valid_final = valid AND window_start ≤ at < window_end AND NOT frozen-at-commit AND at < calls.connected_at + call_count_s AND NOT in_challenge AND call.liveness_result <> 'fail'`
  (extra reasons: before_start, after_freeze, after_count, liveness_fail);
  `multiplier = power_multiplier if at ∈ [power_hour.starts_at, ends_at) of et_day(at) else 1`; `points = valid_final ? multiplier : 0`.
  Reps after freeze get reason `after_freeze`; liveness void gets `liveness_fail`.
- User points = Σ reps.points over non-void calls + Σ score_adjustments.points. valid_reps = count valid_final reps (non-void).
- Rank: points desc, then `reached_at` asc (time of the user's latest points-earning rep/adjustment), then joined_at asc. Users with 0 points are listed after.
- Streak (as of p_now): consecutive ET days ending today (or yesterday if no qualifying call yet today) with ≥1 counted, non-void call having ≥1 valid rep.
- Avatar level = 1 + count of thresholds[1..] ≤ points (1..10).

### RPC functions (plpgsql, `security definer`, `set search_path = public`, EXECUTE granted to service_role ONLY; all return jsonb)
Line/queue mutations lock rows `select … for update` (line_state rows, then the user's queue row) and write `audit_log` (actor 'system').
- `ch_call_start(p_call_id text, p_line_id text, p_handle text, p_mode text /* 'chert_meta'|'claim_window' */, p_now timestamptz)`
  → `{decision:'accept'|'reject', user_id, reason, cue}`. Idempotent on call_id (returns stored decision).
  reasons/cues: `ok`/null; `not_registered`/`not_signed_up`; `at_cap`/`at_cap`; `not_your_turn`/`not_your_turn`; `banned`/`not_your_turn`;
  `frozen`/`competition_over`; `line_inactive`/`not_your_turn`.
  chert_meta: resolve handle→client; accept if line claimed by that user, or line idle AND no waiting/notified queue entries (walk-in).
  claim_window: accept iff line claimed (attribute to claim holder); walk-ins rejected (`not_your_turn`) because unattributable.
  On accept: line → in_call(user, call_id, in_call_since=p_now); queue entry → connected.
- `ch_call_end(p_call_id text, p_ended_at timestamptz, p_count_end_at timestamptz, p_rep_count int, p_now timestamptz)` → `{ok, counted_toward_cap}`.
  Idempotent. Line (if still in_call with this call_id) → offline(offline_until = p_now + line_offline_gap_s).
- `ch_commit_reps(p_call_id text, p_payload jsonb, p_now timestamptz)` → `{ok, session_id, valid_reps, points, already}`.
  payload = `{started_at, ended_at, liveness_result, judge_version, reps:[{n, t, at, valid, reject_reasons[], faults[], in_challenge, <C2 metric columns>}]}`.
  Creates sessions(client_id=user, started_at, ended_at) + sets(exercise_key 'pushups', set_number 1, completed_reps=#valid_final) + reps (computes multiplier/points/after_freeze/liveness_fail). Idempotent on calls.session_id. Rejected calls → `{ok:false, reason:'not_accepted'}`.
- `ch_tick(p_now timestamptz)` → `{no_shows:[{user_id, queue_id}], claims:[{line_id, user_id, queue_id, claimed_until}], timeouts:[call_id], idled:[line_id]}`.
  Per active line: claimed & claimed_until ≤ now → queue no_show, line idle; in_call & in_call_since + call_count_s+call_reveal_s+in_call_timeout_extra_s ≤ now → offline; offline & offline_until ≤ now → idle;
  then for each idle line, unless frozen/after window_end: pop next eligible (calls_today asc, entered_at asc; skip cap/banned/opted_out/in a call) → line claimed(claimed_until = now + claim_window_s), queue notified.
  Waiting entries of users now at cap / banned / opted out → status expired.
- `ch_queue_join(p_user_id uuid, p_now timestamptz)` → `{ok, reason /* ok|already|at_cap|in_call|banned|frozen|not_registered|opted_out_ok */, position, calls_today, calls_left, line_open bool}`. line_open = this user could walk in now: some line idle, no other waiting/notified entry, window open, under cap, no live claim/call (matches ch_call_start; D-13).
- `ch_queue_leave(p_user_id uuid, p_reason text /* 'left'|'stop' */, p_now)` → `{ok, was_queued}`. If the user holds a claim, line → idle.
- `ch_queue_view(p_now)` → `{lines:[{line_id,state,user_id,call_id,claimed_until,offline_until,in_call_since}], queue:[{queue_id,user_id,display_name,status,entered_at,calls_today,position}], avg_cycle_s}`.
  avg_cycle_s = avg(ended_at−connected_at) of last 10 accepted calls (default call_count_s+call_reveal_s) + line_offline_gap_s.
- `ch_join_start(p_handle text, p_display_name text, p_now)` → `{ok, reason /* ok|bad_name|taken|already_registered|closed */}`.
- `ch_join_confirm(p_handle text, p_now)` → `{ok, reason /* ok|no_pending|taken|closed */, user_id}`; creates client (coach = challenge coach), handle (linked_via 'join'), sets age_confirmed_at/rules_accepted_at/joined_at.
- `ch_user_by_handle(p_handle text)` → `{user_id, display_name, opted_out, banned}` or `{user_id:null}`.
- `ch_set_opt(p_user_id uuid, p_opted_out bool, p_now)` → `{ok}`.
- `ch_user_status(p_user_id uuid, p_now)` → `{display_name, points, valid_reps, rank, total_users, calls_today, calls_left, streak, queue_position, queue_status, avatar_level}`.
- `ch_leaderboard(p_limit int, p_now)` → `[{rank, user_id, display_name, points, valid_reps, streak, avatar_level, reached_at}]` (service-side; includes user_id).
- `ch_rank_deltas(p_now)` → `[{user_id, old_rank, new_rank, points, ahead_display_name, ahead_points}]` for users whose rank worsened by ≥ rank_drop_min since rank_state; updates rank_state for everyone.
- `ch_config_get()` → `{key: value, …}`. `ch_config_set(p_key, p_value jsonb, p_actor, p_reason)` → `{ok}` (audited).
- Admin (audited, reason required, actor = admin email): `ch_admin_void_call(p_call_id, p_reason, p_actor)`, `ch_admin_unvoid_call`, `ch_admin_adjust(p_user_id, p_points, p_reason, p_actor)`,
  `ch_admin_ban(p_user_id, p_reason, p_actor)`, `ch_admin_unban(p_user_id, p_reason, p_actor)`, `ch_admin_queue_remove(p_queue_id, p_reason, p_actor)`.
- Outbox: `ch_outbox_enqueue(p_handle, p_user_id, p_template, p_body, p_media_url, p_dedupe_key, p_not_before, p_now)` → `{id, duplicate bool}` (dedupe_key unique; duplicate = no new row);
  `ch_outbox_claim(p_limit int, p_now)` → rows (status queued & not_before ≤ now → sending, attempts+1; `for update skip locked`);
  `ch_outbox_mark(p_id bigint, p_status text, p_provider_message_id text, p_error text, p_retry_at timestamptz, p_attempt int default null)` — pass the `attempts` from claim; a stale attempt returns {ok:false,reason:"stale"} (C7 fence);
  `ch_inbound_record(p_provider_message_id, p_handle, p_body, p_now)` → `{id, duplicate bool}`.
- `ch_heartbeat(p_component text, p_detail jsonb, p_now)`.

### Public views (granted SELECT to anon; no handles, no user_id except as opaque stable `public_id` = md5(user_id))
`leaderboard_public(rank, public_id, display_name, points, valid_reps, streak, avatar_level, badges text[], reached_at)`,
`user_public(public_id, display_name, points, valid_reps, streak, avatar_level, rank, joined_at, best_call_points, best_call_id)`,
`user_daily_public(display_name, date_et, points, valid_reps, calls)`,
`call_result_public(call_id, display_name, connected_at, valid_reps, rejected_reps, points, reasons jsonb /* {reason: count} */, liveness_result, void, rank_after, total_points_after)`,
`line_status_public(state_summary /* idle|in_call|offline|claimed|closed */, queue_length, lines_active, eta_cycle_s, updated_at)`,
`power_hour_public(date_et, starts_at, ends_at)`, `competition_public(window_start, window_end, frozen, brodie_number, site_url)`.
Anon has NO grants on base tables. RLS enabled on every new table, no anon policies (except `site_pulse` select). Realtime publication includes `site_pulse`.

## C3. Store (challenge/store.py)
```python
class Store(Protocol):
    def rpc(self, fn: str, args: dict) -> Any: ...          # returns decoded jsonb
class PgStore:  # psycopg 3; dsn; executes `select fn(%(a)s, …)` with named args p_*; autocommit per call
class SupaStore:  # PostgREST POST {SUPABASE_URL}/rest/v1/rpc/{fn} with service role headers; raises StoreError on non-2xx
def store_from_env() -> Store  # CHALLENGE_DB_DSN → PgStore else SupaStore
```
Args dict keys are the SQL parameter names (`p_now`, …); datetimes passed as ISO strings or datetime.

## C4. Dispatcher HTTP API (FastAPI, `challenge.dispatcher.app:app`)
Auth: worker endpoints require header `X-Brodie-Token: $DISPATCHER_TOKEN`; admin endpoints require the same token plus `X-Admin-Email` (website server only, admin email verified by the site); webhooks verified per provider.
- `POST /calls/start` `{call_id, line_id, handle?}` → `{decision, user_id?, reason, cue}`
  Call-to-queue (chert_meta only): a `not_your_turn` reject of a known caller runs `ch_queue_join`; on ok/already/opted_out_ok the
  response becomes `reason:'queued', cue:'queued', position` and the caller is texted `call_queued` (dedupe `call:<call_id>`).
  A `not_registered` caller with a handle is texted `not_registered` (JOIN instructions). calls.reject_reason stays `not_your_turn`.
  Best effort: a failure there is logged and the plain reject is returned.
- `POST /calls/event` `{kind: 'call_started'|'call_ended'|'reps_committed', call_id, idem_key, at, payload}` → `{ok}`.
  `call_ended.payload = {ended_at, count_end_at, rep_count}`; `reps_committed.payload` = ch_commit_reps payload (dispatcher calls ch_commit_reps, then post-call processing: result text/card, rank deltas).
- `POST /webhooks/chert` (provider-specific body) → 200; `POST /web/queue` `{action:'join'|'leave'}` + `Authorization: Bearer <supabase user jwt>` (web_only mode); `GET /web/me` same auth.
- `POST /admin/broadcast` `{body, dry_run}` → `{recipients, preview}`; `POST /admin/rejudge` `{thresholds?, apply}`.
- `GET /health` → `{ok, db, provider, flags:{CALLER_ID_SOURCE, MESSAGING_PROVIDER, HANGUP_MODE, REVEAL_MODE, CARD_DELIVERY}, line_states}`.

Env flags (read once at startup, logged, echoed in /health and admin): `CALLER_ID_SOURCE` (default claim_window), `MESSAGING_PROVIDER` (default mock),
`HANGUP_MODE` (default unverified), `REVEAL_MODE` (audio_only), `CARD_DELIVERY` (link), `LINE_OFFLINE_GAP_S` (overrides config if set),
`OUTBOUND_RATE_PER_MIN`, `DISPATCHER_URL`, `DISPATCHER_TOKEN`, `CHALLENGE_MODE` (worker: `competition`|`demo`; demo = legacy DEMO_CLIENT_ID path), `LINE_ID` (worker, default 'line-1').

## C5. Judge (challenge/judge/)
```python
JUDGE_VERSION = "j1"
DEFAULT_THRESHOLDS = {"min_conf":0.5, "frame_conf_frac":0.9, "knee_min_deg":160, "knee_floor_margin":0.02,
  "hip_line_max_dev_deg":15, "depth_elbow_max_deg":90, "depth_margin":0.05, "lockout_min_deg":160,
  "min_rep_s":0.8, "max_cadence_rpm":60, "classifier_veto":["pushups - shallow","pushups - insufficient","pushups - elevated hips"],
  "classifier_veto_substrings":["knee","sag"], "liveness_window_s":[45,150], "liveness_timeout_s":4, "cue_min_gap_s":4}
@dataclass FrameObs: t: float; img: np.ndarray|None  # (33,5) x,y,z,vis,presence normalised; world: np.ndarray|None (33,3); persons: int
@dataclass RepMetrics: (the C2 metric columns) + side: str, classifier_labels: list[str]
def judge_rep(m: RepMetrics, thr: dict) -> tuple[bool, list[str]]   # pure; reasons in priority order:
   multiple_people, not_in_frame, knees_down, hips_sag, hips_pike, too_shallow, no_lockout, too_fast, not_horizontal, classifier:<label>
class RepMetricsAccumulator: add_frame(f: FrameObs); close_rep(t_fire: float, labels: list[str], torso_ok: bool) -> RepMetrics; reset()
class JudgeRuntime(thr: dict): on_frame(f: FrameObs); on_rep(rep_event: dict) -> RepVerdict(valid, reasons, metrics, cue_key|None)
```
Rep window = frames from previous rep fire (or counting start) to this fire. `top_elbow_deg` = max visible-side elbow angle in window (lockout that started the rep);
`min_elbow_deg_*` = min per side; depth requires visible-side min elbow ≤ depth_elbow_max_deg AND shoulder_elbow_gap ≤ depth_margin
(shoulder_elbow_gap = min over window of (elbow_y − shoulder_y)/torso_len in image coords, i.e. shoulder drops to within depth_margin of elbow height; shoulder_wrist_drop kept as an informational metric; both defined precisely in judge/metrics.py docstring).

## C6. Worker ↔ judge ↔ dispatcher
`challenge/worker/controller.py: CompetitionCall(call_id, line_id, handle, dispatcher, judge_cfg, clock, say)` with
`async start() -> bool` (gatekeeper; on reject plays cue then returns False within 5s), `on_frame(FrameObs)`, `on_rep(event)`,
`tick(now)` (30s-left cue at count_s−30, "Time!" at count_s, reveal until count_s+reveal_s, then `end()`), `async end(reason)` (commit via `/calls/event reps_committed` then `call_ended`; local JSON first at `data/tmp/sessions/<call_id>.challenge.json` with `committed:false|true`).
Cue keys (say_now phrases; exact text in SPEC §6) are the dict `challenge.judge.cues.CUES: dict[str,str]`.

## C7. Review amendments (v1.1, plan review)
- Per-user serialization: every RPC that can put a user in a call or queue takes `pg_advisory_xact_lock(hashtextextended(user_id::text,0))` after line locks (lock order: line_state rows by line_id → user advisory lock → queue rows). A user can be in at most one of {active queue entry, claim holder, in_call} across ALL lines.
- ch_tick in_call timeout FINALIZES the call: ended_at = in_call_since + call_count_s + call_reveal_s (capped by p_now), counted_toward_cap per rule; a later ch_call_end/ch_commit_reps reconciles (idempotent; never double-counts).
- Notification intents are written in the SAME transaction as the state change: ch_tick inserts outbox rows (template 'youre_up' / 'missed_slot', ctx jsonb, dedupe_key e.g. 'youre_up:<queue_id>') and ch_call_end does not text. Python sender renders body from template+ctx when body is null. Outbox leases: ch_outbox_claim sets status 'sending', lease_until = now+60s; rows whose lease expired are reclaimable; provider send is idempotent per message id where supported (otherwise at-most-once after lease: mark 'failed' after 5 attempts).
- Worker writes a local checkpoint JSON (call meta + reps so far) after every rep, not only at end(); reconciler commits checkpoints of calls that never ended (stale > max length + 120 s) with ended_at = last rep time.
- Website reads are uncached (dynamic, no-store); realtime pulse → router.refresh().
- call_result_public adds `points_before int, avatar_level_before int, avatar_level_after int, rank_before int` (before = user totals excluding this call and later calls; rank_before = rank by points as of just before this call's connected_at, nullable if unranked). Also `competition_public` adds `avatar_level_thresholds jsonb` (non-sensitive) so the site can compute levels for display.

- C7.x: calls gains `end_reason text` (end|timeout|commit). First end wins; only an explicit end/commit ended_at may replace a timeout end (once); counted_toward_cap only recomputed then.
- C7.y (judge): metrics = 2nd-most-extreme value after a running 3-frame median; persons_in_frame = 2nd-highest count in the rep window; the rep window spans from the previous rep fire (or reset) with no truncation; RepAccumulator(thr=None, max_lag_s=2.0). knee_floor_margin 0.02 (D-17).
- C7.z: ch_postcall(p_call_id text, p_now, p_card_delivery) atomic+idempotent post-call intents; ch_postcall_pending(p_now,p_limit) for the jobs sweeper; ch_event_log + ch_event_run(idem_key, call_id, kind, payload, now) for /calls/event dedupe; calls.postcall_done_at. LINE_OFFLINE_GAP_S env writes competition_config at startup (audited).
- C7.p: ch_power_hour(p_now timestamptz) -> jsonb {date_et, starts_at, ends_at, announced, active, over} | null — today (ET); unannounced hidden until start. service_role only.
- C7.m: messages.processed_at; ch_inbound_done(p_id), ch_inbound_is_done(p_id) — webhook re-handles unprocessed duplicates; ch_outbox_sent_recent(p_now,p_window_s) caps claims across processes; ch_outbox_stamp_sent sets sent_at from the dispatcher clock.
- C7.j (task 23 jobs): migration 20261018_challenge_jobs.sql adds ch_job_state + ch_job_get/list/set/delete/incr, ch_power_hour_row/ensure/mark, ch_jobs_audience(p_now), ch_jobs_health(p_now); ch_postcall_pending skips calls with job key `postcall_giveup:<id>`. `Jobs.run_due(now)` (challenge/dispatcher/jobs.py) is the single entrypoint; create_app starts the loop unless JOBS_ENABLED=0. rank_drop texts that would send in quiet hours are marked suppressed (error quiet_hours), not deferred. Template `alert` {condition, detail}.
- C7.w (task 44 web-only join): migration 20261018_challenge_web.sql adds `web_handle_claims` (pending FaceTime-handle claims + LINK code), ch_user_by_auth(p_auth_user_id), ch_web_join(p_auth_user_id, p_display_name, p_handle, p_now), ch_web_claim_handle(p_user_id, p_handle, p_now), ch_web_link(p_handle, p_code, p_now), ch_web_me(p_user_id, p_now); ch_outbox_enqueue is redefined (same signature) to drop texts to web users without a verified handle. Endpoints `GET /web/me`, `POST /web/join|queue|handle|opt` (D-23) — Bearer Supabase access token, identity only from verified `sub`, unknown body fields rejected. A web-entered handle is a pending claim until the owner texts `LINK <code>` from it (D-25). JWT checks: signature, exp, aud=authenticated, iss == SUPABASE_JWT_ISSUER (always required, D-26), role=authenticated, non-anonymous. Enabled by WEB_JOIN_ENABLED (site: NEXT_PUBLIC_WEB_JOIN). Limits: per-IP scope `web` (DISPATCHER_RATE_PER_MIN_WEB, default 20000 since all calls arrive from Vercel) + per-verified-user WEB_RATE_PER_USER_MIN (default 120).
- C7.l (liveness, D-20/D-29/D-30): challenge types challenge_lift_hold | challenge_double_tap | challenge_freeze (+ challenge_go said mid-FREEZE); legacy tap_left/tap_right/lift_right keys kept in CUES but never drawn. DEFAULT_THRESHOLDS added: liveness_lift_h 0.4, liveness_floor_leave 0.25, liveness_quiet_s 2.0, liveness_min_react_s 0.5, liveness_hold_s 1.5, liveness_double_tap_gap_s 2.0, liveness_freeze_s 2.5, liveness_freeze_still 0.15, liveness_freeze_motion_min 0.25, liveness_cam_shift 0.3, liveness_max_gap_s 0.3, liveness_retry_delay_s [3.0,4.5], liveness_periodic_cv 0.25, liveness_postpone_s [10,30], liveness_go_delay_s [2.0,8.0] (D-30), liveness_go_react_s 2.0 (D-30 deviation from D-29's ~1.5: resuming from the top of a rep is slow; at 1.5 honest first-try FREEZE pass fell to 0.82, at 2.0 it is 0.93 at noise 0.02 with overall honest pass 0.995), liveness_go_min_react_s 0.25, liveness_resume_min 0.15; removed: liveness_tap_dist. API: LivenessChallenge(rng, thr).schedule(t0)->fire_t; on_frame(f); due(t); start(t)->cue; poll(t)->(pending|go|retry|pass|fail|skipped, cue|None); finish(t_end); windows()->[(start, deadline)] (replaces window(); feed windows()[-1] to JudgeRuntime.set_challenge_window); summary()->{result, unprompted_lifts, suspicious, fire_t, postponed, attempts:[{cue,start,end,outcome(pass|timeout|quiet|camera|early|no_resume|ended),seen,go_t}]}. Selection: no challenge before reps are earned (push-up motion seen, or on_rep(t)); hand types (LIFT_HOLD/DOUBLE_TAP) whenever no hand lift began in the last liveness_hand_cooldown_s (new threshold, 15.0; replaces the D-20 'no lift since counting started' rule), also at rest; FREEZE only while push-ups are in progress; the retry excludes the first type unless that leaves nothing eligible (then the same type again, fresh go delay); nothing eligible -> random postponement of U(liveness_postpone_s) = 10-30 s, so checks are <= 30 s apart and every >= 30 s cooldown-clear stretch before the last moment an attempt fits gets a cue (shorter stretches may not: a guaranteed cue there would be predictable). Terminal result: pass | skipped (only when no rep was earned and nobody was in frame during any attempt) | fail (everything else, incl. a cue postponed past the call end, the call ending before fire_t with reps earned, hang-up during an attempt/pending retry): earned reps never count without a pass. FREEZE: needs both wrists placed and >= 1 tracked wrist on the floor to confirm; after confirmation a > liveness_max_gap_s stretch without a valid single-person frame ends it as 'lost'; every FREEZE exit before its go cue returns poll status 'go' with challenge_go (release) before the retry. Hand evidence is dropped on tracking gaps (fresh floor->up needed). Outcomes add 'lost'. windows() returns current deadlines (a FREEZE deadline shrinks at go/end): the controller must call JudgeRuntime.update_challenge_window(t0, t1) (new; replaces the window starting at t0) for every windows() entry after each start()/poll(). summary() adds earned. Accepted residual risk (D-30, mitigated by admin re-judge of top finishers): push-ups with long pauses (pause = period-3 s) beat FREEZE+go at 200 seeds 6.0 % (period 10) and 8.5 % (period 12); hand cooldown (replay lifting every 20-35 s at rest): bank_lifts P20/25/35 9.5/7.5/8.0 % (1.5-2.0 % under the old sticky rule); push_lifts P16/20/25 8.0/9.5/6.0 % (already 7.0/9.5/6.0 % before: the test's narrow 6 s cue span); all other replay families <= 5 %.
