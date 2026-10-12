-- Push-Up Challenge, migration 2: call lifecycle, line state machine, queue RPCs.
-- Contract: docs/challenge/CONTRACTS.md §C2 (RPCs ch_call_start, ch_call_end, ch_commit_reps, ch_tick, ch_queue_join,
-- ch_queue_leave, ch_queue_view + Derived rules) and §C7. Idempotent (create or replace only).
--
-- Locking (deadlock-free order, every mutating RPC):
--   1. ALL line_state rows `for update` ordered by line_id (ch_calls_lock_lines) — this serializes every line/queue
--      mutation, so cross-line invariants (a user is in at most one of {active queue entry, claim holder, in_call})
--      can be checked without races;
--   2. per-user pg_advisory_xact_lock(hashtextextended(user_id::text, 0)) (ch_calls_lock_user);
--   3. queue rows / calls row `for update`.
--   ch_commit_reps touches no line/queue rows: it only locks the calls row (same position 3), so it never waits for a
--   line lock while holding a calls row.
-- Every line_state change bumps version and writes audit_log (actor 'system', action 'line:<old>-><new>').
-- Frozen (ch_calls_frozen) = competition_frozen config true OR p_now >= window_end. Before window_start calls are
--   rejected (reason 'not_started', cue 'competition_over') and ch_tick does not pop.
-- Walk-in (chert_meta): line idle AND no waiting/notified queue entry of ANOTHER user (a caller whose own fresh entry is
--   still waiting is the one the scheduler would pop next; their entry becomes 'connected').
-- Scoring at commit (persisted; aggregates in migration 1 read reps.valid/points as stored):
--   extra reason (priority): after_freeze (competition_frozen at commit, or at >= window_end) > before_start
--   (at < window_start) > after_count (at >= connected_at + call_count_s) > liveness_fail (liveness_result = 'fail').
--   reps.valid = valid AND NOT in_challenge AND extra is null; multiplier = power_multiplier when
--   at ∈ [starts_at, ends_at) of power_hours(ch_et_day(at)) else 1; points = valid ? multiplier : 0.
-- counted_toward_cap = accept AND (ended_at - connected_at >= min_counted_call_s OR rep_count >= 1); recomputed by
--   ch_call_end, ch_commit_reps and the ch_tick timeout (whichever runs last sees both inputs). rep_count is the max of
--   the worker-reported count and the committed rep count.
-- ch_queue_join on an opted-out user re-subscribes them (clears opted_out_at) and joins: reason 'opted_out_ok'.

begin;

-- ---------------------------------------------------------------- internal helpers
create or replace function ch_calls_cfg_int(p_key text, p_default int) returns int
language sql stable security definer set search_path = public as $$
  select coalesce((select (value #>> '{}')::numeric::int from competition_config
                   where key = p_key and jsonb_typeof(value) in ('number', 'string')), p_default)
$$;

create or replace function ch_calls_cfg_ts(p_key text) returns timestamptz
language sql stable security definer set search_path = public as $$
  select (value #>> '{}')::timestamptz from competition_config where key = p_key and jsonb_typeof(value) = 'string'
$$;

create or replace function ch_calls_frozen(p_now timestamptz) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce((select value = 'true'::jsonb from competition_config where key = 'competition_frozen'), false)
      or coalesce(p_now >= ch_calls_cfg_ts('window_end'), false)
$$;

create or replace function ch_calls_cue(p_reason text) returns text
language sql immutable as $$
  select case p_reason
           when 'ok' then null
           when 'not_registered' then 'not_signed_up'
           when 'at_cap' then 'at_cap'
           when 'frozen' then 'competition_over'
           when 'not_started' then 'competition_over'
           else 'not_your_turn' end
$$;

create or replace function ch_calls_counted(p_decision text, p_connected_at timestamptz, p_ended_at timestamptz,
                                            p_rep_count int) returns bool
language sql stable security definer set search_path = public as $$
  select p_decision = 'accept'
     and ((p_ended_at is not null
           and extract(epoch from p_ended_at - p_connected_at) >= ch_calls_cfg_int('min_counted_call_s', 30))
          or coalesce(p_rep_count, 0) >= 1)
$$;

create or replace function ch_calls_lock_lines() returns void
language plpgsql security definer set search_path = public as $$
begin
  perform 1 from line_state order by line_id for update;
end;
$$;

create or replace function ch_calls_lock_user(p_user_id uuid) returns void
language plpgsql security definer set search_path = public as $$
begin
  if p_user_id is not null then
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  end if;
end;
$$;

-- Caller must hold the line_state row lock.
create or replace function ch_calls_line_set(p_line_id text, p_state text, p_user_id uuid, p_call_id text,
                                             p_claimed_until timestamptz, p_offline_until timestamptz,
                                             p_in_call_since timestamptz, p_now timestamptz, p_reason text)
returns void
language plpgsql security definer set search_path = public as $$
declare
  v_old line_state;
  v_new line_state;
begin
  select * into v_old from line_state where line_id = p_line_id;
  if not found then
    raise exception 'ch_calls_line_set: unknown line %', p_line_id;
  end if;
  update line_state
     set state = p_state, user_id = p_user_id, call_id = p_call_id, claimed_until = p_claimed_until,
         offline_until = p_offline_until, in_call_since = p_in_call_since, updated_at = p_now, version = version + 1
   where line_id = p_line_id
  returning * into v_new;
  insert into audit_log (actor, action, target, before, after, reason, at)
  values ('system', 'line:' || v_old.state || '->' || p_state, p_line_id, to_jsonb(v_old), to_jsonb(v_new), p_reason, p_now);
end;
$$;

create or replace function ch_calls_queue_set(p_queue_id bigint, p_status text, p_now timestamptz, p_reason text,
                                              p_line_id text default null, p_claim_expires_at timestamptz default null)
returns void
language plpgsql security definer set search_path = public as $$
declare
  v_old queue;
  v_new queue;
begin
  select * into v_old from queue where id = p_queue_id;
  update queue
     set status = p_status,
         notified_at = case when p_status = 'notified' then p_now else notified_at end,
         claim_expires_at = case when p_status = 'notified' then p_claim_expires_at else claim_expires_at end,
         line_id = coalesce(p_line_id, line_id)
   where id = p_queue_id
  returning * into v_new;
  insert into audit_log (actor, action, target, before, after, reason, at)
  values ('system', 'queue:' || v_old.status || '->' || p_status, p_queue_id::text, to_jsonb(v_old), to_jsonb(v_new),
          p_reason, p_now);
end;
$$;

-- Outbox intent (same transaction as the state change). Users without a handle get none.
create or replace function ch_calls_notify(p_user_id uuid, p_template text, p_ctx jsonb, p_dedupe_key text,
                                           p_now timestamptz) returns void
language plpgsql security definer set search_path = public as $$
declare
  v_handle text;
begin
  select h.handle into v_handle from client_handles h
   where h.client_id = p_user_id
   order by (h.kind = 'phone') desc nulls last, h.created_at nulls last, h.handle
   limit 1;
  if v_handle is null then
    return;
  end if;
  insert into messages (direction, handle, user_id, template, ctx, dedupe_key, status, not_before, created_at)
  values ('out', v_handle, p_user_id, p_template, p_ctx, p_dedupe_key, 'queued', p_now, p_now)
  on conflict (dedupe_key) do nothing;
end;
$$;

-- Waiting entries in pop order (calls_today asc, entered_at asc, id asc) with 1-based position.
create or replace function ch_calls_waiting(p_now timestamptz)
returns table (queue_id bigint, user_id uuid, entered_at timestamptz, calls_today int, pos int)
language sql stable security definer set search_path = public as $$
  select w.id, w.user_id, w.entered_at, w.ct,
         (row_number() over (order by w.ct, w.entered_at, w.id))::int
  from (select q.id, q.user_id, q.entered_at, ch_calls_today(q.user_id, p_now) as ct
        from queue q where q.status = 'waiting') w
$$;

create or replace function ch_calls_start_result(p_call calls) returns jsonb
language sql immutable as $$
  select jsonb_build_object('decision', p_call.decision, 'user_id', p_call.user_id,
                            'reason', coalesce(p_call.reject_reason, 'ok'),
                            'cue', ch_calls_cue(coalesce(p_call.reject_reason, 'ok')))
$$;

-- ---------------------------------------------------------------- ch_call_start
create or replace function ch_call_start(p_call_id text, p_line_id text, p_handle text, p_mode text,
                                         p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_call calls;
  v_ls line_state;
  v_user uuid;
  v_client clients;
  v_reason text;
  v_ws timestamptz := ch_calls_cfg_ts('window_start');
  v_q record;
begin
  if p_call_id is null or p_call_id = '' then
    raise exception 'ch_call_start: call_id required';
  end if;
  if p_mode is null or p_mode not in ('chert_meta', 'claim_window') then
    raise exception 'ch_call_start: bad mode %', p_mode;
  end if;
  if p_now is null then
    raise exception 'ch_call_start: p_now required';
  end if;

  perform ch_calls_lock_lines();
  select * into v_call from calls where id = p_call_id;
  if found then
    return ch_calls_start_result(v_call);
  end if;

  select ls.* into v_ls from line_state ls join lines l on l.id = ls.line_id where ls.line_id = p_line_id and l.active;
  if not found then
    v_reason := 'line_inactive';
  elsif v_ws is not null and p_now < v_ws then
    v_reason := 'not_started';
  elsif ch_calls_frozen(p_now) then
    v_reason := 'frozen';
  elsif p_mode = 'chert_meta' then
    select h.client_id into v_user from client_handles h join clients c on c.id = h.client_id
     where h.handle = p_handle and c.joined_at is not null;
    if v_user is null then
      v_reason := 'not_registered';
    end if;
  else
    if v_ls.state = 'claimed' and v_ls.claimed_until > p_now and v_ls.user_id is not null then
      v_user := v_ls.user_id;
    else
      v_reason := 'not_your_turn';
    end if;
  end if;

  if v_reason is null then
    perform ch_calls_lock_user(v_user);
    select * into v_client from clients where id = v_user;
    if v_client.banned_at is not null then
      v_reason := 'banned';
    elsif exists (select 1 from line_state where user_id = v_user and line_id <> p_line_id
                                              and state in ('claimed', 'in_call')) then
      v_reason := 'not_your_turn';
    elsif ch_calls_today(v_user, p_now) >= ch_calls_cfg_int('daily_call_cap', 5) then
      v_reason := 'at_cap';
    elsif v_ls.state = 'claimed' and v_ls.claimed_until > p_now and v_ls.user_id = v_user then
      v_reason := null;  -- claim holder
    elsif p_mode = 'chert_meta' and v_ls.state = 'idle'
          and not exists (select 1 from queue where status in ('waiting', 'notified') and user_id <> v_user) then
      v_reason := null;  -- walk-in
    else
      v_reason := 'not_your_turn';
    end if;
  end if;

  if v_reason is null then
    for v_q in select id from queue where user_id = v_user and status in ('waiting', 'notified') order by id for update loop
      perform ch_calls_queue_set(v_q.id, 'connected', p_now, 'call_start ' || p_call_id, p_line_id);
    end loop;
    perform ch_calls_line_set(p_line_id, 'in_call', v_user, p_call_id, null, null, p_now, p_now,
                              'call_start ' || p_call_id);
  end if;

  insert into calls (id, line_id, user_id, handle_raw, decision, reject_reason, connected_at)
  values (p_call_id, p_line_id, v_user, p_handle, case when v_reason is null then 'accept' else 'reject' end,
          v_reason, p_now)
  returning * into v_call;
  if v_reason is not null then
    insert into audit_log (actor, action, target, after, reason, at)
    values ('system', 'call:reject', p_call_id,
            jsonb_build_object('line_id', p_line_id, 'user_id', v_user, 'mode', p_mode), v_reason, p_now);
  end if;
  return ch_calls_start_result(v_call);
end;
$$;

-- ---------------------------------------------------------------- ch_call_end
create or replace function ch_call_end(p_call_id text, p_ended_at timestamptz, p_count_end_at timestamptz,
                                       p_rep_count int, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_call calls;
  v_ls line_state;
  v_ended timestamptz;
  v_reps int;
begin
  if p_now is null then
    raise exception 'ch_call_end: p_now required';
  end if;
  select * into v_call from calls where id = p_call_id;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'unknown_call', 'counted_toward_cap', false);
  end if;
  if v_call.decision <> 'accept' then
    return jsonb_build_object('ok', true, 'reason', 'not_accepted', 'counted_toward_cap', false);
  end if;

  perform ch_calls_lock_lines();
  perform ch_calls_lock_user(v_call.user_id);
  select * into v_call from calls where id = p_call_id for update;

  v_ended := greatest(coalesce(p_ended_at, p_now), v_call.connected_at);
  v_reps := greatest(coalesce(p_rep_count, 0), coalesce(v_call.rep_count, 0));
  update calls
     set ended_at = v_ended,
         count_end_at = coalesce(p_count_end_at, count_end_at),
         rep_count = v_reps,
         counted_toward_cap = ch_calls_counted(decision, connected_at, v_ended, v_reps)
   where id = p_call_id
  returning * into v_call;

  select * into v_ls from line_state where line_id = v_call.line_id;
  if found and v_ls.state = 'in_call' and v_ls.call_id = p_call_id then
    perform ch_calls_line_set(v_ls.line_id, 'offline', null, null, null,
                              p_now + make_interval(secs => ch_calls_cfg_int('line_offline_gap_s', 180)), null, p_now,
                              'call_end ' || p_call_id);
  end if;
  return jsonb_build_object('ok', true, 'counted_toward_cap', v_call.counted_toward_cap);
end;
$$;

-- ---------------------------------------------------------------- ch_commit_reps
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
  v_count_s int := ch_calls_cfg_int('call_count_s', 180);
  v_mult int := ch_calls_cfg_int('power_multiplier', 2);
  v_total int;
  v_valid int;
  v_points int;
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
           case when v_frozen or (v_we is not null and tm.at_f >= v_we) then 'after_freeze'
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

  update calls
     set session_id = v_session,
         committed_at = p_now,
         liveness_result = v_live,
         rep_count = greatest(coalesce(rep_count, 0), v_total),
         counted_toward_cap = ch_calls_counted(decision, connected_at, ended_at, greatest(coalesce(rep_count, 0), v_total))
   where id = p_call_id;

  return jsonb_build_object('ok', true, 'session_id', v_session, 'valid_reps', v_valid, 'points', v_points,
                            'already', false);
end;
$$;

-- ---------------------------------------------------------------- ch_tick
create or replace function ch_tick(p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_ls line_state;
  v_q queue;
  v_call calls;
  v_cand record;
  v_r record;
  v_cap int := ch_calls_cfg_int('daily_call_cap', 5);
  v_count_s int := ch_calls_cfg_int('call_count_s', 180);
  v_reveal_s int := ch_calls_cfg_int('call_reveal_s', 15);
  v_extra_s int := ch_calls_cfg_int('in_call_timeout_extra_s', 60);
  v_gap_s int := ch_calls_cfg_int('line_offline_gap_s', 180);
  v_claim_s int := ch_calls_cfg_int('claim_window_s', 90);
  v_ws timestamptz := ch_calls_cfg_ts('window_start');
  v_until timestamptz;
  v_ended timestamptz;
  v_no_shows jsonb := '[]'::jsonb;
  v_claims jsonb := '[]'::jsonb;
  v_timeouts jsonb := '[]'::jsonb;
  v_idled jsonb := '[]'::jsonb;
begin
  if p_now is null then
    raise exception 'ch_tick: p_now required';
  end if;
  perform ch_calls_lock_lines();

  -- 1. per-line timers
  for v_ls in select ls.* from line_state ls join lines l on l.id = ls.line_id where l.active order by ls.line_id loop
    if v_ls.state = 'claimed' and (v_ls.claimed_until is null or v_ls.claimed_until <= p_now) then
      perform ch_calls_lock_user(v_ls.user_id);
      select * into v_q from queue
       where user_id = v_ls.user_id and status = 'notified' and (line_id is null or line_id = v_ls.line_id)
       order by id desc limit 1 for update;
      if found then
        perform ch_calls_queue_set(v_q.id, 'no_show', p_now, 'claim expired');
        v_no_shows := v_no_shows || jsonb_build_object('user_id', v_q.user_id, 'queue_id', v_q.id);
        perform ch_calls_notify(v_q.user_id, 'missed_slot',
                                jsonb_build_object('queue_id', v_q.id, 'line_id', v_ls.line_id),
                                'missed_slot:' || v_q.id, p_now);
      end if;
      perform ch_calls_line_set(v_ls.line_id, 'idle', null, null, null, null, null, p_now, 'claim expired');
      v_idled := v_idled || to_jsonb(v_ls.line_id);
    elsif v_ls.state = 'in_call'
          and coalesce(v_ls.in_call_since, '-infinity'::timestamptz)
              + make_interval(secs => v_count_s + v_reveal_s + v_extra_s) <= p_now then
      perform ch_calls_lock_user(v_ls.user_id);
      select * into v_call from calls where id = v_ls.call_id for update;
      if found then
        v_ended := coalesce(v_call.ended_at,
                            least(coalesce(v_ls.in_call_since, v_call.connected_at)
                                  + make_interval(secs => v_count_s + v_reveal_s), p_now));
        update calls
           set ended_at = v_ended,
               counted_toward_cap = ch_calls_counted(decision, connected_at, v_ended, rep_count)
         where id = v_call.id;
        insert into audit_log (actor, action, target, after, reason, at)
        values ('system', 'call:timeout', v_call.id, jsonb_build_object('ended_at', v_ended), 'in_call timeout', p_now);
      end if;
      perform ch_calls_line_set(v_ls.line_id, 'offline', null, null, null, p_now + make_interval(secs => v_gap_s), null,
                                p_now, 'in_call timeout');
      if v_ls.call_id is not null then
        v_timeouts := v_timeouts || to_jsonb(v_ls.call_id);
      end if;
    elsif v_ls.state = 'offline' and (v_ls.offline_until is null or v_ls.offline_until <= p_now) then
      perform ch_calls_line_set(v_ls.line_id, 'idle', null, null, null, null, null, p_now, 'offline gap elapsed');
      v_idled := v_idled || to_jsonb(v_ls.line_id);
    end if;
  end loop;

  -- 2. expire waiting entries of users now at cap / banned / opted out
  for v_r in
    select q.id, q.user_id from queue q join clients c on c.id = q.user_id
     where q.status = 'waiting'
       and (c.banned_at is not null or c.opted_out_at is not null or ch_calls_today(q.user_id, p_now) >= v_cap)
     order by q.user_id, q.id
  loop
    perform ch_calls_lock_user(v_r.user_id);
    perform 1 from queue where id = v_r.id and status = 'waiting' for update;
    if found then
      perform ch_calls_queue_set(v_r.id, 'expired', p_now, 'ineligible');
    end if;
  end loop;

  -- 3. pop for each idle line (not before window_start, not when frozen / after window_end)
  if not ch_calls_frozen(p_now) and (v_ws is null or p_now >= v_ws) then
    for v_ls in select ls.* from line_state ls join lines l on l.id = ls.line_id
                 where l.active and ls.state = 'idle' order by ls.line_id loop
      select w.queue_id, w.user_id into v_cand
        from ch_calls_waiting(p_now) w join clients c on c.id = w.user_id
       where w.calls_today < v_cap and c.banned_at is null and c.opted_out_at is null and c.joined_at is not null
         and not exists (select 1 from line_state x where x.user_id = w.user_id and x.state in ('claimed', 'in_call'))
       order by w.pos
       limit 1;
      if not found then
        exit;
      end if;
      perform ch_calls_lock_user(v_cand.user_id);
      perform 1 from queue where id = v_cand.queue_id and status = 'waiting' for update;
      if not found then
        raise exception 'ch_tick: queue entry % changed under line lock', v_cand.queue_id;
      end if;
      v_until := p_now + make_interval(secs => v_claim_s);
      perform ch_calls_queue_set(v_cand.queue_id, 'notified', p_now, 'pop', v_ls.line_id, v_until);
      perform ch_calls_line_set(v_ls.line_id, 'claimed', v_cand.user_id, null, v_until, null, null, p_now,
                                'pop queue ' || v_cand.queue_id);
      perform ch_calls_notify(v_cand.user_id, 'youre_up',
                              jsonb_build_object('queue_id', v_cand.queue_id, 'line_id', v_ls.line_id,
                                                 'claimed_until', v_until, 'claim_window_s', v_claim_s),
                              'youre_up:' || v_cand.queue_id, p_now);
      v_claims := v_claims || jsonb_build_object('line_id', v_ls.line_id, 'user_id', v_cand.user_id,
                                                 'queue_id', v_cand.queue_id, 'claimed_until', v_until);
    end loop;
  end if;

  return jsonb_build_object('no_shows', v_no_shows, 'claims', v_claims, 'timeouts', v_timeouts, 'idled', v_idled);
end;
$$;

-- ---------------------------------------------------------------- queue RPCs
create or replace function ch_queue_join(p_user_id uuid, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_client clients;
  v_cap int := ch_calls_cfg_int('daily_call_cap', 5);
  v_ct int := 0;
  v_reason text;
  v_qid bigint;
  v_pos int;
  v_line_open bool;
begin
  if p_now is null then
    raise exception 'ch_queue_join: p_now required';
  end if;
  perform ch_calls_lock_lines();
  perform ch_calls_lock_user(p_user_id);
  perform 1 from queue where user_id = p_user_id and status in ('waiting', 'notified') for update;

  select * into v_client from clients where id = p_user_id;
  if found then
    v_ct := ch_calls_today(p_user_id, p_now);
  end if;
  v_line_open := exists (select 1 from line_state ls join lines l on l.id = ls.line_id where l.active and ls.state = 'idle')
                 and not exists (select 1 from queue where status = 'waiting' and user_id is distinct from p_user_id)
                 and not ch_calls_frozen(p_now);

  if v_client.id is null or v_client.joined_at is null then
    v_reason := 'not_registered';
  elsif v_client.banned_at is not null then
    v_reason := 'banned';
  elsif ch_calls_frozen(p_now) then
    v_reason := 'frozen';
  elsif exists (select 1 from queue where user_id = p_user_id and status in ('waiting', 'notified'))
        or exists (select 1 from line_state where user_id = p_user_id and state = 'claimed') then
    v_reason := 'already';
  elsif exists (select 1 from line_state where user_id = p_user_id and state = 'in_call') then
    v_reason := 'in_call';
  elsif v_ct >= v_cap then
    v_reason := 'at_cap';
  else
    if v_client.opted_out_at is not null then
      update clients set opted_out_at = null where id = p_user_id;
      insert into audit_log (actor, action, target, before, after, reason, at)
      values ('system', 'user:opt_in', p_user_id::text, jsonb_build_object('opted_out_at', v_client.opted_out_at),
              jsonb_build_object('opted_out_at', null), 'queue join', p_now);
      v_reason := 'opted_out_ok';
    else
      v_reason := 'ok';
    end if;
    insert into queue (user_id, entered_at, status) values (p_user_id, p_now, 'waiting') returning id into v_qid;
    insert into audit_log (actor, action, target, after, reason, at)
    values ('system', 'queue:join', v_qid::text, jsonb_build_object('user_id', p_user_id), v_reason, p_now);
  end if;

  if v_reason in ('ok', 'opted_out_ok', 'already') then
    select w.pos into v_pos from ch_calls_waiting(p_now) w where w.user_id = p_user_id;
    v_pos := coalesce(v_pos, 0);  -- 0 = holds a claim / notified
  end if;
  return jsonb_build_object('ok', v_reason in ('ok', 'opted_out_ok', 'already'), 'reason', v_reason,
                            'position', v_pos, 'calls_today', v_ct, 'calls_left', greatest(v_cap - v_ct, 0),
                            'line_open', v_line_open);
end;
$$;

create or replace function ch_queue_leave(p_user_id uuid, p_reason text, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_q record;
  v_ls record;
  v_was bool := false;
begin
  if p_reason is null or p_reason not in ('left', 'stop') then
    raise exception 'ch_queue_leave: bad reason %', p_reason;
  end if;
  if p_now is null then
    raise exception 'ch_queue_leave: p_now required';
  end if;
  perform ch_calls_lock_lines();
  perform ch_calls_lock_user(p_user_id);
  for v_q in select id from queue where user_id = p_user_id and status in ('waiting', 'notified') order by id for update loop
    perform ch_calls_queue_set(v_q.id, 'left', p_now, p_reason);
    v_was := true;
  end loop;
  for v_ls in select line_id from line_state where user_id = p_user_id and state = 'claimed' order by line_id loop
    perform ch_calls_line_set(v_ls.line_id, 'idle', null, null, null, null, null, p_now, 'claim holder ' || p_reason);
    v_was := true;
  end loop;
  return jsonb_build_object('ok', true, 'was_queued', v_was);
end;
$$;

create or replace function ch_queue_view(p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'lines', coalesce((
      select jsonb_agg(jsonb_build_object('line_id', ls.line_id, 'state', ls.state, 'user_id', ls.user_id,
                                          'call_id', ls.call_id, 'claimed_until', ls.claimed_until,
                                          'offline_until', ls.offline_until, 'in_call_since', ls.in_call_since)
                       order by ls.line_id)
      from line_state ls join lines l on l.id = ls.line_id where l.active), '[]'::jsonb),
    'queue', coalesce((
      select jsonb_agg(jsonb_build_object('queue_id', q.id, 'user_id', q.user_id, 'display_name', c.display_name,
                                          'status', q.status, 'entered_at', q.entered_at,
                                          'calls_today', ch_calls_today(q.user_id, p_now),
                                          'position', coalesce(w.pos, 0))
                       order by coalesce(w.pos, 0), q.id)
      from queue q join clients c on c.id = q.user_id
      left join ch_calls_waiting(p_now) w on w.queue_id = q.id
      where q.status in ('waiting', 'notified')), '[]'::jsonb),
    'avg_cycle_s', (
      coalesce((select round(avg(extract(epoch from r.ended_at - r.connected_at)))
                from (select ended_at, connected_at from calls
                      where decision = 'accept' and ended_at is not null
                      order by connected_at desc limit 10) r),
               ch_calls_cfg_int('call_count_s', 180) + ch_calls_cfg_int('call_reveal_s', 15))
      + ch_calls_cfg_int('line_offline_gap_s', 180))::int)
$$;

-- ---------------------------------------------------------------- grants (service_role only)
revoke all on function
  ch_calls_cfg_int(text, int), ch_calls_cfg_ts(text), ch_calls_frozen(timestamptz), ch_calls_cue(text),
  ch_calls_counted(text, timestamptz, timestamptz, int), ch_calls_lock_lines(), ch_calls_lock_user(uuid),
  ch_calls_line_set(text, text, uuid, text, timestamptz, timestamptz, timestamptz, timestamptz, text),
  ch_calls_queue_set(bigint, text, timestamptz, text, text, timestamptz),
  ch_calls_notify(uuid, text, jsonb, text, timestamptz), ch_calls_waiting(timestamptz), ch_calls_start_result(calls),
  ch_call_start(text, text, text, text, timestamptz), ch_call_end(text, timestamptz, timestamptz, int, timestamptz),
  ch_commit_reps(text, jsonb, timestamptz), ch_tick(timestamptz), ch_queue_join(uuid, timestamptz),
  ch_queue_leave(uuid, text, timestamptz), ch_queue_view(timestamptz)
  from public, anon, authenticated;
grant execute on function
  ch_calls_cfg_int(text, int), ch_calls_cfg_ts(text), ch_calls_frozen(timestamptz), ch_calls_cue(text),
  ch_calls_counted(text, timestamptz, timestamptz, int), ch_calls_lock_lines(), ch_calls_lock_user(uuid),
  ch_calls_line_set(text, text, uuid, text, timestamptz, timestamptz, timestamptz, timestamptz, text),
  ch_calls_queue_set(bigint, text, timestamptz, text, text, timestamptz),
  ch_calls_notify(uuid, text, jsonb, text, timestamptz), ch_calls_waiting(timestamptz), ch_calls_start_result(calls),
  ch_call_start(text, text, text, text, timestamptz), ch_call_end(text, timestamptz, timestamptz, int, timestamptz),
  ch_commit_reps(text, jsonb, timestamptz), ch_tick(timestamptz), ch_queue_join(uuid, timestamptz),
  ch_queue_leave(uuid, text, timestamptz), ch_queue_view(timestamptz)
  to service_role;

commit;
