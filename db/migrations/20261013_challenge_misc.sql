-- Push-Up Challenge, migration 3: registration, user status, leaderboard, rank deltas, config, admin, outbox/inbound,
-- heartbeat RPCs. Contract: docs/challenge/CONTRACTS.md §C2 RPC list (+ §C7 v1.1). Depends on migration 1 helpers/views
-- (ch_cfg, ch_calls_today, ch_user_points, ch_et_day, ch_streak_days, ch_user_stats) -- points/rank/streak/level are
-- read from ch_user_stats only (single source of truth). Independent of 20261013_challenge_calls.sql (task 03).
-- Idempotent: create or replace only. Every function: security definer, search_path = public, EXECUTE service_role only.
--
-- Helpers defined here:
--   ch_norm_handle(text) -> text                 btrim; emails (contain '@') lowercased. Used for every handle lookup/insert.
--   ch_queue_position(uuid, timestamptz) -> int  1-based position among 'waiting' entries ordered by
--                                                (ch_calls_today asc, entered_at asc, id asc); null when not waiting.
--   ch_require_reason(text, text)                raises 22023 'reason_required' / 'actor_required' on blank input.
-- Decisions (beyond C2 wording):
--   * Registration is "closed" when registration_open <> true, competition_frozen = true, or p_now >= window_end.
--   * ch_user_by_handle / ch_user_status only treat clients with joined_at set as registered users.
--   * ch_join_confirm on a handle already linked to a non-joined client upgrades that client (no duplicate client).
--   * ch_rank_deltas returns every drop >= rank_drop_min with `last_drop_text_at` (value BEFORE this call) and
--     `throttled` (last text < rank_drop_throttle_h ago); for non-throttled drops it stamps last_drop_text_at = p_now in
--     the same statement, so the caller texts exactly the rows with throttled = false. Unlisted (banned) users get
--     rank_state.rank = null, so their next listed observation is a "first observation" (no drop).
--   * ch_outbox_enqueue takes an extra optional p_ctx jsonb (C7 template context; body may be null). If p_handle is null
--     the user's earliest linked handle is used.
--   * ch_outbox_claim: claims status 'queued' with coalesce(not_before, created_at) <= p_now, and reclaims 'sending'
--     rows whose lease_until <= p_now; reclaim candidates that already used outbox_max_attempts (config, default 5)
--     attempts become 'failed' (last_error 'lease_expired') instead (C7 at-most-once). Claimed rows get
--     status 'sending', attempts + 1, lease_until = p_now + 60 s.
--   * ch_outbox_mark statuses: sent | failed | suppressed | queued (retry: not_before = coalesce(p_retry_at, now());
--     becomes 'failed' once attempts >= outbox_max_attempts). Marks on a row already 'sent' are no-ops; 'sent' also
--     overrides a 'failed'/'suppressed' row (the provider is the source of truth).
--   * Admin RPCs and ch_config_set have no p_now in C2; they use now(). Unknown targets return {ok:false, reason}.

begin;

-- ---------------------------------------------------------------- helpers
create or replace function ch_norm_handle(p_handle text) returns text
language sql immutable security definer set search_path = public as $$
  select case when p_handle is null then null
              when position('@' in p_handle) > 0 then lower(btrim(p_handle))
              else btrim(p_handle) end
$$;

create or replace function ch_require_reason(p_reason text, p_actor text) returns void
language plpgsql immutable security definer set search_path = public as $$
begin
  if p_reason is null or btrim(p_reason) = '' then
    raise exception 'reason_required' using errcode = '22023';
  end if;
  if p_actor is null or btrim(p_actor) = '' then
    raise exception 'actor_required' using errcode = '22023';
  end if;
end;
$$;

create or replace function ch_queue_position(p_user_id uuid, p_now timestamptz) returns int
language sql stable security definer set search_path = public as $$
  select x.pos::int from (
    select q.user_id,
           row_number() over (order by ch_calls_today(q.user_id, p_now) asc, q.entered_at asc, q.id asc) as pos
    from queue q where q.status = 'waiting'
  ) x where x.user_id = p_user_id
$$;

create or replace function ch_registration_closed(p_now timestamptz) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce(ch_cfg('registration_open'), 'true'::jsonb) <> 'true'::jsonb
      or coalesce(ch_cfg('competition_frozen'), 'false'::jsonb) = 'true'::jsonb
      or coalesce(p_now >= (ch_cfg('window_end') #>> '{}')::timestamptz, false)
$$;

-- ---------------------------------------------------------------- registration
create or replace function ch_join_start(p_handle text, p_display_name text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_name   text := btrim(coalesce(p_display_name, ''));
  v_self   uuid;
begin
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  select c.id into v_self from client_handles h join clients c on c.id = h.client_id where h.handle = v_handle;
  if v_self is not null and exists (select 1 from clients where id = v_self and joined_at is not null) then
    return jsonb_build_object('ok', false, 'reason', 'already_registered');
  end if;
  if ch_registration_closed(p_now) then
    return jsonb_build_object('ok', false, 'reason', 'closed');
  end if;
  if v_name !~ '^[A-Za-z0-9_]{3,20}$' then
    return jsonb_build_object('ok', false, 'reason', 'bad_name');
  end if;
  if exists (select 1 from clients where lower(display_name) = lower(v_name)
             and id is distinct from v_self) then
    return jsonb_build_object('ok', false, 'reason', 'taken');
  end if;
  insert into join_pending (handle, display_name, created_at) values (v_handle, v_name, p_now)
    on conflict (handle) do update set display_name = excluded.display_name, created_at = excluded.created_at;
  return jsonb_build_object('ok', true, 'reason', 'ok', 'display_name', v_name);
end;
$$;

create or replace function ch_join_confirm(p_handle text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle  text := ch_norm_handle(p_handle);
  v_pending join_pending%rowtype;
  v_coach   uuid;
  v_uid     uuid;
  v_joined  timestamptz;
  v_linked  uuid;
  v_con     text;
begin
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  -- Serializes concurrent confirms of the same handle: the loser finds no pending row afterwards.
  select * into v_pending from join_pending where handle = v_handle for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'no_pending', 'user_id', null);
  end if;

  select c.id, c.joined_at into v_uid, v_joined
    from client_handles h join clients c on c.id = h.client_id where h.handle = v_handle for update of c;
  if v_uid is not null and v_joined is not null then
    -- Already registered (race with another path): idempotent success, pending consumed.
    delete from join_pending where handle = v_handle;
    return jsonb_build_object('ok', true, 'reason', 'ok', 'user_id', v_uid);
  end if;

  if ch_registration_closed(p_now) then
    return jsonb_build_object('ok', false, 'reason', 'closed', 'user_id', null);
  end if;
  if exists (select 1 from clients where lower(display_name) = lower(v_pending.display_name)
             and id is distinct from v_uid) then
    delete from join_pending where handle = v_handle;
    return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null);
  end if;

  v_coach := (ch_cfg('challenge_coach_id') #>> '{}')::uuid;
  if v_coach is null then
    raise exception 'challenge_coach_id not configured' using errcode = '55000';
  end if;

  begin
    if v_uid is null then
      insert into clients (coach_id, name, display_name, joined_at, age_confirmed_at, rules_accepted_at)
        values (v_coach, v_pending.display_name, v_pending.display_name, p_now, p_now, p_now)
        returning id into v_uid;
    else
      update clients set display_name = v_pending.display_name, joined_at = p_now,
                         age_confirmed_at = p_now, rules_accepted_at = p_now
        where id = v_uid;
    end if;
  exception when unique_violation then
    get stacked diagnostics v_con = constraint_name;
    if v_con is distinct from 'clients_display_name_lower_uq' then
      raise;
    end if;
    delete from join_pending where handle = v_handle;
    return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null);
  end;

  insert into client_handles (handle, client_id, kind, linked_via, created_at)
    values (v_handle, v_uid, case when position('@' in v_handle) > 0 then 'email' else 'phone' end, 'join', p_now)
    on conflict (handle) do nothing;
  select client_id into v_linked from client_handles where handle = v_handle;
  if v_linked is distinct from v_uid then
    raise exception 'handle % is linked to another client', v_handle using errcode = '23505';
  end if;

  delete from join_pending where handle = v_handle;
  insert into audit_log (actor, action, target, before, after, reason, at)
    values ('system', 'user_join', v_uid::text, null,
            jsonb_build_object('display_name', v_pending.display_name, 'handle', v_handle, 'joined_at', p_now),
            null, p_now);
  return jsonb_build_object('ok', true, 'reason', 'ok', 'user_id', v_uid);
end;
$$;

create or replace function ch_user_by_handle(p_handle text) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select jsonb_build_object('user_id', c.id, 'display_name', c.display_name,
                               'opted_out', c.opted_out_at is not null, 'banned', c.banned_at is not null)
       from client_handles h join clients c on c.id = h.client_id
      where h.handle = ch_norm_handle(p_handle) and c.joined_at is not null),
    jsonb_build_object('user_id', null))
$$;

-- Opt-out also removes the user from the queue at once (C7 lock order: line_state rows by line_id -> per-user advisory
-- lock -> queue rows): waiting -> 'left', notified -> 'expired', and any line they hold 'claimed' -> idle. Audited.
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
      update line_state set state = 'idle', user_id = null, call_id = null, claimed_until = null,
                            updated_at = p_now, version = version + 1
        where line_id = v_line.line_id;
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

-- ---------------------------------------------------------------- status / leaderboard
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
    'banned', s.banned_at is not null);
end;
$$;

create or replace function ch_leaderboard(p_limit int, p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object(
           'rank', t.rank, 'user_id', t.user_id, 'display_name', t.display_name, 'points', t.points,
           'valid_reps', t.valid_reps, 'streak', ch_streak_days(t.streak_days, ch_et_day(p_now)),
           'avatar_level', t.avatar_level, 'reached_at', t.reached_at) order by t.rank), '[]'::jsonb)
  from (select * from ch_user_stats where listed order by rank
        limit case when p_limit is null then null else greatest(p_limit, 0) end) t
$$;

create or replace function ch_rank_deltas(p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_min      int := coalesce((ch_cfg('rank_drop_min') #>> '{}')::int, 2);
  v_throttle interval := make_interval(secs => coalesce((ch_cfg('rank_drop_throttle_h') #>> '{}')::numeric, 3)::double precision * 3600);
  v_out      jsonb;
begin
  -- Self-conflicting lock: concurrent callers serialize, so every drop is reported exactly once.
  lock table rank_state in share row exclusive mode;
  -- One statement = one snapshot: deltas are computed from the pre-update rank_state and current standings.
  with cur as materialized (
    select user_id, rank, points, display_name from ch_user_stats where listed
  ), d as (
    select c.user_id, p.rank as old_rank, c.rank as new_rank, c.points, p.last_drop_text_at,
           a.display_name as ahead_display_name, a.points as ahead_points,
           (p.last_drop_text_at is not null and p.last_drop_text_at > p_now - v_throttle) as throttled
    from cur c
    join rank_state p on p.user_id = c.user_id and p.rank is not null
    left join cur a on a.rank = c.rank - 1
    where c.rank - p.rank >= v_min
  ), up as (
    insert into rank_state (user_id, rank, points, updated_at, last_drop_text_at)
    select c.user_id, c.rank, c.points, p_now, case when d.throttled = false then p_now end
    from cur c left join d on d.user_id = c.user_id
    on conflict (user_id) do update
      set rank = excluded.rank, points = excluded.points, updated_at = excluded.updated_at,
          last_drop_text_at = coalesce(excluded.last_drop_text_at, rank_state.last_drop_text_at)
    returning 1
  ), clr as (
    update rank_state set rank = null, points = null, updated_at = p_now
    where rank is not null and user_id not in (select user_id from cur)
    returning 1
  )
  select coalesce(jsonb_agg(jsonb_build_object(
           'user_id', d.user_id, 'old_rank', d.old_rank, 'new_rank', d.new_rank, 'points', d.points,
           'ahead_display_name', d.ahead_display_name, 'ahead_points', d.ahead_points,
           'last_drop_text_at', d.last_drop_text_at, 'throttled', d.throttled) order by d.new_rank), '[]'::jsonb)
    into v_out
  from d;
  return v_out;
end;
$$;

-- ---------------------------------------------------------------- config
create or replace function ch_config_get() returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_object_agg(key, value order by key), '{}'::jsonb) from competition_config
$$;

create or replace function ch_config_set(p_key text, p_value jsonb, p_actor text, p_reason text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_before jsonb;
begin
  perform ch_require_reason(p_reason, p_actor);
  if p_value is null then
    raise exception 'value_required' using errcode = '22023';
  end if;
  select value into v_before from competition_config where key = p_key for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'unknown_key');
  end if;
  if jsonb_typeof(v_before) <> 'null' and jsonb_typeof(p_value) <> 'null'
     and jsonb_typeof(v_before) <> jsonb_typeof(p_value) then
    return jsonb_build_object('ok', false, 'reason', 'type_mismatch');
  end if;
  update competition_config set value = p_value, updated_by = p_actor, updated_at = now() where key = p_key;
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, 'config_set', p_key, jsonb_build_object('value', v_before), jsonb_build_object('value', p_value),
            p_reason);
  return jsonb_build_object('ok', true);
end;
$$;

-- ---------------------------------------------------------------- admin
create or replace function ch_admin_set_void(p_call_id text, p_void bool, p_reason text, p_actor text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_old calls%rowtype;
begin
  perform ch_require_reason(p_reason, p_actor);
  select * into v_old from calls where id = p_call_id for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  update calls set void = p_void, void_reason = case when p_void then p_reason end where id = p_call_id;
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, case when p_void then 'void_call' else 'unvoid_call' end, p_call_id,
            jsonb_build_object('void', v_old.void, 'void_reason', v_old.void_reason, 'user_id', v_old.user_id),
            jsonb_build_object('void', p_void, 'void_reason', case when p_void then p_reason end, 'user_id', v_old.user_id),
            p_reason);
  return jsonb_build_object('ok', true, 'changed', v_old.void is distinct from p_void);
end;
$$;

create or replace function ch_admin_void_call(p_call_id text, p_reason text, p_actor text) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_void(p_call_id, true, p_reason, p_actor)
$$;

create or replace function ch_admin_unvoid_call(p_call_id text, p_reason text, p_actor text) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_void(p_call_id, false, p_reason, p_actor)
$$;

create or replace function ch_admin_adjust(p_user_id uuid, p_points int, p_reason text, p_actor text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_before int;
  v_after  int;
  v_id     bigint;
begin
  perform ch_require_reason(p_reason, p_actor);
  if p_points is null or p_points = 0 then
    raise exception 'points_required' using errcode = '22023';
  end if;
  perform 1 from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  v_before := ch_user_points(p_user_id);
  insert into score_adjustments (user_id, points, reason, actor) values (p_user_id, p_points, p_reason, p_actor)
    returning id into v_id;
  v_after := ch_user_points(p_user_id);
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, 'adjust_points', p_user_id::text, jsonb_build_object('points', v_before),
            jsonb_build_object('points', v_after, 'delta', p_points, 'adjustment_id', v_id), p_reason);
  return jsonb_build_object('ok', true, 'adjustment_id', v_id, 'points', v_after);
end;
$$;

create or replace function ch_admin_set_ban(p_user_id uuid, p_ban bool, p_reason text, p_actor text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_old clients%rowtype;
begin
  perform ch_require_reason(p_reason, p_actor);
  select * into v_old from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  if p_ban then
    update clients set banned_at = coalesce(banned_at, now()), ban_reason = p_reason where id = p_user_id;
  else
    update clients set banned_at = null, ban_reason = null where id = p_user_id;
  end if;
  insert into audit_log (actor, action, target, before, after, reason)
    select p_actor, case when p_ban then 'ban' else 'unban' end, p_user_id::text,
           jsonb_build_object('banned_at', v_old.banned_at, 'ban_reason', v_old.ban_reason),
           jsonb_build_object('banned_at', c.banned_at, 'ban_reason', c.ban_reason), p_reason
    from clients c where c.id = p_user_id;
  return jsonb_build_object('ok', true, 'changed', (v_old.banned_at is not null) is distinct from p_ban);
end;
$$;

create or replace function ch_admin_ban(p_user_id uuid, p_reason text, p_actor text) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_ban(p_user_id, true, p_reason, p_actor)
$$;

create or replace function ch_admin_unban(p_user_id uuid, p_reason text, p_actor text) returns jsonb
language sql volatile security definer set search_path = public as $$
  select ch_admin_set_ban(p_user_id, false, p_reason, p_actor)
$$;

-- Lock order (C7): line_state rows by line_id -> per-user advisory lock -> queue rows.
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
      update line_state set state = 'idle', user_id = null, call_id = null, claimed_until = null,
                            updated_at = now(), version = version + 1
        where line_id = v_line.line_id;
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

-- ---------------------------------------------------------------- outbox / inbound / heartbeat
create or replace function ch_outbox_enqueue(p_handle text, p_user_id uuid, p_template text, p_body text,
                                             p_media_url text, p_dedupe_key text, p_not_before timestamptz,
                                             p_now timestamptz, p_ctx jsonb default null) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_id     bigint;
begin
  if v_handle is null or v_handle = '' then
    select handle into v_handle from client_handles where client_id = p_user_id order by created_at, handle limit 1;
  end if;
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  if p_body is null and p_template is null then
    raise exception 'body_or_template_required' using errcode = '22023';
  end if;
  insert into messages (direction, handle, user_id, body, media_url, template, ctx, dedupe_key, status, attempts,
                        not_before, created_at)
    values ('out', v_handle, p_user_id, p_body, p_media_url, p_template, p_ctx, p_dedupe_key, 'queued', 0,
            coalesce(p_not_before, p_now), p_now)
    on conflict (dedupe_key) do nothing
    returning id into v_id;
  if v_id is not null then
    return jsonb_build_object('id', v_id, 'duplicate', false);
  end if;
  select id into v_id from messages where dedupe_key = p_dedupe_key;
  return jsonb_build_object('id', v_id, 'duplicate', true);
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
    order by coalesce(not_before, created_at), id
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

-- Fenced by the attempt number returned by ch_outbox_claim (p_attempt). A mark whose attempt no longer matches (the
-- lease expired and another worker reclaimed the row), or a non-'sent' mark on a row no longer 'sending', is stale:
-- no-op returning {ok:false, reason:'stale'}. p_attempt null = unfenced (admin/legacy). Signature gained p_attempt.
drop function if exists ch_outbox_mark(bigint, text, text, text, timestamptz);
create or replace function ch_outbox_mark(p_id bigint, p_status text, p_provider_message_id text, p_error text,
                                          p_retry_at timestamptz, p_attempt int default null) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_max int := coalesce((ch_cfg('outbox_max_attempts') #>> '{}')::int, 5);
  v_m   messages%rowtype;
  v_new text := p_status;
begin
  if p_status is null or p_status not in ('sent', 'failed', 'suppressed', 'queued') then
    raise exception 'bad outbox status %', p_status using errcode = '22023';
  end if;
  select * into v_m from messages where id = p_id and direction = 'out' for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  if p_attempt is not null and (v_m.attempts is distinct from p_attempt
                                or (p_status <> 'sent' and v_m.status <> 'sending')) then
    return jsonb_build_object('ok', false, 'reason', 'stale', 'status', v_m.status);
  end if;
  if v_m.status = 'sent' or (p_status <> 'sent' and v_m.status in ('failed', 'suppressed')) then
    return jsonb_build_object('ok', true, 'changed', false, 'status', v_m.status);
  end if;
  if p_status = 'queued' and coalesce(v_m.attempts, 0) >= v_max then
    v_new := 'failed';
  end if;
  update messages set
    status = v_new,
    lease_until = null,
    provider_message_id = coalesce(p_provider_message_id, provider_message_id),
    last_error = coalesce(p_error, last_error),
    sent_at = case when v_new = 'sent' then now() else sent_at end,
    not_before = case when v_new = 'queued' then coalesce(p_retry_at, now()) else not_before end
  where id = p_id;
  return jsonb_build_object('ok', true, 'changed', true, 'status', v_new);
end;
$$;

create or replace function ch_inbound_record(p_provider_message_id text, p_handle text, p_body text,
                                             p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_user   uuid;
  v_id     bigint;
begin
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  select client_id into v_user from client_handles where handle = v_handle;
  insert into messages (direction, handle, user_id, body, provider_message_id, status, created_at)
    values ('in', v_handle, v_user, p_body, p_provider_message_id, 'received', p_now)
    on conflict (provider_message_id) do nothing
    returning id into v_id;
  if v_id is not null then
    return jsonb_build_object('id', v_id, 'duplicate', false, 'user_id', v_user);
  end if;
  select id, user_id into v_id, v_user from messages where provider_message_id = p_provider_message_id;
  return jsonb_build_object('id', v_id, 'duplicate', true, 'user_id', v_user);
end;
$$;

create or replace function ch_heartbeat(p_component text, p_detail jsonb, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  if p_component is null or btrim(p_component) = '' then
    raise exception 'component_required' using errcode = '22023';
  end if;
  insert into heartbeats (component, at, detail) values (p_component, p_now, p_detail)
    on conflict (component) do update set at = excluded.at, detail = excluded.detail;
  return jsonb_build_object('ok', true);
end;
$$;

-- ---------------------------------------------------------------- grants: service_role only
do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in (
             'ch_norm_handle', 'ch_require_reason', 'ch_queue_position', 'ch_registration_closed',
             'ch_join_start', 'ch_join_confirm', 'ch_user_by_handle', 'ch_set_opt', 'ch_user_status',
             'ch_leaderboard', 'ch_rank_deltas', 'ch_config_get', 'ch_config_set', 'ch_admin_set_void',
             'ch_admin_void_call', 'ch_admin_unvoid_call', 'ch_admin_adjust', 'ch_admin_set_ban', 'ch_admin_ban',
             'ch_admin_unban', 'ch_admin_queue_remove', 'ch_outbox_enqueue', 'ch_outbox_claim', 'ch_outbox_mark',
             'ch_inbound_record', 'ch_heartbeat') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
