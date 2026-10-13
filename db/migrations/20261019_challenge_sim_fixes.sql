-- Task 24: fixes for bugs found by scripts/simulate.py (tests: tests/challenge/test_scheduler_properties.py).
--
-- 1. ch_tick: the freeze closes the queue. Waiting entries are expired once ch_calls_frozen(p_now) (window_end
--    reached or competition_frozen); before, they stayed 'waiting' forever. Otherwise identical to
--    20261013_challenge_calls.sql ch_tick (audit reason 'frozen' instead of 'ineligible' for those rows).
--
-- 2. ch_outbox_claim: 'you're up' must not wait FIFO behind bulk proactive texts.
-- At outbound_rate_per_min = 20 a power-hour start / ending-soon / recap burst to every user (~60 rows) delays a
-- 'youre_up' queued just after it by ~3 min, longer than the 90 s claim window, so the user loses the slot.
-- Identical to 20261013_challenge_misc.sql ch_outbox_claim except the claim order: time-critical 'youre_up' rows
-- that are due go first, then the previous (not_before, id) FIFO. Idempotent (create or replace).
begin;

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

  -- 2. expire waiting entries of users now at cap / banned / opted out, and every waiting entry once frozen
  --    (SPEC §7: freeze at window_end stops popping AND closes the queue)
  v_frozen := ch_calls_frozen(p_now);
  for v_r in
    select q.id, q.user_id from queue q join clients c on c.id = q.user_id
     where q.status = 'waiting'
       and (v_frozen or c.banned_at is not null or c.opted_out_at is not null
            or ch_calls_today(q.user_id, p_now) >= v_cap)
     order by q.user_id, q.id
  loop
    perform ch_calls_lock_user(v_r.user_id);
    perform 1 from queue where id = v_r.id and status = 'waiting' for update;
    if found then
      perform ch_calls_queue_set(v_r.id, 'expired', p_now, case when v_frozen then 'frozen' else 'ineligible' end);
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


create or replace function ch_outbox_claim(p_limit int, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_max int := coalesce((ch_cfg('outbox_max_attempts') #>> '{}')::int, 5);
  v_out jsonb;
begin
  -- Expired leases that already used every attempt: give up (at-most-once after lease, C7).
  update messages m set status = 'failed', lease_until = null, last_error = coalesce(m.last_error, 'lease_expired')
  where m.id in (select id from messages
                 where direction = 'out' and status = 'sending' and lease_until <= p_now and attempts >= v_max
                 for update skip locked);
  with picked as (
    select id from messages
    where direction = 'out'
      and ((status = 'queued' and coalesce(not_before, created_at) <= p_now)
           or (status = 'sending' and lease_until <= p_now and attempts < v_max))
    order by (template is not distinct from 'youre_up') desc, coalesce(not_before, created_at), id
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

revoke all on function ch_outbox_claim(int, timestamptz), ch_tick(timestamptz) from public, anon, authenticated;
grant execute on function ch_outbox_claim(int, timestamptz), ch_tick(timestamptz) to service_role;

commit;
