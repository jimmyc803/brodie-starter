-- Task 24: fixes for bugs found by scripts/simulate.py (tests: tests/challenge/test_scheduler_properties.py,
-- tests/challenge/test_db_sim_fixes.py). CONTRACTS C7.s. Idempotent (create or replace / if not exists).
--
-- 1. ch_tick (from 20261013_challenge_calls.sql):
--    a. window_end closes the queue: once p_now >= window_end every waiting entry is expired (reason 'frozen');
--       before, they stayed 'waiting' forever. A manual competition_frozen (admin pause) only stops popping and
--       keeps waiting entries.
--    b. a claim that expires while frozen sends no "text QUEUE" missed_slot (QUEUE is refused while frozen): at/after
--       window_end the notified entry becomes 'expired' (reason 'frozen'); during an admin pause it goes back to
--       'waiting' with its original entered_at, so the user keeps their place when the pause ends.
--    c. the youre_up ctx names the line: line_handle = lines.facetime_handle, else brodie_number when exactly one
--       line is active, else the line's chert_agent_name (2-line setups must set lines.facetime_handle).
--
-- 2. ch_outbox_claim (from 20261013_challenge_misc.sql): 'you're up' must not wait FIFO behind bulk proactive texts
--    (at 20/min a ~60-row burst delayed it past the 90 s claim window), yet must not starve other texts either.
--    a. due youre_up rows whose claim is no longer active (queue row not 'notified' or claim_expires_at <= p_now)
--       are marked 'suppressed' (last_error 'claim_inactive') instead of being sent late;
--    b. claim order is earliest-deadline-first: a youre_up's deadline is its claimed_until, every other row's is
--       due time + 300 s. A youre_up therefore overtakes rows younger than ~210 s, but a row that has waited
--       ~210 s goes before any newly created youre_up, and live youre_up rows are bounded by active claims (<= one
--       per line), so ordinary texts cannot be starved by LEAVE/QUEUE cycling.
--
-- 3. ch_set_opt and ch_admin_queue_remove (from 20261013_challenge_misc.sql) free a claimed line through
--    ch_calls_line_set, which writes the usual 'line:claimed->idle' audit row (they updated line_state directly).
--
-- 4. ch_admin_set_ban(.., p_now) / ch_admin_ban(.., p_now) / ch_admin_unban(.., p_now): new overloads taking the
--    injected clock for banned_at and the audit row. The 3/4-arg forms keep their signatures and use now().
begin;

alter table lines add column if not exists facetime_handle text;

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
begin
  if p_now is null then
    raise exception 'ch_tick: p_now required';
  end if;
  perform ch_calls_lock_lines();
  v_frozen := ch_calls_frozen(p_now);                -- window_end reached OR admin competition_frozen
  v_closed := v_we is not null and p_now >= v_we;    -- window_end reached: the queue is closed for good

  -- 1. per-line timers
  for v_ls in select ls.* from line_state ls join lines l on l.id = ls.line_id where l.active order by ls.line_id loop
    if v_ls.state = 'claimed' and (v_ls.claimed_until is null or v_ls.claimed_until <= p_now) then
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
          perform ch_calls_notify(v_q.user_id, 'missed_slot',
                                  jsonb_build_object('queue_id', v_q.id, 'line_id', v_ls.line_id),
                                  'missed_slot:' || v_q.id, p_now);
        end if;
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
      perform ch_calls_lock_user(v_cand.user_id);
      perform 1 from queue where id = v_cand.queue_id and status = 'waiting' for update;
      if not found then
        raise exception 'ch_tick: queue entry % changed under line lock', v_cand.queue_id;
      end if;
      v_until := p_now + make_interval(secs => v_claim_s);
      perform ch_calls_queue_set(v_cand.queue_id, 'notified', p_now, 'pop', v_ls.line_id, v_until);
      perform ch_calls_line_set(v_ls.line_id, 'claimed', v_cand.user_id, null, v_until, null, null, p_now,
                                'pop queue ' || v_cand.queue_id);
      select coalesce(nullif(btrim(l.facetime_handle), ''),
                      case when (select count(*) from lines x where x.active) = 1
                           then nullif(btrim(ch_cfg('brodie_number') #>> '{}'), '') end,
                      l.chert_agent_name)
        into v_line_handle from lines l where l.id = v_ls.line_id;
      perform ch_calls_notify(v_cand.user_id, 'youre_up',
                              jsonb_build_object('queue_id', v_cand.queue_id, 'line_id', v_ls.line_id,
                                                 'line_handle', v_line_handle,
                                                 'claimed_until', v_until, 'claim_window_s', v_claim_s),
                              'youre_up:' || v_cand.queue_id, p_now);
      v_claims := v_claims || jsonb_build_object('line_id', v_ls.line_id, 'user_id', v_cand.user_id,
                                                 'queue_id', v_cand.queue_id, 'claimed_until', v_until);
    end loop;
  end if;

  return jsonb_build_object('no_shows', v_no_shows, 'claims', v_claims, 'timeouts', v_timeouts, 'idled', v_idled);
end;
$$;


create or replace function ch_outbox_claim(p_limit int, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_max int := coalesce((ch_cfg('outbox_max_attempts') #>> '{}')::int, 5);
  v_claim_s int := ch_calls_cfg_int('claim_window_s', 90);
  v_fifo_deadline constant interval := interval '300 seconds';  -- non-youre_up rows: deadline = due + 300 s
  v_ts_re constant text := '^\d{4}-\d\d-\d\d[T ]\d\d:\d\d:\d\d(\.\d+)?([+-]\d\d(:?\d\d)?|Z)$';
  v_out jsonb;
begin
  -- Expired leases that already used every attempt: give up (at-most-once after lease, C7).
  update messages m set status = 'failed', lease_until = null, last_error = coalesce(m.last_error, 'lease_expired')
  where m.id in (select id from messages
                 where direction = 'out' and status = 'sending' and lease_until <= p_now and attempts >= v_max
                 for update skip locked);
  -- A due 'you're up' whose claim is gone (user left / STOP / ban / claim expired / already connected) is obsolete:
  -- suppress it rather than tell the user to FaceTime for a turn they no longer hold.
  update messages m set status = 'suppressed', lease_until = null, last_error = coalesce(m.last_error, 'claim_inactive')
  where m.id in (
    select x.id from messages x
    where x.direction = 'out' and x.template = 'youre_up' and x.ctx ->> 'queue_id' ~ '^[0-9]{1,18}$'
      and ((x.status = 'queued' and coalesce(x.not_before, x.created_at) <= p_now)
           or (x.status = 'sending' and x.lease_until <= p_now and x.attempts < v_max))
      and not exists (select 1 from queue q
                       where q.id = case when x.ctx ->> 'queue_id' ~ '^[0-9]{1,18}$'
                                         then (x.ctx ->> 'queue_id')::bigint end
                         and q.status = 'notified' and q.claim_expires_at > p_now)
    for update of x skip locked);
  with picked as (
    select id from messages
    where direction = 'out'
      and ((status = 'queued' and coalesce(not_before, created_at) <= p_now)
           or (status = 'sending' and lease_until <= p_now and attempts < v_max))
    -- earliest deadline first (see header): youre_up by its claim deadline, everything else due + 300 s
    order by case when template is not distinct from 'youre_up' and ctx ->> 'claimed_until' ~ v_ts_re
                    then (ctx ->> 'claimed_until')::timestamptz
                  when template is not distinct from 'youre_up'
                    then coalesce(not_before, created_at) + make_interval(secs => v_claim_s)
                  else coalesce(not_before, created_at) + v_fifo_deadline end,
             coalesce(not_before, created_at), id
    limit greatest(coalesce(p_limit, 0), 0)
    for update skip locked
  ), upd as (
    update messages m set status = 'sending', attempts = coalesce(m.attempts, 0) + 1,
                          lease_until = p_now + interval '60 seconds'
    from picked where m.id = picked.id
    returning m.*
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', id, 'handle', handle, 'user_id', user_id, 'body', body, 'media_url', media_url,
           'template', template, 'ctx', ctx, 'dedupe_key', dedupe_key, 'attempts', attempts,
           'not_before', not_before, 'created_at', created_at, 'lease_until', lease_until) order by id), '[]'::jsonb)
    into v_out
  from upd;
  return v_out;
end;
$$;

-- Opt-out also removes the user from the queue at once (C7 lock order: line_state rows by line_id -> per-user advisory
-- lock -> queue rows): waiting -> 'left', notified -> 'expired', and any line they hold 'claimed' -> idle through
-- ch_calls_line_set (version bump + 'line:claimed->idle' audit row). Audited.
create or replace function ch_set_opt(p_user_id uuid, p_opted_out bool, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_before timestamptz;
  v_after  timestamptz;
  v_q      record;
  v_line   record;
  v_freed  text[] := '{}';
  v_left   bigint[] := '{}';
begin
  if p_opted_out is null then
    raise exception 'p_opted_out required' using errcode = '22023';
  end if;
  if p_opted_out then
    perform 1 from line_state order by line_id for update;
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  end if;
  select opted_out_at into v_before from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_registered');
  end if;
  v_after := case when p_opted_out then coalesce(v_before, p_now) else null end;
  if v_after is distinct from v_before then
    update clients set opted_out_at = v_after where id = p_user_id;
    insert into audit_log (actor, action, target, before, after, reason, at)
      values ('system', case when p_opted_out then 'opt_out' else 'opt_in' end, p_user_id::text,
              jsonb_build_object('opted_out_at', v_before), jsonb_build_object('opted_out_at', v_after), null, p_now);
  end if;
  if p_opted_out then
    for v_line in select line_id from line_state where state = 'claimed' and user_id = p_user_id order by line_id loop
      perform ch_calls_line_set(v_line.line_id, 'idle', null, null, null, null, null, p_now, 'opt_out');
      v_freed := v_freed || v_line.line_id;
    end loop;
    for v_q in select id, status, line_id from queue where user_id = p_user_id and status in ('waiting', 'notified')
               order by id for update loop
      update queue set status = case when v_q.status = 'waiting' then 'left' else 'expired' end where id = v_q.id;
      v_left := v_left || v_q.id;
      insert into audit_log (actor, action, target, before, after, reason, at)
        values ('system', 'opt_out_queue_remove', v_q.id::text,
                jsonb_build_object('status', v_q.status, 'user_id', p_user_id, 'line_id', v_q.line_id),
                jsonb_build_object('status', case when v_q.status = 'waiting' then 'left' else 'expired' end,
                                   'lines_idled', to_jsonb(v_freed)), 'opt_out', p_now);
    end loop;
  end if;
  return jsonb_build_object('ok', true, 'opted_out', v_after is not null);
end;
$$;

-- Lock order (C7): line_state rows by line_id -> per-user advisory lock -> queue rows. A freed claim goes through
-- ch_calls_line_set (version bump + 'line:claimed->idle' audit row, actor 'system'; the admin row below names the actor).
create or replace function ch_admin_queue_remove(p_queue_id bigint, p_reason text, p_actor text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_user   uuid;
  v_q      queue%rowtype;
  v_line   line_state%rowtype;
  v_freed  text[] := '{}';
begin
  perform ch_require_reason(p_reason, p_actor);
  select user_id into v_user from queue where id = p_queue_id;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  -- Lock every line row (few lines): a claim for this user can appear on any line until we hold the user lock, and
  -- taking a line lock after the user lock would invert the C7 order.
  perform 1 from line_state order by line_id for update;
  perform pg_advisory_xact_lock(hashtextextended(v_user::text, 0));
  select * into v_q from queue where id = p_queue_id for update;
  if v_q.status not in ('waiting', 'notified') then
    return jsonb_build_object('ok', false, 'reason', 'not_active', 'status', v_q.status);
  end if;
  update queue set status = 'left' where id = p_queue_id;
  if v_q.status = 'notified' then
    for v_line in select * from line_state where state = 'claimed' and user_id = v_user order by line_id loop
      perform ch_calls_line_set(v_line.line_id, 'idle', null, null, null, null, null, now(),
                                'admin queue_remove ' || p_queue_id);
      v_freed := v_freed || v_line.line_id;
    end loop;
  end if;
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, 'queue_remove', p_queue_id::text,
            jsonb_build_object('status', v_q.status, 'user_id', v_user, 'line_id', v_q.line_id),
            jsonb_build_object('status', 'left', 'user_id', v_user, 'lines_idled', to_jsonb(v_freed)), p_reason);
  return jsonb_build_object('ok', true, 'lines_idled', to_jsonb(v_freed));
end;
$$;

-- Ban / unban with an injected clock (banned_at and the audit row use p_now). The 4-arg ch_admin_set_ban and the
-- 3-arg ch_admin_ban / ch_admin_unban (admin site) keep their signatures and pass now().
create or replace function ch_admin_set_ban(p_user_id uuid, p_ban bool, p_reason text, p_actor text,
                                            p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_old clients%rowtype;
begin
  if p_now is null then
    raise exception 'ch_admin_set_ban: p_now required' using errcode = '22023';
  end if;
  perform ch_require_reason(p_reason, p_actor);
  select * into v_old from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  if p_ban then
    update clients set banned_at = coalesce(banned_at, p_now), ban_reason = p_reason where id = p_user_id;
  else
    update clients set banned_at = null, ban_reason = null where id = p_user_id;
  end if;
  insert into audit_log (actor, action, target, before, after, reason, at)
    select p_actor, case when p_ban then 'ban' else 'unban' end, p_user_id::text,
           jsonb_build_object('banned_at', v_old.banned_at, 'ban_reason', v_old.ban_reason),
           jsonb_build_object('banned_at', c.banned_at, 'ban_reason', c.ban_reason), p_reason, p_now
    from clients c where c.id = p_user_id;
  return jsonb_build_object('ok', true, 'changed', (v_old.banned_at is not null) is distinct from p_ban);
end;
$$;

create or replace function ch_admin_set_ban(p_user_id uuid, p_ban bool, p_reason text, p_actor text) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_ban(p_user_id, p_ban, p_reason, p_actor, now())
$$;

create or replace function ch_admin_ban(p_user_id uuid, p_reason text, p_actor text, p_now timestamptz) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_ban(p_user_id, true, p_reason, p_actor, p_now)
$$;

create or replace function ch_admin_unban(p_user_id uuid, p_reason text, p_actor text, p_now timestamptz) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_ban(p_user_id, false, p_reason, p_actor, p_now)
$$;

revoke all on function ch_outbox_claim(int, timestamptz), ch_tick(timestamptz), ch_set_opt(uuid, bool, timestamptz),
  ch_admin_queue_remove(bigint, text, text), ch_admin_set_ban(uuid, bool, text, text, timestamptz),
  ch_admin_set_ban(uuid, bool, text, text), ch_admin_ban(uuid, text, text, timestamptz),
  ch_admin_unban(uuid, text, text, timestamptz) from public, anon, authenticated;
grant execute on function ch_outbox_claim(int, timestamptz), ch_tick(timestamptz), ch_set_opt(uuid, bool, timestamptz),
  ch_admin_queue_remove(bigint, text, text), ch_admin_set_ban(uuid, bool, text, text, timestamptz),
  ch_admin_set_ban(uuid, bool, text, text), ch_admin_ban(uuid, text, text, timestamptz),
  ch_admin_unban(uuid, text, text, timestamptz) to service_role;

commit;
