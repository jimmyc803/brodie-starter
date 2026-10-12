-- Push-Up Challenge, migration 1: schema, config seed, scoring helpers, public views, RLS/grants, realtime pulse.
-- Contract: docs/challenge/CONTRACTS.md §C2 (+ §C7 v1.1). Apply after db/schema.sql and 20261011_program_upload.sql.
-- Idempotent: safe to apply any number of times (if not exists / create or replace / on conflict do nothing).
--
-- Helper functions (later migrations / RPCs use these; all security definer ones set search_path = public):
--   Pure (no table access; EXECUTE granted to anon because public views call them as the querying role):
--     ch_et_day(timestamptz) -> date                ET calendar day of a timestamp (America/New_York).
--     ch_et_day_start(date) -> timestamptz           instant of ET midnight that starts the given ET day.
--     ch_level_for_points(int, jsonb) -> int         avatar level 1..10 = 1 + count(thresholds[1..] <= points).
--     ch_streak_days(date[], date) -> int            consecutive qualifying ET days ending today (or yesterday).
--   Service-role only (read tables; EXECUTE revoked from public/anon/authenticated):
--     ch_cfg(text) -> jsonb                          competition_config value (null when missing).
--     ch_calls_today(uuid, timestamptz) -> int       counted_toward_cap calls (void included) on et_day(p_now).
--     ch_user_points(uuid) -> int                    Σ rep points over non-void accepted calls + Σ score_adjustments.
--     ch_valid_reps(uuid) -> int                     count of valid_final reps over non-void accepted calls.
--     ch_reached_at(uuid) -> timestamptz             latest points-earning rep / adjustment time (rank tiebreak).
--     ch_streak(uuid, timestamptz) -> int            streak as of p_now.
--     ch_avatar_level(int) -> int                    ch_level_for_points with the configured thresholds.
--   Internal views (no anon/authenticated grants; service_role may select):
--     ch_call_stats  one row per call: call_id, user_id, line_id, decision, void, counted_toward_cap, liveness_result,
--                    connected_at, ended_at, committed_at, date_et, valid_reps, rejected_reps, points, last_point_at, reasons.
--     ch_user_stats  one row per competitor (clients.joined_at not null): user_id, display_name, joined_at, banned_at,
--                    opted_out_at, points, valid_reps, reached_at, streak_days date[], best_call_id, best_call_points,
--                    avatar_level, listed bool, rank (null when not listed). Streak at time T =
--                    ch_streak_days(streak_days, ch_et_day(T)).
-- Rep validity in aggregates ("valid_final"): reps.valid AND reps.points > 0 AND window_start <= reps.at
--   AND reps.at < calls.connected_at + call_count_s. Points are summed from reps.points (set at commit by ch_commit_reps)
--   over the same filtered reps; reps outside [window_start, connected_at + call_count_s) never score.
-- Badges (leaderboard_public.badges): 'streak' when streak >= 2, 'raffle' when valid_reps >= raffle_min_valid_reps.
-- competition_public.frozen = competition_frozen OR now() >= window_end.
-- site_pulse is bumped once per transaction, at commit (deferred constraint triggers), by writes to calls, reps,
--   line_state, queue, score_adjustments, competition_config, power_hours, clients. Deferring keeps the single-row
--   lock to the very end of the transaction so it cannot deadlock against RPC row locks.

begin;

-- ---------------------------------------------------------------- columns on existing tables
alter table clients add column if not exists display_name text;
alter table clients add column if not exists joined_at timestamptz;
alter table clients add column if not exists age_confirmed_at timestamptz;
alter table clients add column if not exists rules_accepted_at timestamptz;
alter table clients add column if not exists opted_out_at timestamptz;
alter table clients add column if not exists banned_at timestamptz;
alter table clients add column if not exists ban_reason text;
alter table clients add column if not exists auth_user_id uuid;
create unique index if not exists clients_display_name_lower_uq on clients (lower(display_name)) where display_name is not null;
create unique index if not exists clients_auth_user_id_uq on clients (auth_user_id) where auth_user_id is not null;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'clients_display_name_format'
                 and conrelid = 'public.clients'::regclass) then
    alter table clients add constraint clients_display_name_format
      check (display_name is null or display_name ~ '^[A-Za-z0-9_]{3,20}$');
  end if;
end $$;

alter table reps add column if not exists valid bool;
alter table reps add column if not exists reject_reasons text[];
alter table reps add column if not exists multiplier int;
alter table reps add column if not exists points int;
alter table reps add column if not exists at timestamptz;
alter table reps add column if not exists min_elbow_deg_l real;
alter table reps add column if not exists min_elbow_deg_r real;
alter table reps add column if not exists top_elbow_deg real;
alter table reps add column if not exists max_hip_line_dev_deg real;
alter table reps add column if not exists min_knee_deg real;
alter table reps add column if not exists knee_floor_contact bool;
alter table reps add column if not exists shoulder_wrist_drop real;
alter table reps add column if not exists shoulder_elbow_gap real;
alter table reps add column if not exists min_keypoint_conf real;
alter table reps add column if not exists frame_conf_frac real;
alter table reps add column if not exists persons_in_frame int;
alter table reps add column if not exists rep_duration_s real;
alter table reps add column if not exists torso_ok bool;
alter table reps add column if not exists side text;
alter table reps add column if not exists classifier_labels text[];
alter table reps add column if not exists in_challenge bool;
alter table reps add column if not exists judge_version text;

-- ---------------------------------------------------------------- new tables
create table if not exists client_handles (
  handle      text primary key,
  client_id   uuid not null references clients(id) on delete cascade,
  kind        text check (kind in ('phone', 'email')),
  linked_via  text check (linked_via in ('join', 'claim_window', 'admin', 'web')),
  created_at  timestamptz default now()
);
create index if not exists client_handles_client_idx on client_handles (client_id);

create table if not exists join_pending (
  handle       text primary key,
  display_name text not null,
  created_at   timestamptz not null
);

create table if not exists lines (
  id               text primary key,
  chert_agent_name text not null,
  active           bool not null default true
);

create table if not exists line_state (
  line_id       text primary key references lines(id) on delete cascade,
  state         text not null check (state in ('idle', 'claimed', 'in_call', 'offline')),
  user_id       uuid,
  call_id       text,
  claimed_until timestamptz,
  offline_until timestamptz,
  in_call_since timestamptz,
  updated_at    timestamptz not null,
  version       bigint not null default 0
);

create table if not exists queue (
  id               bigserial primary key,
  user_id          uuid not null references clients(id) on delete cascade,
  line_pref        text,
  entered_at       timestamptz not null,
  notified_at      timestamptz,
  claim_expires_at timestamptz,
  line_id          text,
  status           text not null check (status in ('waiting', 'notified', 'connected', 'no_show', 'left', 'expired'))
);
create unique index if not exists queue_one_active_per_user on queue (user_id) where status in ('waiting', 'notified');
create index if not exists queue_status_entered_idx on queue (status, entered_at);

create table if not exists calls (
  id                 text primary key,
  line_id            text,
  user_id            uuid,
  handle_raw         text,
  decision           text not null check (decision in ('accept', 'reject')),
  reject_reason      text,
  connected_at       timestamptz not null,
  count_end_at       timestamptz,
  ended_at           timestamptz,
  counted_toward_cap bool not null default false,
  liveness_result    text check (liveness_result in ('pass', 'fail', 'skipped') or liveness_result is null),
  void               bool not null default false,
  void_reason        text,
  session_id         uuid references sessions(id) on delete set null,
  committed_at       timestamptz,
  rep_count          int
);
create index if not exists calls_user_connected_idx on calls (user_id, connected_at);
create index if not exists calls_connected_idx on calls (connected_at);
create index if not exists calls_session_idx on calls (session_id);

create table if not exists competition_config (
  key        text primary key,
  value      jsonb not null,
  updated_by text,
  updated_at timestamptz not null default now()
);

create table if not exists power_hours (
  date_et              date primary key,
  starts_at            timestamptz not null,
  ends_at              timestamptz not null,
  announced_at         timestamptz,
  warned_at            timestamptz,
  started_announced_at timestamptz
);

create table if not exists messages (
  id                  bigserial primary key,
  direction           text check (direction in ('in', 'out')),
  handle              text not null,
  user_id             uuid,
  body                text,
  media_url           text,
  template            text,
  ctx                 jsonb,
  lease_until         timestamptz,
  dedupe_key          text unique,
  provider_message_id text unique,
  status              text not null,
  attempts            int default 0,
  last_error          text,
  not_before          timestamptz,
  created_at          timestamptz not null default now(),
  sent_at             timestamptz
);
alter table messages add column if not exists ctx jsonb;
alter table messages add column if not exists lease_until timestamptz;
alter table messages alter column body drop not null;
create index if not exists messages_outbox_idx on messages (status, not_before) where direction = 'out';
create index if not exists messages_handle_idx on messages (handle, created_at);

create table if not exists audit_log (
  id     bigserial primary key,
  actor  text not null,
  action text not null,
  target text,
  before jsonb,
  after  jsonb,
  reason text,
  at     timestamptz not null default now()
);
create index if not exists audit_log_at_idx on audit_log (at);

create table if not exists score_adjustments (
  id      bigserial primary key,
  user_id uuid not null references clients(id) on delete cascade,
  points  int not null,
  reason  text not null,
  actor   text not null,
  at      timestamptz not null default now()
);
create index if not exists score_adjustments_user_idx on score_adjustments (user_id);

create table if not exists rank_state (
  user_id           uuid primary key references clients(id) on delete cascade,
  rank              int,
  points            int,
  updated_at        timestamptz,
  last_drop_text_at timestamptz
);

create table if not exists admin_allowlist (email text primary key);

create table if not exists heartbeats (
  component text primary key,
  at        timestamptz not null,
  detail    jsonb
);

create table if not exists site_pulse (
  id        int primary key default 1 check (id = 1),
  bumped_at timestamptz not null
);

-- ---------------------------------------------------------------- seeds
insert into competition_config (key, value) values
  ('window_start',            to_jsonb('2026-10-12T20:00:00-04:00'::text)),
  ('window_end',              to_jsonb('2026-10-18T23:59:59-04:00'::text)),
  ('call_count_s',            '180'),
  ('call_reveal_s',           '15'),
  ('daily_call_cap',          '5'),
  ('claim_window_s',          '90'),
  ('line_offline_gap_s',      '180'),
  ('min_counted_call_s',      '30'),
  ('in_call_timeout_extra_s', '60'),
  ('power_hour_window',       '[12, 22]'),
  ('power_multiplier',        '2'),
  ('rank_drop_min',           '2'),
  ('rank_drop_throttle_h',    '3'),
  ('quiet_hours',             '[23, 9]'),
  ('recap_hour',              '10'),
  ('streak_risk_hour',        '20'),
  ('raffle_min_valid_reps',   '100'),
  ('raffle_prize',            '"TBD"'),
  ('avatar_level_thresholds', '[0, 25, 60, 120, 200, 300, 450, 650, 900, 1200]'),
  ('judge_thresholds',        '{"min_conf": 0.5, "frame_conf_frac": 0.9, "knee_min_deg": 160, "knee_floor_margin": 0.04,
                                "hip_line_max_dev_deg": 15, "depth_elbow_max_deg": 90, "depth_margin": 0.05,
                                "lockout_min_deg": 160, "min_rep_s": 0.8, "max_cadence_rpm": 60,
                                "classifier_veto": ["pushups - shallow", "pushups - insufficient", "pushups - elevated hips"],
                                "classifier_veto_substrings": ["knee", "sag"], "liveness_window_s": [45, 150],
                                "liveness_timeout_s": 4, "cue_min_gap_s": 4}'),
  ('registration_open',       'true'),
  ('competition_frozen',      'false'),
  ('swearing',                'false'),
  ('site_url',                '"https://brodie-pushups.vercel.app"'),
  ('brodie_number',           'null'),
  ('team_alert_handles',      '[]'),
  ('outbound_rate_per_min',   '20')
on conflict (key) do nothing;

-- Challenge coach: reuse the configured one, else one named 'Brodie Challenge', else create it.
do $$
declare v_coach uuid;
begin
  select c.id into v_coach from competition_config k join coaches c on c.id::text = k.value #>> '{}'
    where k.key = 'challenge_coach_id';
  if v_coach is null then
    select id into v_coach from coaches where name = 'Brodie Challenge' order by created_at, id limit 1;
  end if;
  if v_coach is null then
    insert into coaches (name) values ('Brodie Challenge') returning id into v_coach;
  end if;
  insert into competition_config (key, value) values ('challenge_coach_id', to_jsonb(v_coach::text))
    on conflict (key) do nothing;
end $$;

insert into lines (id, chert_agent_name, active) values ('line-1', 'brodie', true) on conflict (id) do nothing;
insert into line_state (line_id, state, updated_at) values ('line-1', 'idle', now()) on conflict (line_id) do nothing;
insert into site_pulse (id, bumped_at) values (1, now()) on conflict (id) do nothing;

-- ---------------------------------------------------------------- pure helpers
create or replace function ch_et_day(p_ts timestamptz) returns date
language sql immutable parallel safe as $$ select (p_ts at time zone 'America/New_York')::date $$;

create or replace function ch_et_day_start(p_day date) returns timestamptz
language sql immutable parallel safe as $$ select (p_day::timestamp at time zone 'America/New_York') $$;

create or replace function ch_level_for_points(p_points int, p_thresholds jsonb) returns int
language sql immutable parallel safe as $$
  select 1 + (select count(*)::int from jsonb_array_elements(
                case when jsonb_typeof(p_thresholds) = 'array' then p_thresholds else '[]'::jsonb end
              ) with ordinality as t(v, i)
              where t.i > 1 and jsonb_typeof(t.v) = 'number' and (t.v)::numeric <= coalesce(p_points, 0))
$$;

create or replace function ch_streak_days(p_days date[], p_today date) returns int
language plpgsql immutable parallel safe as $$
declare
  d date;
  n int := 0;
begin
  if p_days is null or p_today is null then return 0; end if;
  if p_today = any(p_days) then d := p_today;
  elsif p_today - 1 = any(p_days) then d := p_today - 1;
  else return 0;
  end if;
  while d = any(p_days) loop
    n := n + 1;
    d := d - 1;
  end loop;
  return n;
end;
$$;

-- ---------------------------------------------------------------- internal aggregate views
create or replace view ch_call_stats as
select c.id as call_id, c.user_id, c.line_id, c.decision, c.void, c.counted_toward_cap, c.liveness_result,
       c.connected_at, c.ended_at, c.committed_at, ch_et_day(c.connected_at) as date_et,
       coalesce(r.valid_reps, 0)::int as valid_reps, coalesce(r.rejected_reps, 0)::int as rejected_reps,
       coalesce(r.points, 0)::int as points, r.last_point_at, coalesce(r.reasons, '{}'::jsonb) as reasons
from calls c
left join lateral (
  with rr as (
    select rp.at, rp.points, rp.reject_reasons,
           coalesce(rp.valid is true and coalesce(rp.points, 0) > 0
                    and rp.at >= (select (value #>> '{}')::timestamptz from competition_config where key = 'window_start')
                    and rp.at < c.connected_at + make_interval(secs => coalesce(
                          (select (value #>> '{}')::numeric from competition_config where key = 'call_count_s'), 180)::double precision),
                    false) as ok
    from sets s join reps rp on rp.set_id = s.id
    where s.session_id = c.session_id
  )
  select count(*) filter (where ok) as valid_reps,
         count(*) filter (where not ok) as rejected_reps,
         sum(points) filter (where ok) as points,
         max(at) filter (where ok) as last_point_at,
         (select jsonb_object_agg(reason, n)
            from (select reason, count(*) as n from rr, unnest(rr.reject_reasons) as reason
                  where not rr.ok group by reason) x) as reasons
  from rr
) r on true;

create or replace view ch_user_stats as
with cs as (
  select * from ch_call_stats where decision = 'accept' and user_id is not null
), call_agg as (
  select user_id,
         sum(points) filter (where not void) as points,
         sum(valid_reps) filter (where not void) as valid_reps,
         max(last_point_at) filter (where not void) as last_point_at,
         array_agg(distinct date_et) filter (where counted_toward_cap and not void and valid_reps > 0) as streak_days,
         (array_agg(call_id order by points desc, connected_at asc) filter (where not void))[1] as best_call_id,
         max(points) filter (where not void) as best_call_points
  from cs group by user_id
), adj_agg as (
  select user_id, sum(points) as points, max(at) as last_at from score_adjustments group by user_id
), base as (
  select cl.id as user_id, cl.display_name, cl.joined_at, cl.banned_at, cl.opted_out_at,
         (coalesce(ca.points, 0) + coalesce(aa.points, 0))::int as points,
         coalesce(ca.valid_reps, 0)::int as valid_reps,
         case when ca.last_point_at is null then aa.last_at
              when aa.last_at is null then ca.last_point_at
              else greatest(ca.last_point_at, aa.last_at) end as reached_at,
         coalesce(ca.streak_days, '{}'::date[]) as streak_days,
         ca.best_call_id, ca.best_call_points,
         (cl.banned_at is null and cl.display_name is not null) as listed
  from clients cl
  left join call_agg ca on ca.user_id = cl.id
  left join adj_agg aa on aa.user_id = cl.id
  where cl.joined_at is not null
)
select b.user_id, b.display_name, b.joined_at, b.banned_at, b.opted_out_at, b.points, b.valid_reps, b.reached_at,
       b.streak_days, b.best_call_id, b.best_call_points,
       ch_level_for_points(b.points, (select value from competition_config where key = 'avatar_level_thresholds')) as avatar_level,
       b.listed,
       case when b.listed then row_number() over (
         partition by b.listed order by b.points desc, b.reached_at asc nulls last, b.joined_at asc, b.user_id) end::int as rank
from base b;

-- ---------------------------------------------------------------- service-role helpers
create or replace function ch_cfg(p_key text) returns jsonb
language sql stable security definer set search_path = public as $$
  select value from competition_config where key = p_key
$$;

create or replace function ch_calls_today(p_user_id uuid, p_now timestamptz) returns int
language sql stable security definer set search_path = public as $$
  select count(*)::int from calls
  where user_id = p_user_id and counted_toward_cap
    and connected_at >= ch_et_day_start(ch_et_day(p_now))
    and connected_at <  ch_et_day_start(ch_et_day(p_now) + 1)
$$;

create or replace function ch_user_points(p_user_id uuid) returns int
language sql stable security definer set search_path = public as $$
  select (coalesce((select sum(points) from ch_call_stats
                    where user_id = p_user_id and decision = 'accept' and not void), 0)
        + coalesce((select sum(points) from score_adjustments where user_id = p_user_id), 0))::int
$$;

create or replace function ch_valid_reps(p_user_id uuid) returns int
language sql stable security definer set search_path = public as $$
  select coalesce(sum(valid_reps), 0)::int from ch_call_stats
  where user_id = p_user_id and decision = 'accept' and not void
$$;

create or replace function ch_reached_at(p_user_id uuid) returns timestamptz
language sql stable security definer set search_path = public as $$
  select max(t) from (
    select last_point_at as t from ch_call_stats where user_id = p_user_id and decision = 'accept' and not void
    union all
    select at from score_adjustments where user_id = p_user_id
  ) x
$$;

create or replace function ch_streak(p_user_id uuid, p_now timestamptz) returns int
language sql stable security definer set search_path = public as $$
  select ch_streak_days(
    (select array_agg(distinct date_et) from ch_call_stats
      where user_id = p_user_id and decision = 'accept' and counted_toward_cap and not void and valid_reps > 0),
    ch_et_day(p_now))
$$;

create or replace function ch_avatar_level(p_points int) returns int
language sql stable security definer set search_path = public as $$
  select ch_level_for_points(p_points, (select value from competition_config where key = 'avatar_level_thresholds'))
$$;

-- ---------------------------------------------------------------- site pulse
create or replace function ch_bump_site_pulse() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if current_setting('ch.site_pulse_bumped', true) is distinct from '1' then
    perform set_config('ch.site_pulse_bumped', '1', true);
    insert into site_pulse (id, bumped_at) values (1, clock_timestamp())
      on conflict (id) do update set bumped_at = greatest(site_pulse.bumped_at, excluded.bumped_at);
  end if;
  return null;
end;
$$;

do $$
declare t text;
begin
  foreach t in array array['calls', 'reps', 'line_state', 'queue', 'score_adjustments', 'competition_config',
                           'power_hours', 'clients'] loop
    execute format('drop trigger if exists ch_site_pulse on %I', t);
    execute format('create constraint trigger ch_site_pulse after insert or update or delete on %I '
                   'deferrable initially deferred for each row execute function ch_bump_site_pulse()', t);
  end loop;
end $$;

-- ---------------------------------------------------------------- public views (anon-readable)
create or replace view leaderboard_public with (security_barrier = true) as
select s.rank, md5(s.user_id::text) as public_id, s.display_name, s.points, s.valid_reps,
       ch_streak_days(s.streak_days, ch_et_day(now())) as streak, s.avatar_level,
       array_remove(array[
         case when ch_streak_days(s.streak_days, ch_et_day(now())) >= 2 then 'streak' end,
         case when s.valid_reps >= coalesce((select (value #>> '{}')::int from competition_config
                                             where key = 'raffle_min_valid_reps'), 100) then 'raffle' end
       ], null)::text[] as badges,
       s.reached_at
from ch_user_stats s
where s.listed
order by s.rank;

create or replace view user_public with (security_barrier = true) as
select md5(s.user_id::text) as public_id, s.display_name, s.points, s.valid_reps,
       ch_streak_days(s.streak_days, ch_et_day(now())) as streak, s.avatar_level, s.rank, s.joined_at,
       s.best_call_points, s.best_call_id
from ch_user_stats s
where s.listed;

create or replace view user_daily_public with (security_barrier = true) as
select cl.display_name, cs.date_et,
       coalesce(sum(cs.points) filter (where not cs.void), 0)::int as points,
       coalesce(sum(cs.valid_reps) filter (where not cs.void), 0)::int as valid_reps,
       (count(*) filter (where cs.counted_toward_cap))::int as calls
from ch_call_stats cs
join clients cl on cl.id = cs.user_id
where cs.decision = 'accept' and cl.joined_at is not null and cl.banned_at is null and cl.display_name is not null
group by cl.id, cl.display_name, cs.date_et;

-- rank_after / total_points_after: standings as of the call's end (or connect time while live), counting non-void
-- accepted calls connected by then and adjustments made by then. Query by call_id (per-row laterals).
create or replace view call_result_public with (security_barrier = true) as
select cs.call_id, cl.display_name, cs.connected_at, cs.valid_reps, cs.rejected_reps, cs.points, cs.reasons,
       cs.liveness_result, cs.void, st.rank_after, st.total_points_after
from ch_call_stats cs
join clients cl on cl.id = cs.user_id
cross join lateral (
  with t as (select coalesce(cs.ended_at, cs.connected_at) as at),
  pts as (
    select u.user_id, sum(u.points)::int as points, max(u.reached) as reached_at
    from (
      select o.user_id, o.points, o.last_point_at as reached
        from ch_call_stats o, t
        where o.decision = 'accept' and not o.void and o.user_id is not null and o.connected_at <= t.at
      union all
      select a.user_id, a.points, a.at from score_adjustments a, t where a.at <= t.at
    ) u
    join clients c2 on c2.id = u.user_id
    where c2.banned_at is null and c2.display_name is not null and c2.joined_at is not null
    group by u.user_id
  ), me as (
    select coalesce((select points from pts where user_id = cs.user_id), 0) as points,
           (select reached_at from pts where user_id = cs.user_id) as reached_at
  )
  select (1 + (select count(*) from pts, me
               where pts.user_id <> cs.user_id
                 and (pts.points > me.points
                      or (pts.points = me.points and pts.reached_at < me.reached_at))))::int as rank_after,
         me.points as total_points_after
  from me
) st
where cs.decision = 'accept' and cl.banned_at is null and cl.display_name is not null;

create or replace view line_status_public with (security_barrier = true) as
with cfg as (
  select (select (value #>> '{}')::timestamptz from competition_config where key = 'window_start') as window_start,
         (select (value #>> '{}')::timestamptz from competition_config where key = 'window_end') as window_end,
         coalesce((select value = 'true'::jsonb from competition_config where key = 'competition_frozen'), false) as frozen,
         coalesce((select (value #>> '{}')::int from competition_config where key = 'call_count_s'), 180) as count_s,
         coalesce((select (value #>> '{}')::int from competition_config where key = 'call_reveal_s'), 15) as reveal_s,
         coalesce((select (value #>> '{}')::int from competition_config where key = 'line_offline_gap_s'), 180) as gap_s
), ls as (
  select s.state, s.updated_at from line_state s join lines l on l.id = s.line_id where l.active
), recent as (
  select extract(epoch from ended_at - connected_at) as dur from calls
  where decision = 'accept' and ended_at is not null order by connected_at desc limit 10
)
select case
         when cfg.frozen or (cfg.window_start is not null and now() < cfg.window_start)
              or (cfg.window_end is not null and now() >= cfg.window_end)
              or not exists (select 1 from ls) then 'closed'
         when exists (select 1 from ls where state = 'idle') then 'idle'
         when exists (select 1 from ls where state = 'claimed') then 'claimed'
         when exists (select 1 from ls where state = 'in_call') then 'in_call'
         else 'offline' end as state_summary,
       (select count(*) from queue where status = 'waiting')::int as queue_length,
       (select count(*) from ls)::int as lines_active,
       (coalesce((select round(avg(dur)) from recent), cfg.count_s + cfg.reveal_s) + cfg.gap_s)::int as eta_cycle_s,
       (select max(updated_at) from ls) as updated_at
from cfg;

create or replace view power_hour_public with (security_barrier = true) as
select date_et, starts_at, ends_at from power_hours
where announced_at is not null or starts_at <= now();

create or replace view competition_public with (security_barrier = true) as
with k as (select key, value from competition_config)
select (select (value #>> '{}')::timestamptz from k where key = 'window_start') as window_start,
       (select (value #>> '{}')::timestamptz from k where key = 'window_end') as window_end,
       (coalesce((select value = 'true'::jsonb from k where key = 'competition_frozen'), false)
        or coalesce(now() >= (select (value #>> '{}')::timestamptz from k where key = 'window_end'), false)) as frozen,
       (select value #>> '{}' from k where key = 'raffle_prize') as raffle_prize,
       (select (value #>> '{}')::int from k where key = 'raffle_min_valid_reps') as raffle_min_valid_reps,
       (select value #>> '{}' from k where key = 'brodie_number') as brodie_number,
       (select value #>> '{}' from k where key = 'site_url') as site_url;

-- ---------------------------------------------------------------- RLS + grants
do $$
declare
  t text;
  r record;
begin
  -- New tables: RLS on; anon/authenticated get nothing; service_role full DML.
  foreach t in array array['client_handles', 'join_pending', 'lines', 'line_state', 'queue', 'calls',
                           'competition_config', 'power_hours', 'messages', 'audit_log', 'score_adjustments',
                           'rank_state', 'admin_allowlist', 'heartbeats', 'site_pulse'] loop
    execute format('alter table %I enable row level security', t);
    execute format('revoke all on table %I from public, anon, authenticated', t);
    execute format('grant select, insert, update, delete on table %I to service_role', t);
  end loop;
  -- Existing tables: anon/authenticated never read base tables (RLS already blocked them; remove the grants too).
  foreach t in array array['coaches', 'clients', 'programs', 'program_days', 'assignments', 'sessions', 'sets',
                           'reps', 'muscle_scores'] loop
    execute format('revoke all on table %I from public, anon, authenticated', t);
  end loop;
  for r in select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
           where n.nspname = 'public' and c.relkind = 'S'
             and c.relname in ('queue_id_seq', 'messages_id_seq', 'audit_log_id_seq', 'score_adjustments_id_seq') loop
    execute format('revoke all on sequence %I from public, anon, authenticated', r.relname);
    execute format('grant usage, select on sequence %I to service_role', r.relname);
  end loop;
end $$;

drop policy if exists site_pulse_public_read on site_pulse;
create policy site_pulse_public_read on site_pulse for select to anon, authenticated using (true);
grant select on table site_pulse to anon, authenticated;

revoke all on table ch_call_stats, ch_user_stats from public, anon, authenticated;
grant select on table ch_call_stats, ch_user_stats to service_role;

revoke all on table leaderboard_public, user_public, user_daily_public, call_result_public, line_status_public,
  power_hour_public, competition_public from public, anon, authenticated;
grant select on table leaderboard_public, user_public, user_daily_public, call_result_public, line_status_public,
  power_hour_public, competition_public to anon, authenticated, service_role;

revoke all on function ch_et_day(timestamptz), ch_et_day_start(date), ch_level_for_points(int, jsonb),
  ch_streak_days(date[], date) from public;
grant execute on function ch_et_day(timestamptz), ch_et_day_start(date), ch_level_for_points(int, jsonb),
  ch_streak_days(date[], date) to anon, authenticated, service_role;

revoke all on function ch_cfg(text), ch_calls_today(uuid, timestamptz), ch_user_points(uuid), ch_valid_reps(uuid),
  ch_reached_at(uuid), ch_streak(uuid, timestamptz), ch_avatar_level(int), ch_bump_site_pulse()
  from public, anon, authenticated;
grant execute on function ch_cfg(text), ch_calls_today(uuid, timestamptz), ch_user_points(uuid), ch_valid_reps(uuid),
  ch_reached_at(uuid), ch_streak(uuid, timestamptz), ch_avatar_level(int) to service_role;

-- ---------------------------------------------------------------- realtime
do $$
begin
  if exists (select 1 from pg_publication where pubname = 'supabase_realtime')
     and not exists (select 1 from pg_publication_tables
                     where pubname = 'supabase_realtime' and schemaname = 'public' and tablename = 'site_pulse') then
    alter publication supabase_realtime add table site_pulse;
  end if;
end $$;

commit;
