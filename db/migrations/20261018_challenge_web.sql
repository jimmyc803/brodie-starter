-- Push-Up Challenge, migration: web-only join / status (task 44, MESSAGING_PROVIDER=web_only fallback, SPEC §3 row 2).
-- Contract: docs/challenge/CONTRACTS.md §C2 (clients.auth_user_id, client_handles.linked_via 'web') + §C4 /web/*.
-- Idempotent: create or replace only. Every function: security definer, search_path = public, EXECUTE service_role only.
--
--   ch_user_by_auth(p_auth_user_id uuid) -> {user_id, display_name, opted_out, banned} | {user_id: null}
--       Registered (joined_at set) client linked to a Supabase auth user. The dispatcher derives user_id ONLY from a
--       verified JWT `sub` through this function; no /web endpoint accepts a user_id from the caller.
--   ch_web_join(p_auth_user_id uuid, p_display_name text, p_handle text, p_now timestamptz)
--       -> {ok, reason /* ok|already_registered|bad_name|bad_handle|taken|handle_taken|closed */, user_id}
--       Registers directly (no join_pending/YES step: the web form carries the 18+ / rules confirmation) with
--       auth_user_id and the FaceTime handle linked_via 'web'. A handle already linked to ANY client is never re-linked
--       or merged (reason handle_taken): accounts are not joined across login methods, so a web login can never read or
--       act on an iMessage user's record. Serialized per auth user (advisory lock) and by the handle / display-name
--       unique indexes; a lost race rolls the client insert back inside a subtransaction.
--   ch_web_me(p_user_id uuid, p_now timestamptz) -> ch_user_status fields + points_today, handle, claim, in_call,
--       line_open (walk-in possible now, mirrors ch_queue_join), ETA inputs (avg_cycle_s, remaining_s, lines_active),
--       daily_call_cap, brodie_number, started, frozen. {user_id: null} when not registered. Only this user's data.

begin;

create or replace function ch_user_by_auth(p_auth_user_id uuid) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select jsonb_build_object('user_id', c.id, 'display_name', c.display_name,
                               'opted_out', c.opted_out_at is not null, 'banned', c.banned_at is not null)
       from clients c
      where p_auth_user_id is not null and c.auth_user_id = p_auth_user_id and c.joined_at is not null),
    jsonb_build_object('user_id', null))
$$;

create or replace function ch_web_join(p_auth_user_id uuid, p_display_name text, p_handle text, p_now timestamptz)
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_name   text := btrim(coalesce(p_display_name, ''));
  v_uid    uuid;
  v_joined timestamptz;
  v_owner  uuid;
  v_coach  uuid;
  v_con    text;
begin
  if p_auth_user_id is null then
    raise exception 'auth_user_id required' using errcode = '22023';
  end if;
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('web_join:' || p_auth_user_id::text, 0));

  select id, joined_at into v_uid, v_joined from clients where auth_user_id = p_auth_user_id for update;
  if v_uid is not null and v_joined is not null then
    return jsonb_build_object('ok', true, 'reason', 'already_registered', 'user_id', v_uid);
  end if;
  if ch_registration_closed(p_now) then
    return jsonb_build_object('ok', false, 'reason', 'closed', 'user_id', null);
  end if;
  if v_name !~ '^[A-Za-z0-9_]{3,20}$' then
    return jsonb_build_object('ok', false, 'reason', 'bad_name', 'user_id', null);
  end if;
  if v_handle is null or not (v_handle ~ '^\+[1-9][0-9]{1,14}$'
                              or v_handle ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$') then
    return jsonb_build_object('ok', false, 'reason', 'bad_handle', 'user_id', null);
  end if;
  select client_id into v_owner from client_handles where handle = v_handle for update;
  if v_owner is not null and v_owner is distinct from v_uid then
    return jsonb_build_object('ok', false, 'reason', 'handle_taken', 'user_id', null);
  end if;
  if exists (select 1 from clients where lower(display_name) = lower(v_name) and id is distinct from v_uid) then
    return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null);
  end if;

  v_coach := (ch_cfg('challenge_coach_id') #>> '{}')::uuid;
  if v_coach is null then
    raise exception 'challenge_coach_id not configured' using errcode = '55000';
  end if;

  begin
    if v_uid is null then
      insert into clients (coach_id, name, display_name, joined_at, age_confirmed_at, rules_accepted_at, auth_user_id)
        values (v_coach, v_name, v_name, p_now, p_now, p_now, p_auth_user_id)
        returning id into v_uid;
    else
      update clients set display_name = v_name, joined_at = p_now, age_confirmed_at = p_now, rules_accepted_at = p_now
        where id = v_uid;
    end if;
    insert into client_handles (handle, client_id, kind, linked_via, created_at)
      values (v_handle, v_uid, case when position('@' in v_handle) > 0 then 'email' else 'phone' end, 'web', p_now)
      on conflict (handle) do nothing;  -- concurrent link by another client is caught by the ownership check below
    if not exists (select 1 from client_handles where handle = v_handle and client_id = v_uid) then
      raise exception 'handle_taken' using errcode = 'P0001';
    end if;
  exception
    when unique_violation then
      get stacked diagnostics v_con = constraint_name;
      if v_con = 'clients_display_name_lower_uq' then
        return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null);
      elsif v_con = 'client_handles_pkey' then
        return jsonb_build_object('ok', false, 'reason', 'handle_taken', 'user_id', null);
      end if;
      raise;
    when raise_exception then
      if sqlerrm = 'handle_taken' then
        return jsonb_build_object('ok', false, 'reason', 'handle_taken', 'user_id', null);
      end if;
      raise;
  end;

  insert into audit_log (actor, action, target, before, after, reason, at)
    values ('system', 'user_join', v_uid::text, null,
            jsonb_build_object('display_name', v_name, 'handle', v_handle, 'joined_at', p_now, 'via', 'web'),
            null, p_now);
  return jsonb_build_object('ok', true, 'reason', 'ok', 'user_id', v_uid);
end;
$$;

create or replace function ch_web_me(p_user_id uuid, p_now timestamptz) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_status   jsonb;
  v_today    date := ch_et_day(p_now);
  v_pts      int;
  v_handle   text;
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
            and (v_status->>'calls_today')::int < v_cap
            and not v_in_call and v_claim.line_id is null
            and exists (select 1 from line_state ls join lines l on l.id = ls.line_id where l.active and ls.state = 'idle')
            and not exists (select 1 from queue where status in ('waiting', 'notified') and user_id <> p_user_id);

  return v_status || jsonb_build_object(
    'points_today', v_pts,
    'handle', v_handle,
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

revoke all on function ch_user_by_auth(uuid), ch_web_join(uuid, text, text, timestamptz), ch_web_me(uuid, timestamptz)
  from public, anon, authenticated;
grant execute on function ch_user_by_auth(uuid), ch_web_join(uuid, text, text, timestamptz), ch_web_me(uuid, timestamptz)
  to service_role;

commit;
