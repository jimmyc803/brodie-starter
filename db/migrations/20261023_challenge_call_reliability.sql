-- Call-path reliability before public launch (audit P0-1, P1-1, P1-2, P2-1, P2-2). Idempotent (create or replace /
-- if not exists); full current definitions are copied from the latest migration that defined each function.
--
-- 1. Griefer / short-call protection (P0-1). In claim_window mode any caller during a claim is attributed to the claim
--    holder (calls.via_claim = true; calls.queue_id = the holder's queue entry that the call consumed). Such a call
--    that ends with duration < min_counted_call_s AND zero valid reps is cap-exempt (never counted toward the
--    holder's daily cap), and the holder gets the turn back: their entry goes back to 'notified' with a fresh
--    claim_window_s claim on the call's line and a new "you're up" text (dedupe 'youre_up:<queue_id>:restore:<call_id>').
--    At most once per queue entry (queue.turn_restores): a second short call on the restored claim is a normal call
--    (the entry stays 'connected'). Valid reps are known once committed; before the commit a call with rep_count = 0
--    has none. The check runs (ch_calls_settle) after ch_call_end, ch_commit_reps and the ch_tick in_call timeout, so
--    whichever of end/commit arrives last decides; retries are no-ops (calls.turn_restored_at, queue status checks).
--    If the line cannot be claimed (busy with another user, or the worker heartbeat is stale) the entry goes back to
--    'waiting' at the front (entered_at moved before every waiting entry) instead.
-- 2. In_call timeout (P1-2): a call ended by the ch_tick timeout with no commit and rep_count 0 is cap-exempt (any mode)
--    and its holder's entry gets the same one-time restore (it is no longer left 'connected'). A later commit
--    replaces the provisional end as before and the exemption is recomputed from the committed data.
--    counted_toward_cap = ch_calls_counted(...) AND NOT ch_calls_cap_exempt(call); both are functions of persisted
--    call data, so retries cannot flip it.
-- 3. Dial grace (P2-1): ch_call_start accepts the claim holder until claimed_until + claim_grace_s (config, default 10);
--    ch_tick expires a claim only after the grace too, so the line cannot be re-claimed by someone else meanwhile.
--    The advertised deadline (claimed_until, youre_up text) is unchanged.
-- 4. Worker liveness gate (P1-1): ch_tick does not pop a new claim (no "you're up") onto a line whose worker heartbeat
--    (heartbeats 'worker:<line_id>') is older than worker_stale_s (config, default 120; 0 disables; a line that never
--    beat is not gated). Such lines are returned in the tick result as 'held' (key present only when non-empty;
--    likewise 'restored'), and the jobs loop alerts once per hold.
-- 5. ch_postcall (P2-2): ch_rank_deltas (recomputes ch_user_stats for every user) runs before the line lock, so it no
--    longer blocks ch_call_start / ch_tick. A per-call advisory lock serializes concurrent ch_postcall runs of one call
--    so the drops consumed in rank_state are always written as intents by the run that commits.
--    Lock order: advisory 'ch_postcall:<call>' -> rank_state (inside ch_rank_deltas) -> line_state rows -> user -> rows.
--    Nothing that holds the line lock takes either of the first two.
-- ch_commit_reps now takes the line lock + user lock BEFORE the calls row lock (same global order), because it may
-- restore a turn.
begin;

alter table calls add column if not exists via_claim bool not null default false;
alter table calls add column if not exists queue_id bigint;
alter table calls add column if not exists turn_restored_at timestamptz;
alter table queue add column if not exists turn_restores int not null default 0;

-- Config seeds. The deploy role may lack the privilege on competition_config: then this is a notice and the code
-- defaults (claim_grace_s 10, worker_stale_s 120) apply until the rows are added with the service role.
do $$
begin
  insert into competition_config (key, value, updated_by)
  values ('claim_grace_s', '10'::jsonb, 'migration:call_reliability'),
         ('worker_stale_s', '120'::jsonb, 'migration:call_reliability')
  on conflict (key) do nothing;
exception when insufficient_privilege then
  raise notice 'call_reliability: no privilege for competition_config; add claim_grace_s / worker_stale_s with the service role';
end
$$;

-- ---------------------------------------------------------------- helpers
-- true when the line's worker heartbeat exists and is older than worker_stale_s (0 disables the gate)
create or replace function ch_calls_line_stale(p_line_id text, p_now timestamptz) returns bool
language sql stable security definer set search_path = public as $$
  select case when ch_calls_cfg_int('worker_stale_s', 120) <= 0 then false
              else coalesce((select h.at < p_now - make_interval(secs => ch_calls_cfg_int('worker_stale_s', 120))
                               from heartbeats h where h.component = 'worker:' || p_line_id), false) end
$$;

-- The FaceTime handle named in a youre_up text for a line (see 20261019_challenge_sim_fixes.sql 1c).
create or replace function ch_calls_line_handle(p_line_id text) returns text
language sql stable security definer set search_path = public as $$
  select coalesce(nullif(btrim(l.facetime_handle), ''),
                  case when (select count(*) from lines x where x.active) = 1
                       then nullif(btrim(ch_cfg('brodie_number') #>> '{}'), '') end,
                  l.chert_agent_name)
    from lines l where l.id = p_line_id
$$;

-- Cap exemption (see header 1 and 2). A function of persisted call data only.
create or replace function ch_calls_cap_exempt(p_call calls) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce(p_call.decision = 'accept' and p_call.ended_at is not null and (
           (p_call.via_claim
            and extract(epoch from p_call.ended_at - p_call.connected_at) < ch_calls_cfg_int('min_counted_call_s', 30)
            and case when p_call.session_id is not null
                     then not exists (select 1 from sets s join reps r on r.set_id = s.id
                                       where s.session_id = p_call.session_id
                                         and r.valid is true and coalesce(r.points, 0) > 0)
                     else coalesce(p_call.rep_count, 0) = 0 end)
           or (p_call.end_reason = 'timeout' and p_call.session_id is null and coalesce(p_call.rep_count, 0) = 0)),
         false)
$$;

-- Applies the cap exemption and the one-time turn restore for an ended call. Caller holds the line lock and the
-- call user's lock (ch_calls_lock_lines, ch_calls_lock_user). Idempotent.
create or replace function ch_calls_settle(p_call_id text, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_call calls;
  v_q queue;
  v_client clients;
  v_ls line_state;
  v_target bigint;
  v_active queue;
  v_until timestamptz;
  v_claim_s int := ch_calls_cfg_int('claim_window_s', 90);
  v_ws timestamptz := ch_calls_cfg_ts('window_start');
  v_exempt bool;
  v_how text;
begin
  select * into v_call from calls where id = p_call_id for update;
  if not found or v_call.decision <> 'accept' then
    return jsonb_build_object('cap_exempt', false, 'restored', null);
  end if;
  v_exempt := ch_calls_cap_exempt(v_call);
  if v_exempt and v_call.counted_toward_cap then
    update calls set counted_toward_cap = false where id = p_call_id;
  end if;
  if not v_exempt or v_call.turn_restored_at is not null or v_call.queue_id is null then
    return jsonb_build_object('cap_exempt', v_exempt, 'restored', null);
  end if;

  select * into v_q from queue where id = v_call.queue_id for update;
  if not found or v_q.status <> 'connected' or v_q.user_id is distinct from v_call.user_id or v_q.turn_restores > 0 then
    return jsonb_build_object('cap_exempt', v_exempt, 'restored', null);
  end if;
  select * into v_client from clients where id = v_call.user_id;
  if v_client.banned_at is not null or v_client.opted_out_at is not null or v_client.joined_at is null
     or ch_calls_frozen(p_now) or (v_ws is not null and p_now < v_ws)
     or ch_calls_today(v_call.user_id, p_now) >= ch_calls_cfg_int('daily_call_cap', 5)
     or exists (select 1 from line_state where user_id = v_call.user_id and state in ('claimed', 'in_call')) then
    return jsonb_build_object('cap_exempt', v_exempt, 'restored', null);
  end if;
  -- the user may have texted QUEUE again meanwhile (one active entry per user): that entry takes the turn
  select * into v_active from queue where user_id = v_call.user_id and status in ('waiting', 'notified')
   order by id desc limit 1 for update;
  if found and v_active.status = 'notified' then
    return jsonb_build_object('cap_exempt', v_exempt, 'restored', null);
  end if;
  v_target := coalesce(v_active.id, v_q.id);

  update queue set turn_restores = turn_restores + 1 where id in (v_q.id, v_target);
  update calls set turn_restored_at = p_now where id = p_call_id;

  select ls.* into v_ls from line_state ls join lines l on l.id = ls.line_id
   where ls.line_id = v_call.line_id and l.active;
  if found and v_ls.state in ('idle', 'offline') and not ch_calls_line_stale(v_ls.line_id, p_now) then
    v_until := p_now + make_interval(secs => v_claim_s);
    perform ch_calls_queue_set(v_target, 'notified', p_now, 'turn restored after call ' || p_call_id, v_ls.line_id,
                               v_until);
    perform ch_calls_line_set(v_ls.line_id, 'claimed', v_call.user_id, null, v_until, null, null, p_now,
                              'turn restored after call ' || p_call_id || ' queue ' || v_target);
    perform ch_calls_notify(v_call.user_id, 'youre_up',
                            jsonb_build_object('queue_id', v_target, 'line_id', v_ls.line_id,
                                               'line_handle', ch_calls_line_handle(v_ls.line_id),
                                               'claimed_until', v_until, 'expires_at', v_until,
                                               'claim_window_s', v_claim_s, 'restored', true),
                            'youre_up:' || v_target || ':restore:' || p_call_id, p_now);
    v_how := 'claimed';
  else
    -- line busy / worker stale: back to the front of the waiting queue (same calls_today tier)
    if v_target = v_q.id then
      perform ch_calls_queue_set(v_target, 'waiting', p_now, 'turn restored after call ' || p_call_id || ' (line busy)');
    end if;
    update queue
       set entered_at = least(entered_at, coalesce((select min(entered_at) from queue
                                                     where status = 'waiting' and id <> v_target), entered_at)
                                          - interval '1 millisecond')
     where id = v_target;
    v_how := 'waiting';
  end if;
  insert into audit_log (actor, action, target, after, reason, at)
  values ('system', 'call:turn_restored', p_call_id,
          jsonb_build_object('queue_id', v_target, 'user_id', v_call.user_id, 'line_id', v_call.line_id, 'how', v_how,
                             'claimed_until', v_until, 'cap_exempt', v_exempt),
          case when v_call.end_reason = 'timeout' then 'in_call timeout without commit'
               else 'short call without valid reps' end, p_now);
  return jsonb_build_object('cap_exempt', v_exempt, 'restored', v_how, 'queue_id', v_target, 'user_id', v_call.user_id,
                            'line_id', v_call.line_id, 'claimed_until', v_until);
end;
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
  v_grace interval := make_interval(secs => greatest(ch_calls_cfg_int('claim_grace_s', 10), 0));
  v_qid bigint;
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
    if v_ls.state = 'claimed' and v_ls.claimed_until + v_grace > p_now and v_ls.user_id is not null then
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
                                              and (state = 'in_call' or (state = 'claimed' and claimed_until > p_now))) then
      v_reason := 'not_your_turn';
    elsif ch_calls_today(v_user, p_now) >= ch_calls_cfg_int('daily_call_cap', 5) then
      v_reason := 'at_cap';
    elsif v_ls.state = 'claimed' and v_ls.claimed_until + v_grace > p_now and v_ls.user_id = v_user then
      v_reason := null;  -- claim holder (dial grace: until claimed_until + claim_grace_s)
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
      v_qid := v_q.id;  -- the entry this call consumed (one active entry per user)
    end loop;
    -- an expired (not yet ticked) claim of this user on another line is stale: release it with the connect
    for v_q in select line_id from line_state where user_id = v_user and line_id <> p_line_id and state = 'claimed'
                order by line_id loop
      perform ch_calls_line_set(v_q.line_id, 'idle', null, null, null, null, null, p_now,
                                'stale claim released by call_start ' || p_call_id);
    end loop;
    perform ch_calls_line_set(p_line_id, 'in_call', v_user, p_call_id, null, null, p_now, p_now,
                              'call_start ' || p_call_id);
  elsif v_reason in ('banned', 'at_cap') and v_user is not null and v_ls.state = 'claimed'
        and v_ls.claimed_until + v_grace > p_now and v_ls.user_id = v_user then
    -- the claim holder can never use this claim: release it now (queue entry expired, line idle)
    for v_q in select id from queue where user_id = v_user and status in ('waiting', 'notified') order by id for update loop
      perform ch_calls_queue_set(v_q.id, 'expired', p_now, 'call_start ' || p_call_id || ' ' || v_reason);
    end loop;
    perform ch_calls_line_set(p_line_id, 'idle', null, null, null, null, null, p_now,
                              'claim holder rejected ' || v_reason || ' call_start ' || p_call_id);
  end if;

  insert into calls (id, line_id, user_id, handle_raw, decision, reject_reason, connected_at, via_claim, queue_id)
  values (p_call_id, p_line_id, v_user, p_handle, case when v_reason is null then 'accept' else 'reject' end,
          v_reason, p_now, v_reason is null and p_mode = 'claim_window', case when v_reason is null then v_qid end)
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

  v_reps := greatest(coalesce(p_rep_count, 0), coalesce(v_call.rep_count, 0));
  if v_call.ended_at is not null and v_call.end_reason = 'timeout' and p_ended_at is not null then
    -- explicit end replaces the provisional tick-timeout end once; full recompute
    v_ended := greatest(p_ended_at, v_call.connected_at);
    update calls
       set ended_at = v_ended, end_reason = 'end',
           count_end_at = coalesce(p_count_end_at, count_end_at),
           rep_count = v_reps,
           counted_toward_cap = ch_calls_counted(decision, connected_at, v_ended, v_reps)
     where id = p_call_id
    returning * into v_call;
  else
    -- first end wins; retries only add reps and can only turn counted_toward_cap on
    v_ended := coalesce(v_call.ended_at, greatest(coalesce(p_ended_at, p_now), v_call.connected_at));
    update calls
       set ended_at = v_ended, end_reason = coalesce(end_reason, 'end'),
           count_end_at = coalesce(count_end_at, p_count_end_at),
           rep_count = v_reps,
           counted_toward_cap = counted_toward_cap or ch_calls_counted(decision, connected_at, v_ended, v_reps)
     where id = p_call_id
    returning * into v_call;
  end if;

  select * into v_ls from line_state where line_id = v_call.line_id;
  if found and v_ls.state = 'in_call' and v_ls.call_id = p_call_id then
    perform ch_calls_line_set(v_ls.line_id, 'offline', null, null, null,
                              p_now + make_interval(secs => ch_calls_cfg_int('line_offline_gap_s', 180)), null, p_now,
                              'call_end ' || p_call_id);
  end if;
  -- short claim-window call without valid reps: not counted, the holder gets the turn back (once)
  perform ch_calls_settle(p_call_id, p_now);
  select * into v_call from calls where id = p_call_id;
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

  -- a first commit may restore a turn (ch_calls_settle): take the line lock and the user lock BEFORE the calls row
  -- lock (global lock order); retries and rejected calls stay line-lock free
  select * into v_call from calls where id = p_call_id;
  if found and v_call.decision = 'accept' and v_call.session_id is null then
    perform ch_calls_lock_lines();
    perform ch_calls_lock_user(v_call.user_id);
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
  -- valid reps are known now: apply the cap exemption / one-time turn restore if the call already ended
  perform ch_calls_settle(p_call_id, p_now);

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
  v_frozen bool;
  v_we timestamptz := ch_calls_cfg_ts('window_end');
  v_closed bool;
  v_line_handle text;
  v_grace interval := make_interval(secs => greatest(ch_calls_cfg_int('claim_grace_s', 10), 0));
  v_held jsonb := '[]'::jsonb;
  v_restored jsonb := '[]'::jsonb;
  v_settle jsonb;
  v_out jsonb;
begin
  if p_now is null then
    raise exception 'ch_tick: p_now required';
  end if;
  perform ch_calls_lock_lines();
  v_frozen := ch_calls_frozen(p_now);                -- window_end reached OR admin competition_frozen
  v_closed := v_we is not null and p_now >= v_we;    -- window_end reached: the queue is closed for good

  -- 1. per-line timers
  for v_ls in select ls.* from line_state ls join lines l on l.id = ls.line_id where l.active order by ls.line_id loop
    -- a claim expires after the dial grace (ch_call_start still accepts the holder until then)
    if v_ls.state = 'claimed' and (v_ls.claimed_until is null or v_ls.claimed_until + v_grace <= p_now) then
      perform ch_calls_lock_user(v_ls.user_id);
      select * into v_q from queue
       where user_id = v_ls.user_id and status = 'notified' and (line_id is null or line_id = v_ls.line_id)
       order by id desc limit 1 for update;
      if found then
        if v_closed then
          -- the claim could not be used (calls are refused once frozen) and QUEUE is refused: no missed_slot text
          perform ch_calls_queue_set(v_q.id, 'expired', p_now, 'frozen');
        elsif v_frozen then
          -- admin pause: keep the user's place (original entered_at); popping resumes when the pause ends
          perform ch_calls_queue_set(v_q.id, 'waiting', p_now, 'claim expired while paused');
        else
          perform ch_calls_queue_set(v_q.id, 'no_show', p_now, 'claim expired');
          v_no_shows := v_no_shows || jsonb_build_object('user_id', v_q.user_id, 'queue_id', v_q.id);
          -- expires_at: a "text QUEUE" nudge is stale after 30 min (e.g. deferred by quiet hours) and never valid
          -- after window_end; the outbox suppresses it instead of sending late (ch_outbox_claim + Outbox._deliver)
          perform ch_calls_notify(v_q.user_id, 'missed_slot',
                                  jsonb_build_object('queue_id', v_q.id, 'line_id', v_ls.line_id,
                                                     'expires_at', case when v_we is null then p_now + interval '30 minutes'
                                                                        else least(p_now + interval '30 minutes', v_we) end),
                                  'missed_slot:' || v_q.id, p_now);
        end if;
      end if;
      perform ch_calls_line_set(v_ls.line_id, 'idle', null, null, null, null, null, p_now, 'claim expired');
      v_idled := v_idled || to_jsonb(v_ls.line_id);
    elsif v_ls.state = 'in_call'
          and coalesce(v_ls.in_call_since, '-infinity'::timestamptz)
              + make_interval(secs => v_count_s + v_reveal_s + v_extra_s) <= p_now then
      perform ch_calls_lock_user(v_ls.user_id);
      v_call := null;
      select * into v_call from calls where id = v_ls.call_id for update;
      if found then
        v_ended := coalesce(v_call.ended_at,
                            least(coalesce(v_ls.in_call_since, v_call.connected_at)
                                  + make_interval(secs => v_count_s + v_reveal_s), p_now));
        update calls
           set ended_at = v_ended,
               end_reason = case when ended_at is null then 'timeout' else end_reason end,
               counted_toward_cap = counted_toward_cap or ch_calls_counted(decision, connected_at, v_ended, rep_count)
         where id = v_call.id;
        insert into audit_log (actor, action, target, after, reason, at)
        values ('system', 'call:timeout', v_call.id, jsonb_build_object('ended_at', v_ended), 'in_call timeout', p_now);
      end if;
      perform ch_calls_line_set(v_ls.line_id, 'offline', null, null, null, p_now + make_interval(secs => v_gap_s), null,
                                p_now, 'in_call timeout');
      if v_ls.call_id is not null then
        v_timeouts := v_timeouts || to_jsonb(v_ls.call_id);
      end if;
      if v_call.id is not null then
        -- no commit and no reps: not counted, and the holder's entry is not left 'connected' (one-time restore)
        v_settle := ch_calls_settle(v_call.id, p_now);
        if v_settle ->> 'restored' is not null then
          v_restored := v_restored || jsonb_build_object('call_id', v_call.id, 'user_id', v_settle -> 'user_id',
                                                         'queue_id', v_settle -> 'queue_id', 'line_id', v_ls.line_id,
                                                         'how', v_settle -> 'restored');
        end if;
      end if;
    elsif v_ls.state = 'offline' and (v_ls.offline_until is null or v_ls.offline_until <= p_now) then
      perform ch_calls_line_set(v_ls.line_id, 'idle', null, null, null, null, null, p_now, 'offline gap elapsed');
      v_idled := v_idled || to_jsonb(v_ls.line_id);
    end if;
  end loop;

  -- 2. expire waiting entries of users now at cap / banned / opted out, and every waiting entry once window_end is
  --    reached (SPEC §7: freeze at window_end stops popping AND closes the queue; an admin pause only stops popping)
  for v_r in
    select q.id, q.user_id from queue q join clients c on c.id = q.user_id
     where q.status = 'waiting'
       and (v_closed or c.banned_at is not null or c.opted_out_at is not null
            or ch_calls_today(q.user_id, p_now) >= v_cap)
     order by q.user_id, q.id
  loop
    perform ch_calls_lock_user(v_r.user_id);
    perform 1 from queue where id = v_r.id and status = 'waiting' for update;
    if found then
      perform ch_calls_queue_set(v_r.id, 'expired', p_now, case when v_closed then 'frozen' else 'ineligible' end);
    end if;
  end loop;

  -- 3. pop for each idle line (not before window_start, not when frozen / after window_end)
  if not v_frozen and (v_ws is null or p_now >= v_ws) then
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
      -- worker liveness gate: never text "you're up" for a line whose worker stopped beating; hold the queue
      -- (someone is waiting; another live line may still take them)
      if ch_calls_line_stale(v_ls.line_id, p_now) then
        v_held := v_held || to_jsonb(v_ls.line_id);
        continue;
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
      v_line_handle := ch_calls_line_handle(v_ls.line_id);
      -- one notification per claim ATTEMPT: an entry re-popped after an admin pause keeps its queue id (and place),
      -- so later attempts get 'youre_up:<queue_id>:<epoch ms>' (the first keeps 'youre_up:<queue_id>')
      perform ch_calls_notify(v_cand.user_id, 'youre_up',
                              jsonb_build_object('queue_id', v_cand.queue_id, 'line_id', v_ls.line_id,
                                                 'line_handle', v_line_handle, 'claimed_until', v_until,
                                                 'expires_at', v_until, 'claim_window_s', v_claim_s),
                              case when exists (select 1 from messages where dedupe_key = 'youre_up:' || v_cand.queue_id)
                                   then 'youre_up:' || v_cand.queue_id || ':'
                                        || (extract(epoch from p_now) * 1000)::bigint
                                   else 'youre_up:' || v_cand.queue_id end,
                              p_now);
      v_claims := v_claims || jsonb_build_object('line_id', v_ls.line_id, 'user_id', v_cand.user_id,
                                                 'queue_id', v_cand.queue_id, 'claimed_until', v_until);
    end loop;
  end if;

  v_out := jsonb_build_object('no_shows', v_no_shows, 'claims', v_claims, 'timeouts', v_timeouts, 'idled', v_idled);
  if jsonb_array_length(v_held) > 0 then
    v_out := v_out || jsonb_build_object('held', v_held);
  end if;
  if jsonb_array_length(v_restored) > 0 then
    v_out := v_out || jsonb_build_object('restored', v_restored);
  end if;
  return v_out;
end;
$$;

-- ---------------------------------------------------------------- ch_postcall
-- One transaction: post_call intent + unthrottled rank_drop intents + calls.postcall_done_at.
-- Lock order: advisory 'ch_postcall:<call>' -> rank_state (ch_rank_deltas) -> line_state rows -> user advisory lock
-- -> rows. ch_rank_deltas runs BEFORE the line lock (P2-2: it recomputes every user's standing and must not block
-- ch_call_start / ch_tick). The per-call advisory lock makes a concurrent run of the same call wait and then see
-- postcall_done_at, so drops are consumed only by the run that writes their intents. Idempotent; a failure rolls
-- everything back (including rank_state), so a rank drop is never consumed without its intent being written.
create or replace function ch_postcall(p_call_id text, p_now timestamptz, p_card_delivery text default 'link')
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_call   calls;
  v_site   text := coalesce(ch_cfg('site_url') #>> '{}', 'https://brodie-pushups.vercel.app');
  v_url    text;
  v_st     jsonb;
  v_stats  record;
  v_ctx    jsonb;
  v_drops  int := 0;
  d        record;
  v_deltas jsonb;
begin
  if p_now is null then
    raise exception 'ch_postcall: p_now required';
  end if;
  select * into v_call from calls where id = p_call_id;
  if not found or v_call.decision <> 'accept' or v_call.user_id is null then
    return jsonb_build_object('ok', false, 'reason', 'not_accepted');
  end if;
  if v_call.session_id is null then
    return jsonb_build_object('ok', false, 'reason', 'not_committed');
  end if;

  -- only ch_postcall sets postcall_done_at, and it does so under this lock
  perform pg_advisory_xact_lock(hashtextextended('ch_postcall:' || p_call_id, 0));
  if (select postcall_done_at from calls where id = p_call_id) is not null then
    return jsonb_build_object('ok', true, 'already', true);
  end if;
  v_deltas := ch_rank_deltas(p_now);  -- outside the line lock (P2-2)

  perform ch_calls_lock_lines();
  perform ch_calls_lock_user(v_call.user_id);
  select * into v_call from calls where id = p_call_id for update;
  if v_call.postcall_done_at is not null then
    return jsonb_build_object('ok', true, 'already', true);
  end if;

  select * into v_stats from ch_call_stats where call_id = p_call_id;
  v_st := ch_user_status(v_call.user_id, p_now);
  v_url := rtrim(v_site, '/') || '/r/' || p_call_id;
  v_ctx := jsonb_build_object(
    'valid_reps', v_stats.valid_reps, 'rejected_reps', v_stats.rejected_reps, 'points_earned', v_stats.points,
    'points', coalesce(v_st -> 'points', '0'::jsonb), 'rank', coalesce(v_st -> 'rank', '"-"'::jsonb),
    'streak', coalesce(v_st -> 'streak', '0'::jsonb), 'result_url', v_url, 'call_id', p_call_id);
  if p_card_delivery = 'attachment' then
    v_ctx := v_ctx || jsonb_build_object('media_url', v_url || '/card.png');
  end if;
  perform ch_outbox_enqueue(null, v_call.user_id, 'post_call', null,
                            case when p_card_delivery = 'attachment' then v_url || '/card.png' end,
                            'post_call:' || p_call_id, null, p_now, v_ctx);

  for d in select * from jsonb_to_recordset(v_deltas) as x(
             user_id uuid, old_rank int, new_rank int, points int, ahead_display_name text, ahead_points int,
             throttled bool) loop
    continue when d.throttled;
    perform ch_outbox_enqueue(null, d.user_id, 'rank_drop', null, null,
                              'rank_drop:' || d.user_id || ':' || p_call_id, null, p_now,
                              jsonb_build_object('old_rank', d.old_rank, 'rank', d.new_rank,
                                                 'next_rank', d.new_rank - 1,
                                                 'points_gap', greatest(coalesce(d.ahead_points, 0) - coalesce(d.points, 0), 0),
                                                 'points', d.points, 'ahead_display_name', d.ahead_display_name));
    v_drops := v_drops + 1;
  end loop;

  update calls set postcall_done_at = p_now where id = p_call_id;
  return jsonb_build_object('ok', true, 'already', false, 'rank_drops', v_drops);
end;
$$;


-- ---------------------------------------------------------------- grants (service_role only)
revoke all on function
  ch_calls_line_stale(text, timestamptz), ch_calls_line_handle(text), ch_calls_cap_exempt(calls),
  ch_calls_settle(text, timestamptz), ch_call_start(text, text, text, text, timestamptz),
  ch_call_end(text, timestamptz, timestamptz, int, timestamptz), ch_commit_reps(text, jsonb, timestamptz),
  ch_tick(timestamptz), ch_postcall(text, timestamptz, text)
  from public, anon, authenticated;
grant execute on function
  ch_calls_line_stale(text, timestamptz), ch_calls_line_handle(text), ch_calls_cap_exempt(calls),
  ch_calls_settle(text, timestamptz), ch_call_start(text, text, text, text, timestamptz),
  ch_call_end(text, timestamptz, timestamptz, int, timestamptz), ch_commit_reps(text, jsonb, timestamptz),
  ch_tick(timestamptz), ch_postcall(text, timestamptz, text)
  to service_role;

commit;
