-- Task 23: scheduled-jobs support. Idempotent; every function security definer, service_role only.
begin;

-- Small key/value state for the jobs loop (attempt counters, alert dedupe, queue-update baselines).
create table if not exists ch_job_state (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
alter table ch_job_state enable row level security;
revoke all on table ch_job_state from public, anon, authenticated;
grant select, insert, update, delete on table ch_job_state to service_role;

create or replace function ch_job_get(p_key text) returns jsonb
language sql stable security definer set search_path = public as $$
  select value from ch_job_state where key = p_key
$$;

create or replace function ch_job_list(p_prefix text) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_object_agg(key, value), '{}'::jsonb) from ch_job_state
  where left(key, length(p_prefix)) = p_prefix
$$;

create or replace function ch_job_set(p_key text, p_value jsonb, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  insert into ch_job_state (key, value, updated_at) values (p_key, p_value, p_now)
    on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function ch_job_delete(p_key text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  delete from ch_job_state where key = p_key;
  return jsonb_build_object('ok', true);
end;
$$;

-- Atomic attempt counter: {n, first_at}.
create or replace function ch_job_incr(p_key text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v jsonb;
begin
  insert into ch_job_state (key, value, updated_at)
    values (p_key, jsonb_build_object('n', 1, 'first_at', p_now), p_now)
    on conflict (key) do update
      set value = jsonb_build_object('n', coalesce((ch_job_state.value ->> 'n')::int, 0) + 1,
                                     'first_at', coalesce(ch_job_state.value -> 'first_at', to_jsonb(p_now))),
          updated_at = p_now
    returning value into v;
  return v;
end;
$$;

-- Post-call sweeper input: skip calls the jobs loop gave up on.
create or replace function ch_postcall_pending(p_now timestamptz, p_limit int default 50) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object('call_id', id, 'user_id', user_id) order by committed_at), '[]'::jsonb)
  from (select c.id, c.user_id, c.committed_at from calls c
         where c.decision = 'accept' and c.session_id is not null and c.postcall_done_at is null
           and c.committed_at < p_now - interval '30 seconds'
           and not exists (select 1 from ch_job_state s where s.key = 'postcall_giveup:' || c.id)
         order by c.committed_at limit greatest(p_limit, 0)) q
$$;

-- ---------------------------------------------------------------- timestamp-based freeze
-- A rep counts iff its timestamp < min(window_end, frozen_at). The freeze flag no longer rejects reps that
-- happened before the cutoff but are committed after it (calls spanning window_end).
-- Any flip of competition_frozen to true stamps frozen_at = now() (admin freeze). The jobs loop then
-- overrides it with window_end exactly (ch_set_frozen_at).
create or replace function ch_stamp_frozen_at() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.key = 'competition_frozen' and new.value = 'true'::jsonb
     and (tg_op = 'INSERT' or old.value is distinct from new.value) then
    insert into competition_config (key, value, updated_by) values ('frozen_at', to_jsonb(now()), 'trigger')
      on conflict (key) do update set value = excluded.value, updated_by = 'trigger', updated_at = now();
  end if;
  return new;
end;
$$;
drop trigger if exists ch_stamp_frozen_at on competition_config;
create trigger ch_stamp_frozen_at after insert or update on competition_config
  for each row execute function ch_stamp_frozen_at();

create or replace function ch_commit_reps(p_call_id text, p_payload jsonb, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_call calls;
  v_session uuid;
  v_set uuid;
  v_started timestamptz;
  v_ended timestamptz;
  v_live text;
  v_ws timestamptz := ch_calls_cfg_ts('window_start');
  v_we timestamptz := ch_calls_cfg_ts('window_end');
  v_frozen bool := coalesce((select value = 'true'::jsonb from competition_config where key = 'competition_frozen'), false);
  v_fz_at timestamptz := ch_calls_cfg_ts('frozen_at');  -- freeze cutoff; reps are judged by timestamp, not commit time
  v_count_s int := ch_calls_cfg_int('call_count_s', 180);
  v_mult int := ch_calls_cfg_int('power_multiplier', 2);
  v_total int;
  v_valid int;
  v_points int;
  v_reconcile bool;
  v_cend timestamptz;
  v_reps int;
begin
  if p_now is null then
    raise exception 'ch_commit_reps: p_now required';
  end if;
  if p_payload is null or jsonb_typeof(p_payload) <> 'object' then
    raise exception 'ch_commit_reps: payload must be a json object';
  end if;
  if p_payload ? 'reps' and jsonb_typeof(p_payload -> 'reps') not in ('array', 'null') then
    raise exception 'ch_commit_reps: payload.reps must be an array';
  end if;

  select * into v_call from calls where id = p_call_id for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'unknown_call');
  end if;
  if v_call.decision <> 'accept' then
    return jsonb_build_object('ok', false, 'reason', 'not_accepted');
  end if;
  if v_call.session_id is not null then
    select cs.valid_reps, cs.points into v_valid, v_points from ch_call_stats cs where cs.call_id = p_call_id;
    return jsonb_build_object('ok', true, 'session_id', v_call.session_id, 'valid_reps', coalesce(v_valid, 0),
                              'points', coalesce(v_points, 0), 'already', true);
  end if;

  v_live := case when p_payload ->> 'liveness_result' in ('pass', 'fail', 'skipped')
                 then p_payload ->> 'liveness_result' else v_call.liveness_result end;
  v_started := coalesce((p_payload ->> 'started_at')::timestamptz, v_call.connected_at);
  v_ended := coalesce((p_payload ->> 'ended_at')::timestamptz, v_call.ended_at, p_now);
  v_reconcile := v_call.end_reason = 'timeout' and (p_payload ->> 'ended_at') is not null;

  insert into sessions (client_id, started_at, ended_at) values (v_call.user_id, v_started, v_ended)
  returning id into v_session;
  insert into sets (session_id, exercise_key, set_number, planned_reps, completed_reps, started_at, ended_at)
  values (v_session, 'pushups', 1, 0, 0, v_started, v_ended)
  returning id into v_set;

  with raw as (
    select x.*, x.ordinality as ord
    from rows from (jsonb_to_recordset(case when jsonb_typeof(p_payload -> 'reps') = 'array'
                                            then p_payload -> 'reps' else '[]'::jsonb end)
                    as (n int, t real, at timestamptz, valid bool, reject_reasons text[], faults text[],
                        in_challenge bool, min_elbow_deg_l real, min_elbow_deg_r real, top_elbow_deg real,
                        max_hip_line_dev_deg real, min_knee_deg real, knee_floor_contact bool,
                        shoulder_wrist_drop real, shoulder_elbow_gap real, min_keypoint_conf real,
                        frame_conf_frac real, persons_in_frame int, rep_duration_s real, torso_ok bool, side text,
                        classifier_labels text[], judge_version text)) with ordinality as x
  ), timed as (
    select r.*, coalesce(r.at, v_started + make_interval(secs => coalesce(r.t, 0)::float8)) as at_f
    from raw r
  ), scored as (
    select tm.*,
           case when (v_frozen and (v_fz_at is null or tm.at_f >= v_fz_at)) or (v_we is not null and tm.at_f >= v_we) then 'after_freeze'
                when v_ws is not null and tm.at_f < v_ws then 'before_start'
                when tm.at_f >= v_call.connected_at + make_interval(secs => v_count_s) then 'after_count'
                when v_live = 'fail' then 'liveness_fail' end as extra,
           case when exists (select 1 from power_hours ph
                              where ph.date_et = ch_et_day(tm.at_f) and tm.at_f >= ph.starts_at and tm.at_f < ph.ends_at)
                then v_mult else 1 end as mult
    from timed tm
  ), final as (
    select s.*,
           (coalesce(s.valid, false) and not coalesce(s.in_challenge, false) and s.extra is null) as vf,
           (row_number() over (order by coalesce(s.n, s.ord), s.ord))::int as rn
    from scored s
  )
  insert into reps (set_id, rep_number, t, faults, valid, reject_reasons, multiplier, points, at,
                    min_elbow_deg_l, min_elbow_deg_r, top_elbow_deg, max_hip_line_dev_deg, min_knee_deg,
                    knee_floor_contact, shoulder_wrist_drop, shoulder_elbow_gap, min_keypoint_conf, frame_conf_frac,
                    persons_in_frame, rep_duration_s, torso_ok, side, classifier_labels, in_challenge, judge_version)
  select v_set, f.rn, coalesce(f.t, extract(epoch from f.at_f - v_started)::real), coalesce(f.faults, '{}'),
         f.vf,
         case when f.extra is null or f.extra = any(coalesce(f.reject_reasons, '{}')) then coalesce(f.reject_reasons, '{}')
              else coalesce(f.reject_reasons, '{}') || f.extra end,
         f.mult, case when f.vf then f.mult else 0 end, f.at_f,
         f.min_elbow_deg_l, f.min_elbow_deg_r, f.top_elbow_deg, f.max_hip_line_dev_deg, f.min_knee_deg,
         f.knee_floor_contact, f.shoulder_wrist_drop, f.shoulder_elbow_gap, f.min_keypoint_conf, f.frame_conf_frac,
         f.persons_in_frame, f.rep_duration_s, f.torso_ok, f.side, f.classifier_labels, coalesce(f.in_challenge, false),
         coalesce(f.judge_version, p_payload ->> 'judge_version')
  from final f;

  select count(*)::int, (count(*) filter (where valid))::int, coalesce(sum(points), 0)::int
    into v_total, v_valid, v_points
  from reps where set_id = v_set;
  update sets set completed_reps = v_valid where id = v_set;

  v_reps := greatest(coalesce(v_call.rep_count, 0), v_total);
  if v_reconcile then
    -- late commit after a tick timeout: the worker's ended_at replaces the provisional one; full recompute
    v_cend := greatest(v_ended, v_call.connected_at);
    update calls
       set session_id = v_session, committed_at = p_now, liveness_result = v_live, rep_count = v_reps,
           ended_at = v_cend, end_reason = 'commit',
           counted_toward_cap = ch_calls_counted(decision, connected_at, v_cend, v_reps)
     where id = p_call_id;
    insert into audit_log (actor, action, target, before, after, reason, at)
    values ('system', 'call:reconcile', p_call_id,
            jsonb_build_object('ended_at', v_call.ended_at, 'counted_toward_cap', v_call.counted_toward_cap),
            jsonb_build_object('ended_at', v_cend,
                               'counted_toward_cap', ch_calls_counted(v_call.decision, v_call.connected_at, v_cend, v_reps)),
            'commit after timeout', p_now);
  else
    update calls
       set session_id = v_session, committed_at = p_now, liveness_result = v_live, rep_count = v_reps,
           counted_toward_cap = counted_toward_cap or ch_calls_counted(decision, connected_at, ended_at, v_reps)
     where id = p_call_id;
  end if;

  return jsonb_build_object('ok', true, 'session_id', v_session, 'valid_reps', v_valid, 'points', v_points,
                            'already', false);
end;
$$;


-- Atomic claim: true iff the key was absent or last claimed >= p_gap_s ago (serializes concurrent callers).
create or replace function ch_job_claim(p_key text, p_now timestamptz, p_gap_s int) returns boolean
language plpgsql volatile security definer set search_path = public as $$
declare
  v_key text;
begin
  insert into ch_job_state (key, value, updated_at) values (p_key, jsonb_build_object('at', p_now), p_now)
    on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at
      where ch_job_state.updated_at <= p_now - make_interval(secs => p_gap_s)
    returning key into v_key;
  return v_key is not null;
end;
$$;

-- Queue-position update: the intent (deduped per user + time bucket) and the user's baseline state are
-- written in ONE transaction, so concurrent dispatchers cannot both send.
create or replace function ch_queue_update_notify(p_user_id uuid, p_state_key text, p_state jsonb, p_ctx jsonb,
                                                  p_bucket_s int, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_bucket bigint := floor(extract(epoch from p_now) / greatest(p_bucket_s, 1));
  v_res jsonb;
begin
  v_res := ch_outbox_enqueue(null, p_user_id, 'queue_update', null, null,
                             'queue_update:' || p_user_id || ':' || v_bucket, null, p_now, p_ctx);
  if not (v_res ->> 'duplicate')::bool then
    insert into ch_job_state (key, value, updated_at) values (p_state_key, p_state, p_now)
      on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;
  end if;
  return v_res;
end;
$$;

-- Audited override of the freeze cutoff (the jobs loop sets it to window_end exactly).
create or replace function ch_set_frozen_at(p_at timestamptz, p_actor text, p_reason text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_before jsonb;
begin
  perform ch_require_reason(p_reason, p_actor);
  select value into v_before from competition_config where key = 'frozen_at';
  insert into competition_config (key, value, updated_by) values ('frozen_at', to_jsonb(p_at), p_actor)
    on conflict (key) do update set value = excluded.value, updated_by = excluded.updated_by, updated_at = now();
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, 'config:frozen_at', 'frozen_at', v_before, to_jsonb(p_at), p_reason);
  return jsonb_build_object('ok', true);
end;
$$;

-- ---------------------------------------------------------------- power hours
create or replace function ch_power_hour_row(p_date_et date) returns jsonb
language sql stable security definer set search_path = public as $$
  select to_jsonb(ph) from power_hours ph where ph.date_et = p_date_et
$$;

create or replace function ch_power_hour_ensure(p_date_et date, p_starts_at timestamptz, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  insert into power_hours (date_et, starts_at, ends_at)
    values (p_date_et, p_starts_at, p_starts_at + interval '1 hour')
    on conflict (date_et) do nothing;
  return (select to_jsonb(ph) from power_hours ph where ph.date_et = p_date_et);
end;
$$;

-- p_kind: announced | warned | started. Sets the timestamp once.
create or replace function ch_power_hour_mark(p_date_et date, p_kind text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  if p_kind not in ('announced', 'warned', 'started') then
    raise exception 'bad power hour mark %', p_kind using errcode = '22023';
  end if;
  update power_hours set
    announced_at = case when p_kind = 'announced' then coalesce(announced_at, p_now) else announced_at end,
    warned_at = case when p_kind = 'warned' then coalesce(warned_at, p_now) else warned_at end,
    started_announced_at = case when p_kind = 'started' then coalesce(started_announced_at, p_now) else started_announced_at end
   where date_et = p_date_et;
  return jsonb_build_object('ok', found);
end;
$$;

-- ---------------------------------------------------------------- audience for proactive texts
-- Registered, not opted out, not banned, reachable (has a handle).
create or replace function ch_jobs_audience(p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  with y as (
    select user_id, sum(points)::int as pts from ch_score_events
     where ch_et_day(at) = ch_et_day(p_now) - 1 group by user_id
  )
  select coalesce(jsonb_agg(jsonb_build_object(
      'user_id', s.user_id, 'display_name', s.display_name, 'points', s.points, 'rank', s.rank,
      'streak', ch_streak(s.user_id, p_now), 'yesterday_points', coalesce(y.pts, 0),
      'qualified_today', ch_et_day(p_now) = any(s.streak_days),
      'calls_today', ch_calls_today(s.user_id, p_now)) order by s.rank), '[]'::jsonb)
  from ch_user_stats s left join y on y.user_id = s.user_id
  where s.listed and s.opted_out_at is null
    and exists (select 1 from client_handles h where h.client_id = s.user_id)
$$;

-- ---------------------------------------------------------------- health snapshot for alerts
create or replace function ch_jobs_health(p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'lines', coalesce((select jsonb_agg(jsonb_build_object('line_id', ls.line_id, 'state', ls.state,
                                                           'updated_at', ls.updated_at))
                         from line_state ls join lines l on l.id = ls.line_id where l.active), '[]'::jsonb),
    'queue_len', (select count(*) from queue where status in ('waiting', 'notified')),
    'out_sent', (select count(*) from messages where direction = 'out' and status = 'sent'
                   and created_at > p_now - interval '15 minutes'),
    'out_failed', (select count(*) from messages where direction = 'out' and status = 'failed'
                     and created_at > p_now - interval '15 minutes'),
    'heartbeats', coalesce((select jsonb_object_agg(component, at) from heartbeats), '{}'::jsonb))
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in (
             'ch_commit_reps', 'ch_job_get', 'ch_job_list', 'ch_job_set', 'ch_job_delete', 'ch_job_incr', 'ch_postcall_pending',
             'ch_power_hour_row', 'ch_power_hour_ensure', 'ch_power_hour_mark', 'ch_jobs_audience',
             'ch_jobs_health', 'ch_job_claim', 'ch_queue_update_notify', 'ch_set_frozen_at') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
