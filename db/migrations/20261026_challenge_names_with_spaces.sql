-- Display names may contain single internal spaces: "JOIN stan lee" registers "stan lee" (D-41).
--
-- One rule, in one place: ch_valid_display_name. 3-20 characters of [A-Za-z0-9_] in space-separated words, so a
-- name can neither start nor end with a space nor hold two in a row. Every writer (ch_join_start, ch_web_join,
-- challenge/messaging/commands.py, the site's join form) and the clients CHECK agree on it.
--
-- Existing names stay valid: the old rule is this one with a single word. Nothing is rewritten, no column is
-- added, and lower(display_name) uniqueness is unchanged ("Stan Lee" still collides with "stan lee").

create or replace function ch_valid_display_name(p_name text) returns bool
language sql immutable set search_path = public as $$
  select p_name is not null
     and char_length(p_name) between 3 and 20
     and p_name ~ '^[A-Za-z0-9_]+( [A-Za-z0-9_]+)*$'
$$;
revoke all on function ch_valid_display_name(text) from public;
grant execute on function ch_valid_display_name(text) to service_role;

-- The table CHECK spells the rule out instead of calling the function: a CHECK that depends on a function is
-- awkward to dump and restore, and this one must survive both.
alter table clients drop constraint if exists clients_display_name_format;
alter table clients add constraint clients_display_name_format
  check (display_name is null or (char_length(display_name) between 3 and 20
         and display_name ~ '^[A-Za-z0-9_]+( [A-Za-z0-9_]+)*$'));

create or replace function ch_join_start(p_handle text, p_display_name text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_name   text := regexp_replace(btrim(coalesce(p_display_name, '')), '\s+', ' ', 'g');
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
  if not ch_valid_display_name(v_name) then
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

create or replace function ch_web_join(p_auth_user_id uuid, p_display_name text, p_handle text, p_now timestamptz)
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := nullif(ch_norm_handle(p_handle), '');
  v_name   text := regexp_replace(btrim(coalesce(p_display_name, '')), '\s+', ' ', 'g');
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
  if not ch_valid_display_name(v_name) then
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
