-- Team members get no daily call cap (owner request 2026-10-13; D-38 in docs/challenge/DECISIONS.md).
--
-- A team member is `clients.is_team` - the "team / test account" flag from 20261025_challenge_metrics.sql, already
-- audited through ch_admin_set_team and already a one-click toggle in the admin console. This migration gives that
-- one flag a second meaning: the account is exempt from daily_call_cap. No new column and no new admin RPC, so
-- there is one source of truth for "this is us, not a competitor".
--
-- The cap was otherwise global config (daily_call_cap) with no per-user override anywhere, so every gate that
-- compared ch_calls_today(user) against the configured cap now compares it against ch_calls_cap_for(user):
--   ch_call_start        the 'at_cap' reject
--   ch_queue_join        the 'at_cap' reason and the line_open (walk-in) hint
--   ch_tick              step 2 expiring waiting entries of users at cap, step 3 pop eligibility
--   ch_calls_settle      refusing a one-time turn restore to a user at cap
--   ch_calls_cap_exempt  the 20261024 rule that a restored-turn call re-counts only if the ET day has room
--   ch_web_me            the walk-in line_open hint
-- (grep daily_call_cap after applying: what is left is reporting and config.)
--
-- ch_calls_today is deliberately NOT changed. The count stays honest, so queue ORDER (calls_today asc, entered_at
-- asc) is untouched: a team member is never refused for being at cap, and never jumps the line either. Their calls
-- still count, still score and still show on the public leaderboard (keeping them off the board is a separate
-- decision, not this migration).
--
-- Reporting also stays on the configured cap, so calls_left / daily_call_cap keep giving every existing reader a
-- small number instead of the sentinel. ch_user_status and ch_queue_join gained `uncapped` so a reader can say
-- "no cap" instead of "0 left"; pushup-web does.
--
-- Already-marked team or test accounts become uncapped the moment this is applied. Idempotent (create or replace;
-- no column adds, no config writes).
begin;

-- ---------------------------------------------------------------- per-user cap
-- Exempt from daily_call_cap: a team / test account (clients.is_team, ch_admin_set_team).
create or replace function ch_calls_uncapped(p_user_id uuid) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce((select c.is_team from clients c where c.id = p_user_id), false)
$$;

-- This user's daily call cap: the configured cap, or effectively none for a team member. A sentinel (not null) keeps
-- every `calls_today >= cap` / `calls_today < cap` comparison two-valued; null would make the `<` gates read false.
create or replace function ch_calls_cap_for(p_user_id uuid) returns int
language sql stable security definer set search_path = public as $$
  select case when ch_calls_uncapped(p_user_id) then 2147483647
              else ch_calls_cfg_int('daily_call_cap', 5) end
$$;

-- ch_calls_cap_exempt(p_call calls) - restore re-count rule reads the caller's own cap
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
           or (p_call.end_reason = 'timeout' and p_call.session_id is null and coalesce(p_call.rep_count, 0) = 0)
           or (p_call.turn_restored_at is not null
               and (select count(*) from calls o
                     where o.user_id = p_call.user_id and o.id <> p_call.id and o.decision = 'accept'
                       and (o.counted_toward_cap or o.ended_at is null)
                       and o.connected_at >= ch_et_day_start(ch_et_day(p_call.connected_at))
                       and o.connected_at <  ch_et_day_start(ch_et_day(p_call.connected_at) + 1))
                   >= ch_calls_cap_for(p_call.user_id))),
         false)
$$;

-- ch_calls_settle - turn restore
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
     or ch_calls_today(v_call.user_id, p_now) >= ch_calls_cap_for(v_call.user_id)
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

-- ch_call_start - at_cap gate
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
    elsif ch_calls_today(v_user, p_now) >= ch_calls_cap_for(v_user) then
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

-- ch_tick - expire ineligible waiting entries (step 2) and pop eligibility (step 3)
create or replace function ch_tick(p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_ls line_state;
  v_q queue;
  v_call calls;
  v_cand record;
  v_r record;
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
            or ch_calls_today(q.user_id, p_now) >= ch_calls_cap_for(q.user_id))
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
       where w.calls_today < ch_calls_cap_for(w.user_id) and c.banned_at is null and c.opted_out_at is null and c.joined_at is not null
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

-- ch_queue_join - at_cap gate and line_open use this user's cap
create or replace function ch_queue_join(p_user_id uuid, p_now timestamptz) returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  v_client clients;
  v_cap int := ch_calls_cfg_int('daily_call_cap', 5);   -- configured cap: reporting only
  v_user_cap int := ch_calls_cap_for(p_user_id);        -- this user's cap: every gate below
  v_ct int := 0;
  v_reason text;
  v_qid bigint;
  v_pos int;
  v_line_open bool;
  v_ws timestamptz := ch_calls_cfg_ts('window_start');
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
  elsif v_ct >= v_user_cap then
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

  -- line_open mirrors ch_call_start's chert_meta walk-in acceptance for this user (incl. D-13: own entry ok)
  v_line_open := v_reason in ('ok', 'opted_out_ok', 'already')
                 and (v_ws is null or p_now >= v_ws) and not ch_calls_frozen(p_now)
                 and v_ct < v_user_cap
                 and exists (select 1 from line_state ls join lines l on l.id = ls.line_id
                              where l.active and ls.state = 'idle')
                 and not exists (select 1 from queue where status in ('waiting', 'notified') and user_id <> p_user_id)
                 and not exists (select 1 from line_state where user_id = p_user_id
                                    and (state = 'in_call' or (state = 'claimed' and claimed_until > p_now)));

  if v_reason in ('ok', 'opted_out_ok', 'already') then
    select w.pos into v_pos from ch_calls_waiting(p_now) w where w.user_id = p_user_id;
    v_pos := coalesce(v_pos, 0);  -- 0 = holds a claim / notified
  end if;
  return jsonb_build_object('ok', v_reason in ('ok', 'opted_out_ok', 'already'), 'reason', v_reason,
                            'position', v_pos, 'calls_today', v_ct, 'calls_left', greatest(v_cap - v_ct, 0),
                            'uncapped', ch_calls_uncapped(p_user_id),
                            'line_open', v_line_open);
end;
$$;

-- ch_web_me - walk-in line_open gate (daily_call_cap in the payload stays the configured cap)
create or replace function ch_web_me(p_user_id uuid, p_now timestamptz) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_status   jsonb;
  v_today    date := ch_et_day(p_now);
  v_pts      int;
  v_handle   text;
  v_pending  jsonb;
  v_claim    record;
  v_in_call  bool;
  v_cap      int := ch_calls_cfg_int('daily_call_cap', 5);
  v_ws       timestamptz := ch_calls_cfg_ts('window_start');
  v_frozen   bool := ch_calls_frozen(p_now);
  v_count_s  int := ch_calls_cfg_int('call_count_s', 180) + ch_calls_cfg_int('call_reveal_s', 15);
  v_gap_s    int := ch_calls_cfg_int('line_offline_gap_s', 180);
  v_cycle    int;
  v_remain   int;
  v_lines    int;
  v_open     bool;
begin
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  v_status := ch_user_status(p_user_id, p_now);
  if v_status->>'user_id' is null then
    return jsonb_build_object('user_id', null);
  end if;

  select coalesce(sum(e.points), 0)::int into v_pts
    from ch_score_events e where e.user_id = p_user_id and ch_et_day(e.at) = v_today;
  select h.handle into v_handle from client_handles h where h.client_id = p_user_id
    order by h.created_at asc, h.handle asc limit 1;
  select jsonb_build_object('handle', w.handle, 'code', w.code, 'expires_at', w.expires_at,
                            'expired', w.expires_at <= p_now)
    into v_pending
    from web_handle_claims w where w.user_id = p_user_id and w.consumed_at is null
   order by w.id desc limit 1;
  select ls.line_id, ls.claimed_until into v_claim
    from line_state ls join lines l on l.id = ls.line_id
   where l.active and ls.state = 'claimed' and ls.user_id = p_user_id and ls.claimed_until > p_now
   order by ls.claimed_until desc limit 1;
  v_in_call := exists (select 1 from line_state where user_id = p_user_id and state = 'in_call');

  v_cycle := (ch_queue_view(p_now)->>'avg_cycle_s')::int;
  select count(*)::int,
         min(case ls.state
               when 'idle' then 0
               when 'offline' then greatest(0, ceil(extract(epoch from ls.offline_until - p_now)))::int
               when 'in_call' then greatest(0, ceil(extract(epoch from ls.in_call_since - p_now)) + v_count_s)::int
                                   + v_gap_s
               when 'claimed' then greatest(0, ceil(extract(epoch from ls.claimed_until - p_now)))::int + v_cycle
             end)
    into v_lines, v_remain
    from line_state ls join lines l on l.id = ls.line_id where l.active;

  v_open := (v_status->>'banned')::bool is not true
            and (v_ws is null or p_now >= v_ws) and not v_frozen
            and (v_status->>'calls_today')::int < ch_calls_cap_for(p_user_id)
            and not v_in_call and v_claim.line_id is null
            and exists (select 1 from line_state ls join lines l on l.id = ls.line_id where l.active and ls.state = 'idle')
            and not exists (select 1 from queue where status in ('waiting', 'notified') and user_id <> p_user_id);

  return v_status || jsonb_build_object(
    'points_today', v_pts,
    'handle', v_handle,
    'pending_claim', v_pending,
    'daily_call_cap', v_cap,
    'claim', case when v_claim.line_id is null then null else jsonb_build_object(
               'line_id', v_claim.line_id, 'claimed_until', v_claim.claimed_until,
               'seconds_left', greatest(0, ceil(extract(epoch from v_claim.claimed_until - p_now)))::int) end,
    'in_call', v_in_call,
    'line_open', v_open,
    'avg_cycle_s', v_cycle,
    'remaining_s', coalesce(v_remain, 0),
    'lines_active', coalesce(v_lines, 0),
    'brodie_number', ch_cfg('brodie_number') #>> '{}',
    'started', v_ws is null or p_now >= v_ws,
    'frozen', v_frozen);
end;
$$;

-- ch_user_status - adds 'uncapped' (ch_web_me merges this payload, so the site gets it too)
create or replace function ch_user_status(p_user_id uuid, p_now timestamptz) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  s        record;
  v_cap    int := coalesce((ch_cfg('daily_call_cap') #>> '{}')::int, 5);
  v_today  int;
  v_total  int;
  v_qstat  text;
begin
  select * into s from ch_user_stats where user_id = p_user_id;
  if not found then
    return jsonb_build_object('user_id', null);
  end if;
  select count(*)::int into v_total from ch_user_stats where listed;
  v_today := ch_calls_today(p_user_id, p_now);
  select status into v_qstat from queue where user_id = p_user_id and status in ('waiting', 'notified')
    order by id desc limit 1;
  return jsonb_build_object(
    'user_id', s.user_id,
    'display_name', s.display_name,
    'points', s.points,
    'valid_reps', s.valid_reps,
    'rank', s.rank,
    'total_users', v_total,
    'calls_today', v_today,
    'calls_left', greatest(v_cap - v_today, 0),
    'streak', ch_streak_days(s.streak_days, ch_et_day(p_now)),
    'queue_position', ch_queue_position(p_user_id, p_now),
    'queue_status', v_qstat,
    'avatar_level', s.avatar_level,
    'opted_out', s.opted_out_at is not null,
    'banned', s.banned_at is not null,
    'uncapped', ch_calls_uncapped(p_user_id),
    'ref_code', (select ref_code from clients where id = p_user_id));
end;
$$;

-- ---------------------------------------------------------------- grants (create or replace keeps the ACL of the
-- replaced functions; these two are new)
revoke all on function ch_calls_uncapped(uuid), ch_calls_cap_for(uuid) from public, anon, authenticated;
grant execute on function ch_calls_uncapped(uuid), ch_calls_cap_for(uuid) to service_role;

commit;
