-- Push-Up Challenge, migration: web-only join / status (task 44, MESSAGING_PROVIDER=web_only fallback, SPEC §3 row 2).
-- Contract: docs/challenge/CONTRACTS.md §C2 (clients.auth_user_id, client_handles.linked_via 'web') + §C4 /web/*.
-- Idempotent: create if not exists / create or replace. Every function: security definer, search_path = public,
-- EXECUTE service_role only. New table: RLS on, no anon/authenticated grants.
--
-- Handle ownership (D-25): a web join NEVER binds a handle. The FaceTime handle typed into the form is only a pending
-- claim (web_handle_claims: 6-digit code, 24 h). Any number of pending claims may name the same handle and none blocks
-- anyone (no squatting, no enumeration of registered numbers). The claim becomes an authoritative client_handles row
-- (linked_via 'web') only when the owner texts "LINK <code>" FROM that handle (ch_web_link). Until then the user has no
-- handle: no texts are queued for them (ch_outbox_enqueue skips) and caller-id matching (ch_call_start chert_meta)
-- cannot resolve to them; the claim window still identifies them on calls.
--
--   ch_user_by_auth(p_auth_user_id uuid) -> {user_id, display_name, opted_out, banned} | {user_id: null}
--       The dispatcher derives user_id ONLY from a verified JWT `sub` through this; no /web endpoint takes a user_id.
--   ch_web_join(p_auth_user_id, p_display_name, p_handle /* nullable */, p_now)
--       -> {ok, reason /* ok|already_registered|bad_name|bad_handle|taken|closed */, user_id, claim}
--       Registers directly (the web form carries the 18+ / rules confirmation) with auth_user_id; optional handle claim.
--   ch_web_claim_handle(p_user_id, p_handle, p_now) -> {ok, reason /* ok|bad_handle|not_registered|already_linked */,
--       claim: {handle, code, expires_at}}. Replaces the user's other pending claims (one live code per user).
--   ch_web_link(p_handle, p_code, p_now) -> {ok, reason /* ok|already_linked|bad_code|expired|handle_owned */,
--       user_id, display_name}. Binds iff the handle is unowned or already the claimant's; then clears every pending
--       claim for that handle. A handle owned by another account (e.g. text-registered) is refused (handle_owned).
--   ch_web_me(p_user_id, p_now) -> ch_user_status + points_today, handle (verified only), pending_claim, claim,
--       in_call, line_open, ETA inputs, daily_call_cap, brodie_number, started, frozen. Only this user's data.
--   ch_outbox_enqueue (redefined): a WEB account (auth_user_id set) with no linked handle gets {id:null, duplicate:false,
--       skipped:'no_handle'} instead of raising handle_required, so post-call / rank-drop / jobs for web-only users never
--       fail the batch. Other handle-less users still raise handle_required (unchanged behaviour).

begin;

create table if not exists web_handle_claims (
  id          bigserial primary key,
  user_id     uuid not null references clients(id) on delete cascade,
  handle      text not null,
  code        text not null check (code ~ '^[0-9]{6}$'),
  created_at  timestamptz not null,
  expires_at  timestamptz not null,
  consumed_at timestamptz
);
create index if not exists web_handle_claims_handle_idx on web_handle_claims (handle) where consumed_at is null;
create index if not exists web_handle_claims_user_idx on web_handle_claims (user_id) where consumed_at is null;
alter table web_handle_claims enable row level security;
revoke all on table web_handle_claims from public, anon, authenticated;
revoke all on sequence web_handle_claims_id_seq from public, anon, authenticated;

-- 6 digits from the CSPRNG behind gen_random_uuid() (core since PG13; no pgcrypto needed).
create or replace function ch_web_code() returns text
language sql volatile security definer set search_path = public as $$
  select lpad(((('x' || substr(replace(gen_random_uuid()::text, '-', ''), 1, 12))::bit(48)::bigint) % 1000000)::text,
              6, '0')
$$;

create or replace function ch_web_valid_handle(p_handle text) returns bool
language sql immutable security definer set search_path = public as $$
  select p_handle is not null and (p_handle ~ '^\+[1-9][0-9]{1,14}$' or p_handle ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
$$;

create or replace function ch_user_by_auth(p_auth_user_id uuid) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select jsonb_build_object('user_id', c.id, 'display_name', c.display_name,
                               'opted_out', c.opted_out_at is not null, 'banned', c.banned_at is not null)
       from clients c
      where p_auth_user_id is not null and c.auth_user_id = p_auth_user_id and c.joined_at is not null),
    jsonb_build_object('user_id', null))
$$;

create or replace function ch_web_claim_handle(p_user_id uuid, p_handle text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_code   text;
  v_exp    timestamptz := p_now + interval '24 hours';
begin
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  if not ch_web_valid_handle(v_handle) then
    return jsonb_build_object('ok', false, 'reason', 'bad_handle', 'claim', null);
  end if;
  perform 1 from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_registered', 'claim', null);
  end if;
  if exists (select 1 from client_handles where handle = v_handle and client_id = p_user_id) then
    return jsonb_build_object('ok', true, 'reason', 'already_linked', 'claim', null);
  end if;
  update web_handle_claims set consumed_at = p_now where user_id = p_user_id and consumed_at is null;
  v_code := ch_web_code();
  insert into web_handle_claims (user_id, handle, code, created_at, expires_at)
    values (p_user_id, v_handle, v_code, p_now, v_exp);
  return jsonb_build_object('ok', true, 'reason', 'ok',
                            'claim', jsonb_build_object('handle', v_handle, 'code', v_code, 'expires_at', v_exp));
end;
$$;

create or replace function ch_web_join(p_auth_user_id uuid, p_display_name text, p_handle text, p_now timestamptz)
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := nullif(ch_norm_handle(p_handle), '');
  v_name   text := btrim(coalesce(p_display_name, ''));
  v_uid    uuid;
  v_joined timestamptz;
  v_coach  uuid;
  v_con    text;
  v_claim  jsonb;
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
    return jsonb_build_object('ok', true, 'reason', 'already_registered', 'user_id', v_uid, 'claim', null);
  end if;
  if ch_registration_closed(p_now) then
    return jsonb_build_object('ok', false, 'reason', 'closed', 'user_id', null, 'claim', null);
  end if;
  if v_name !~ '^[A-Za-z0-9_]{3,20}$' then
    return jsonb_build_object('ok', false, 'reason', 'bad_name', 'user_id', null, 'claim', null);
  end if;
  if v_handle is not null and not ch_web_valid_handle(v_handle) then
    return jsonb_build_object('ok', false, 'reason', 'bad_handle', 'user_id', null, 'claim', null);
  end if;
  if exists (select 1 from clients where lower(display_name) = lower(v_name) and id is distinct from v_uid) then
    return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null, 'claim', null);
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
  exception when unique_violation then
    get stacked diagnostics v_con = constraint_name;
    if v_con = 'clients_display_name_lower_uq' then
      return jsonb_build_object('ok', false, 'reason', 'taken', 'user_id', null, 'claim', null);
    end if;
    raise;
  end;

  if v_handle is not null then
    v_claim := ch_web_claim_handle(v_uid, v_handle, p_now) -> 'claim';
  end if;
  insert into audit_log (actor, action, target, before, after, reason, at)
    values ('system', 'user_join', v_uid::text, null,
            jsonb_build_object('display_name', v_name, 'claimed_handle', v_handle, 'joined_at', p_now, 'via', 'web'),
            null, p_now);
  return jsonb_build_object('ok', true, 'reason', 'ok', 'user_id', v_uid, 'claim', v_claim);
end;
$$;

create or replace function ch_web_link(p_handle text, p_code text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_code   text := regexp_replace(coalesce(p_code, ''), '\s', '', 'g');
  v_claim  web_handle_claims;
  v_owner  uuid;
  v_name   text;
begin
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  -- Serializes links of one handle (and the ownership check) without touching line/queue locks.
  perform pg_advisory_xact_lock(hashtextextended('web_link:' || v_handle, 0));
  if v_code !~ '^[0-9]{6}$' then
    return jsonb_build_object('ok', false, 'reason', 'bad_code', 'user_id', null);
  end if;
  select * into v_claim from web_handle_claims
   where handle = v_handle and code = v_code and consumed_at is null
   order by id desc limit 1 for update;
  if v_claim.id is null then
    return jsonb_build_object('ok', false, 'reason', 'bad_code', 'user_id', null);
  end if;
  if v_claim.expires_at <= p_now then
    return jsonb_build_object('ok', false, 'reason', 'expired', 'user_id', null);
  end if;
  select client_id into v_owner from client_handles where handle = v_handle for update;
  if v_owner is not null and v_owner <> v_claim.user_id then
    return jsonb_build_object('ok', false, 'reason', 'handle_owned', 'user_id', null);
  end if;
  select display_name into v_name from clients where id = v_claim.user_id and joined_at is not null;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'bad_code', 'user_id', null);
  end if;
  if v_owner is null then
    insert into client_handles (handle, client_id, kind, linked_via, created_at)
      values (v_handle, v_claim.user_id, case when position('@' in v_handle) > 0 then 'email' else 'phone' end, 'web',
              p_now);
  end if;
  update web_handle_claims set consumed_at = p_now where handle = v_handle and consumed_at is null;
  insert into audit_log (actor, action, target, before, after, reason, at)
    values ('system', 'handle_link', v_claim.user_id::text, null,
            jsonb_build_object('handle', v_handle, 'linked_via', 'web', 'claim_id', v_claim.id), 'LINK code', p_now);
  return jsonb_build_object('ok', true, 'reason', case when v_owner is null then 'ok' else 'already_linked' end,
                            'user_id', v_claim.user_id, 'display_name', v_name);
end;
$$;

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
    if (v_handle is null or v_handle = '')
       and exists (select 1 from clients where id = p_user_id and auth_user_id is not null) then
      -- Web account without a LINKed handle: nothing to send to (D-25), not an error. Any other handle-less user
      -- is still a data error (handle_required), as before.
      return jsonb_build_object('id', null, 'duplicate', false, 'skipped', 'no_handle');
    end if;
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
            and (v_status->>'calls_today')::int < v_cap
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

revoke all on function ch_web_code(), ch_web_valid_handle(text), ch_user_by_auth(uuid),
  ch_web_claim_handle(uuid, text, timestamptz), ch_web_join(uuid, text, text, timestamptz),
  ch_web_link(text, text, timestamptz), ch_web_me(uuid, timestamptz),
  ch_outbox_enqueue(text, uuid, text, text, text, text, timestamptz, timestamptz, jsonb)
  from public, anon, authenticated;
grant execute on function ch_web_code(), ch_web_valid_handle(text), ch_user_by_auth(uuid),
  ch_web_claim_handle(uuid, text, timestamptz), ch_web_join(uuid, text, text, timestamptz),
  ch_web_link(text, text, timestamptz), ch_web_me(uuid, timestamptz),
  ch_outbox_enqueue(text, uuid, text, text, text, text, timestamptz, timestamptz, jsonb)
  to service_role;

commit;
