-- Growth metrics: referral codes, acquisition source, team flag, first-party site visit counts, admin metrics RPC.
-- Idempotent (if not exists / create or replace / drop trigger if exists): safe to apply any number of times.
-- Every function: security definer, search_path = public, EXECUTE service_role only. New tables: RLS on, no grants.
--
-- clients (new columns)
--   ref_code            6 chars from 23456789BCDFGHJKLMNPQRSTVWXZ (no vowels: never spells a word, never "STOP"). Set by
--                       trigger whenever a client has joined_at and no code (insert or join); backfilled below for
--                       every existing participant. Unique.
--   referred_by         client who invited this one (their ref_code arrived with the JOIN text). Never overwritten.
--   acquisition_source  'referral' or a site link tag such as 'tiktok' (^[a-z0-9_]{1,24}$). Null = untagged; metrics
--                       report null as 'web' for web-form accounts (auth_user_id) and 'direct' otherwise.
--   is_team             team / test account; the metrics page can exclude these. Toggled by ch_admin_set_team (audited).
--
-- SMS attribution: "JOIN <name> ref-<CODE> src-<tag>" (tags in any order, see challenge/messaging/commands.py). The
-- handler calls ch_join_attribution(handle, ref, src, now) BEFORE validating the name, so a tag survives a retry with a
-- corrected name. Rows live in join_attribution (keyed by handle, first valid value per field wins) until the handle is
-- linked to a joined client by JOIN/YES (ch_join_confirm), when triggers copy them onto the client and delete the row.
--   ch_join_attribution(p_handle, p_ref_code, p_source, p_now) -> {ok, reason /* ok|empty|already_registered */,
--       ref_valid}. An unknown ref code is ignored (ref_valid false); the source tag is still kept.
--
-- Site visits (no cookies, no IP, no user agent, no handle): site_visits rows written by the site's /api/visit route.
--   ch_site_visit(p_kind /* landing|join_tap */, p_path, p_source, p_ref_code, p_referrer_host, p_now) -> {ok}
--
-- Admin
--   ch_admin_set_team(p_user_id, p_team, p_reason, p_actor, p_now) -> {ok, changed} | {ok:false, reason:'not_found'};
--       audit_log action 'set_team'.
--   ch_admin_metrics(p_include_team, p_now, p_days) -> one jsonb with KPIs, daily (ET) and hourly series, funnel and
--       virality aggregates. Display names and user ids only, never handles.
--   ch_admin_retention(p_include_team, p_now) -> cohort D1/D3/D7 return, first-time vs returning callers per day,
--       calls-per-user and streak distributions, engaged-but-not-calling (see the comment above the function).
--
-- ch_user_by_handle and ch_user_status are redefined (bodies copied from 20261013_challenge_misc.sql) to add
-- 'ref_code', so the welcome text and /me can show the participant's invite link.

begin;

-- ---------------------------------------------------------------- columns
alter table clients add column if not exists ref_code text;
alter table clients add column if not exists referred_by uuid references clients(id) on delete set null;
alter table clients add column if not exists acquisition_source text;
alter table clients add column if not exists is_team bool not null default false;
create unique index if not exists clients_ref_code_uq on clients (ref_code) where ref_code is not null;
create index if not exists clients_referred_by_idx on clients (referred_by) where referred_by is not null;
do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'clients_ref_code_format'
                 and conrelid = 'public.clients'::regclass) then
    alter table clients add constraint clients_ref_code_format check (ref_code is null or ref_code ~ '^[A-Z0-9]{4,12}$');
  end if;
  if not exists (select 1 from pg_constraint where conname = 'clients_acquisition_source_format'
                 and conrelid = 'public.clients'::regclass) then
    alter table clients add constraint clients_acquisition_source_format
      check (acquisition_source is null or acquisition_source ~ '^[a-z0-9_]{1,24}$');
  end if;
end $$;

-- ---------------------------------------------------------------- tables
create table if not exists join_attribution (
  handle     text primary key,
  ref_code   text check (ref_code is null or ref_code ~ '^[A-Z0-9]{4,12}$'),
  source     text check (source is null or source ~ '^[a-z0-9_]{1,24}$'),
  created_at timestamptz not null,
  updated_at timestamptz not null
);
alter table join_attribution enable row level security;
revoke all on table join_attribution from public, anon, authenticated;

create table if not exists site_visits (
  id            bigserial primary key,
  at            timestamptz not null,
  kind          text not null check (kind in ('landing', 'join_tap')),
  path          text not null check (path ~ '^/' and length(path) <= 120),
  source        text check (source is null or source ~ '^[a-z0-9_]{1,24}$'),
  ref_code      text check (ref_code is null or ref_code ~ '^[A-Z0-9]{4,12}$'),
  referrer_host text check (referrer_host is null or referrer_host ~ '^[a-z0-9.-]{1,100}$')
);
create index if not exists site_visits_at_idx on site_visits (at);
alter table site_visits enable row level security;
revoke all on table site_visits from public, anon, authenticated;
revoke all on sequence site_visits_id_seq from public, anon, authenticated;

-- ---------------------------------------------------------------- referral codes
-- 6 symbols from a 28-letter alphabet (~4.8e8 codes) drawn from the CSPRNG behind gen_random_uuid() (core since PG13).
create or replace function ch_new_ref_code() returns text
language plpgsql volatile security definer set search_path = public as $$
declare
  v_abc  constant text := '23456789BCDFGHJKLMNPQRSTVWXZ';
  v_raw  bytea;
  v_code text;
begin
  loop
    v_raw := decode(replace(gen_random_uuid()::text, '-', ''), 'hex');
    v_code := '';
    for i in 0..5 loop
      v_code := v_code || substr(v_abc, 1 + get_byte(v_raw, i) % 28, 1);
    end loop;
    exit when not exists (select 1 from clients where ref_code = v_code);
  end loop;
  return v_code;
end;
$$;

create or replace function ch_clients_ref_code() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.joined_at is not null and new.ref_code is null then
    new.ref_code := ch_new_ref_code();
  end if;
  return new;
end;
$$;
drop trigger if exists ch_clients_ref_code on clients;
create trigger ch_clients_ref_code before insert or update of joined_at, ref_code on clients
  for each row execute function ch_clients_ref_code();

-- Backfill: every existing participant gets a code (the trigger fires on this update).
update clients set ref_code = null where joined_at is not null and ref_code is null;

-- ---------------------------------------------------------------- attribution
create or replace function ch_norm_ref_code(p_code text) returns text
language sql immutable security definer set search_path = public as $$
  select case when upper(btrim(p_code)) ~ '^[A-Z0-9]{4,12}$' then upper(btrim(p_code)) end
$$;

create or replace function ch_norm_source(p_source text) returns text
language sql immutable security definer set search_path = public as $$
  select case when lower(btrim(p_source)) ~ '^[a-z0-9_]{1,24}$' then lower(btrim(p_source)) end
$$;

create or replace function ch_join_attribution(p_handle text, p_ref_code text, p_source text, p_now timestamptz)
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_handle text := ch_norm_handle(p_handle);
  v_ref    text := ch_norm_ref_code(p_ref_code);
  v_src    text := ch_norm_source(p_source);
  v_valid  bool := false;
begin
  if v_handle is null or v_handle = '' then
    raise exception 'handle_required' using errcode = '22023';
  end if;
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  if exists (select 1 from client_handles h join clients c on c.id = h.client_id
             where h.handle = v_handle and c.joined_at is not null) then
    return jsonb_build_object('ok', false, 'reason', 'already_registered', 'ref_valid', false);
  end if;
  if v_ref is not null then
    v_valid := exists (select 1 from clients where ref_code = v_ref and joined_at is not null);
    if not v_valid then
      v_ref := null;
    end if;
  end if;
  if v_ref is null and v_src is null then
    return jsonb_build_object('ok', false, 'reason', 'empty', 'ref_valid', false);
  end if;
  insert into join_attribution (handle, ref_code, source, created_at, updated_at)
    values (v_handle, v_ref, v_src, p_now, p_now)
    on conflict (handle) do update
      set ref_code   = coalesce(join_attribution.ref_code, excluded.ref_code),
          source     = coalesce(join_attribution.source, excluded.source),
          updated_at = excluded.updated_at;
  return jsonb_build_object('ok', true, 'reason', 'ok', 'ref_valid', v_valid);
end;
$$;

-- Copy a handle's pending attribution onto the (joined) client, never overwriting, then drop it.
create or replace function ch_attribute_join(p_client uuid, p_handle text) returns void
language plpgsql volatile security definer set search_path = public as $$
declare
  v_attr join_attribution%rowtype;
  v_ref  uuid;
begin
  if p_client is null or p_handle is null then
    return;
  end if;
  if not exists (select 1 from clients where id = p_client and joined_at is not null) then
    return;
  end if;
  delete from join_attribution where handle = p_handle returning * into v_attr;
  if not found then
    return;
  end if;
  if v_attr.ref_code is not null then
    select id into v_ref from clients
     where ref_code = v_attr.ref_code and joined_at is not null and id <> p_client;
  end if;
  update clients
     set referred_by        = coalesce(referred_by, v_ref),
         acquisition_source = coalesce(acquisition_source, v_attr.source,
                                       case when v_ref is not null then 'referral' end)
   where id = p_client;
end;
$$;

-- ch_join_confirm inserts the client (joined) and then its 'join' handle: attribute on the handle insert.
create or replace function ch_client_handles_attribute() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  if new.linked_via = 'join' then
    perform ch_attribute_join(new.client_id, new.handle);
  end if;
  return null;
end;
$$;
drop trigger if exists ch_client_handles_attribute on client_handles;
create trigger ch_client_handles_attribute after insert on client_handles
  for each row execute function ch_client_handles_attribute();

-- ch_join_confirm on a handle already linked to a non-joined client upgrades that client (no handle insert).
create or replace function ch_clients_attribute() returns trigger
language plpgsql security definer set search_path = public as $$
declare v_handle text;
begin
  for v_handle in select handle from client_handles where client_id = new.id loop
    perform ch_attribute_join(new.id, v_handle);
  end loop;
  return null;
end;
$$;
drop trigger if exists ch_clients_attribute on clients;
create trigger ch_clients_attribute after update of joined_at on clients
  for each row when (old.joined_at is null and new.joined_at is not null)
  execute function ch_clients_attribute();

-- ---------------------------------------------------------------- site visits
create or replace function ch_site_visit(p_kind text, p_path text, p_source text, p_ref_code text,
                                         p_referrer_host text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_path text := left(split_part(split_part(coalesce(p_path, '/'), '?', 1), '#', 1), 120);
  v_host text := lower(btrim(p_referrer_host));
begin
  if p_kind is null or p_kind not in ('landing', 'join_tap') then
    raise exception 'bad_kind' using errcode = '22023';
  end if;
  if p_now is null then
    raise exception 'p_now required' using errcode = '22023';
  end if;
  if v_path !~ '^/' then
    v_path := '/';
  end if;
  if v_host !~ '^[a-z0-9.-]{1,100}$' then
    v_host := null;
  end if;
  insert into site_visits (at, kind, path, source, ref_code, referrer_host)
    values (p_now, p_kind, v_path, ch_norm_source(p_source), ch_norm_ref_code(p_ref_code), v_host);
  return jsonb_build_object('ok', true);
end;
$$;

-- ---------------------------------------------------------------- registration lookups (+ ref_code)
create or replace function ch_user_by_handle(p_handle text) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(
    (select jsonb_build_object('user_id', c.id, 'display_name', c.display_name,
                               'opted_out', c.opted_out_at is not null, 'banned', c.banned_at is not null,
                               'ref_code', c.ref_code)
       from client_handles h join clients c on c.id = h.client_id
      where h.handle = ch_norm_handle(p_handle) and c.joined_at is not null),
    jsonb_build_object('user_id', null))
$$;

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
    'ref_code', (select ref_code from clients where id = p_user_id));
end;
$$;

-- ---------------------------------------------------------------- admin
create or replace function ch_admin_set_team(p_user_id uuid, p_team bool, p_reason text, p_actor text,
                                             p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_old bool;
begin
  if p_now is null then
    raise exception 'ch_admin_set_team: p_now required' using errcode = '22023';
  end if;
  if p_team is null then
    raise exception 'ch_admin_set_team: p_team required' using errcode = '22023';
  end if;
  perform ch_require_reason(p_reason, p_actor);
  select is_team into v_old from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  update clients set is_team = p_team where id = p_user_id;
  insert into audit_log (actor, action, target, before, after, reason, at)
    values (p_actor, 'set_team', p_user_id::text, jsonb_build_object('is_team', v_old),
            jsonb_build_object('is_team', p_team), p_reason, p_now);
  return jsonb_build_object('ok', true, 'changed', v_old is distinct from p_team);
end;
$$;

-- One round trip for the whole metrics page. Day buckets are ET calendar days (ch_et_day); hour buckets are UTC hour
-- starts (ET offsets are whole hours, so they are ET hours too). Series are sparse: the site fills empty buckets.
create or replace function ch_admin_metrics(p_include_team bool, p_now timestamptz, p_days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_days  int := least(greatest(coalesce(p_days, 30), 1), 120);
  v_team  bool := coalesce(p_include_team, false);
  v_today date;
  v_since timestamptz;
  v_hours timestamptz;
begin
  if p_now is null then
    raise exception 'ch_admin_metrics: p_now required' using errcode = '22023';
  end if;
  v_today := ch_et_day(p_now);
  v_since := ch_et_day_start(v_today - (v_days - 1));
  v_hours := date_trunc('hour', p_now) - interval '47 hours';

  return (
    with recursive u as (
      select c.id, c.display_name, c.joined_at, c.opted_out_at, c.banned_at, c.referred_by, c.is_team,
             coalesce(c.acquisition_source, case when c.auth_user_id is not null then 'web' else 'direct' end) as source
        from clients c
       where c.joined_at is not null and (v_team or not c.is_team)
    ),
    cs as (
      select s.call_id, s.user_id, s.decision, s.void, s.counted_toward_cap, s.connected_at, s.date_et, s.valid_reps
        from ch_call_stats s
       where v_team or s.user_id is null
          or not exists (select 1 from clients t where t.id = s.user_id and t.is_team)
    ),
    called as (select distinct cs.user_id from cs join u on u.id = cs.user_id),
    scored as (
      select distinct cs.user_id from cs join u on u.id = cs.user_id
       where cs.decision = 'accept' and not cs.void and cs.valid_reps > 0
    ),
    started_handles as (
      select m.handle from messages m
       where m.direction = 'in' and m.body ~* '^\W*join(\W|$)'
      union select handle from join_pending
      union select handle from join_attribution
    ),
    -- Referral tree: roots are users without an (included) referrer; the path guards against cycles.
    tree(id, depth, path) as (
      select u.id, 0, array[u.id] from u
       where u.referred_by is null or not exists (select 1 from u p where p.id = u.referred_by)
      union all
      select k.id, t.depth + 1, t.path || k.id from u k join tree t on k.referred_by = t.id
       where not k.id = any(t.path) and t.depth < 100
    ),
    started_extra as (
      select count(*)::int as n from started_handles sh
       where not exists (select 1 from client_handles h join clients c on c.id = h.client_id
                          where h.handle = sh.handle and c.joined_at is not null)
    )
    select jsonb_build_object(
      'generated_at', p_now,
      'include_team', v_team,
      'days', v_days,
      'today', v_today,
      'kpis', jsonb_build_object(
        'joined', (select count(*) from u),
        'joined_today', (select count(*) from u where ch_et_day(u.joined_at) = v_today),
        'called_users', (select count(*) from called),
        'scored_users', (select count(*) from scored),
        'calls_connected', (select count(*) from cs),
        'calls_accepted', (select count(*) from cs where cs.decision = 'accept'),
        'calls_counted', (select count(*) from cs where cs.counted_toward_cap),
        'valid_reps', (select coalesce(sum(cs.valid_reps), 0) from cs where cs.decision = 'accept' and not cs.void),
        'dau_today', (select count(distinct cs.user_id) from cs join u on u.id = cs.user_id
                       where cs.date_et = v_today),
        'opted_out', (select count(*) from u where u.opted_out_at is not null),
        'banned', (select count(*) from u where u.banned_at is not null),
        'team_accounts', (select count(*) from clients where joined_at is not null and is_team),
        'pending_joins', (select count(*) from join_pending)),
      'signups_before', (select count(*) from u where u.joined_at < v_since),
      'signups_daily', (select coalesce(jsonb_agg(jsonb_build_object('day', x.d, 'n', x.n) order by x.d), '[]'::jsonb)
                          from (select ch_et_day(u.joined_at) as d, count(*) as n from u
                                 where u.joined_at >= v_since group by 1) x),
      'signups_hourly', (select coalesce(jsonb_agg(jsonb_build_object('hour', x.h, 'n', x.n) order by x.h), '[]'::jsonb)
                           from (select date_trunc('hour', u.joined_at) as h, count(*) as n from u
                                  where u.joined_at >= v_hours group by 1) x),
      'calls_daily', (select coalesce(jsonb_agg(jsonb_build_object('day', x.d, 'connected', x.n, 'accepted', x.a,
                                                                   'valid_reps', x.r) order by x.d), '[]'::jsonb)
                        from (select cs.date_et as d, count(*) as n,
                                     count(*) filter (where cs.decision = 'accept') as a,
                                     coalesce(sum(cs.valid_reps) filter (where cs.decision = 'accept' and not cs.void),
                                              0) as r
                                from cs where cs.connected_at >= v_since group by 1) x),
      'calls_hourly', (select coalesce(jsonb_agg(jsonb_build_object('hour', x.h, 'n', x.n) order by x.h), '[]'::jsonb)
                         from (select date_trunc('hour', cs.connected_at) as h, count(*) as n from cs
                                where cs.connected_at >= v_hours group by 1) x),
      'visits_daily', (select coalesce(jsonb_agg(jsonb_build_object('day', x.d, 'landings', x.l, 'join_taps', x.j)
                                                 order by x.d), '[]'::jsonb)
                         from (select ch_et_day(v.at) as d, count(*) filter (where v.kind = 'landing') as l,
                                      count(*) filter (where v.kind = 'join_tap') as j
                                 from site_visits v where v.at >= v_since group by 1) x),
      'funnel', jsonb_build_object(
        'visits', (select count(*) from site_visits where kind = 'landing'),
        'join_taps', (select count(*) from site_visits where kind = 'join_tap'),
        'join_started', (select count(*) from u) + (select n from started_extra),
        'joined', (select count(*) from u),
        'called', (select count(*) from called),
        'scored', (select count(*) from scored)),
      'virality', jsonb_build_object(
        'referred', (select count(*) from u where u.referred_by is not null),
        'active_referrers', (select count(distinct u.referred_by) from u
                              where exists (select 1 from u r where r.id = u.referred_by)),
        'sources', (select coalesce(jsonb_agg(jsonb_build_object('source', x.source, 'n', x.n)
                                              order by x.n desc, x.source), '[]'::jsonb)
                      from (select u.source, count(*) as n from u group by 1) x),
        'visit_sources', (select coalesce(jsonb_agg(jsonb_build_object('source', x.s, 'n', x.n)
                                                    order by x.n desc, x.s), '[]'::jsonb)
                            from (select coalesce(v.source, case when v.ref_code is not null then 'referral' end,
                                                  v.referrer_host, 'direct') as s, count(*) as n
                                    from site_visits v where v.kind = 'landing' group by 1
                                    order by 2 desc, 1 limit 12) x),
        'top_referrers', (select coalesce(jsonb_agg(jsonb_build_object('user_id', x.id, 'display_name', x.display_name,
                                                                       'referred', x.n, 'referred_called', x.c)
                                                    order by x.n desc, x.c desc, x.display_name), '[]'::jsonb)
                            from (select r.id, r.display_name, count(*) as n,
                                         count(*) filter (where exists (select 1 from called k where k.user_id = ch.id)) as c
                                    from u ch join u r on r.id = ch.referred_by
                                   group by r.id, r.display_name
                                   order by n desc, c desc, r.display_name limit 10) x),
        'max_depth', (select coalesce(max(t.depth), 0) from tree t),
        'second_gen', (select count(*) from tree t where t.depth >= 2))
    )
  );
end;
$$;

-- Retention, from our own records only (Chert reports no caller data, and a FaceTime that never connects, e.g. a busy
-- line, leaves no row anywhere). "Called" = a connected calls row for the user (any decision); "active" = called OR sent
-- us an inbound text that ET day (texts matched by messages.user_id, else by the sender's linked handle).
--   cohorts[]: one per ET join day: n, returned (called on any later ET day) and, for k in 1/3/7, dK = {eligible
--     (join day + k <= today), complete (join day + k < today; today is still in progress), called, active} where
--     called/active count users of the cohort doing so on ET day join+k exactly.
--   callers_daily[]: per ET day with calls: first-time callers (first call ever that day) vs returning callers.
--   calls_per_user[]: {calls, users} for every included participant (calls = 0 included).
--   streaks[]: {streak, users} current streak (ch_streak_days as of today); qualified_days[]: {days, users} number of
--     distinct qualifying ET days (ch_user_stats.streak_days).
--   engaged_not_calling: participants with an inbound text in the last 24 h and no connected call in the last 24 h:
--     {n, users: up to 25 {user_id, display_name, last_text_at}} (display names only).
create or replace function ch_admin_retention(p_include_team bool, p_now timestamptz) returns jsonb
language plpgsql stable security definer set search_path = public as $$
declare
  v_team  bool := coalesce(p_include_team, false);
  v_today date;
begin
  if p_now is null then
    raise exception 'ch_admin_retention: p_now required' using errcode = '22023';
  end if;
  v_today := ch_et_day(p_now);

  return (
    with u as (
      select c.id, c.display_name, ch_et_day(c.joined_at) as jd
        from clients c
       where c.joined_at is not null and (v_team or not c.is_team)
    ),
    calls_u as (
      select k.user_id, k.connected_at from calls k join u on u.id = k.user_id where k.connected_at <= p_now
    ),
    call_days as (select distinct user_id, ch_et_day(connected_at) as d from calls_u),
    texts_u as (
      select coalesce(m.user_id, h.client_id) as user_id, m.created_at
        from messages m left join client_handles h on h.handle = m.handle
       where m.direction = 'in' and m.created_at <= p_now
    ),
    text_days as (
      select distinct t.user_id, ch_et_day(t.created_at) as d from texts_u t join u on u.id = t.user_id
    ),
    act_days as (select user_id, d from call_days union select user_id, d from text_days),
    first_call as (select user_id, min(d) as d from call_days group by user_id),
    ks(k) as (values (1), (3), (7)),
    cohort_k as (
      select u.jd, ks.k,
             count(distinct cd.user_id) as called,
             count(distinct ad.user_id) as active
        from u cross join ks
        left join call_days cd on cd.user_id = u.id and cd.d = u.jd + ks.k
        left join act_days ad on ad.user_id = u.id and ad.d = u.jd + ks.k
       group by u.jd, ks.k
    ),
    last_call as (select user_id, max(d) as d from call_days group by user_id),
    cohort as (
      select u.jd, count(*) as n, count(*) filter (where lc.d > u.jd) as returned
        from u left join last_call lc on lc.user_id = u.id group by u.jd
    ),
    per_user as (
      select u.id, count(k.user_id) as n from u left join calls_u k on k.user_id = u.id group by u.id
    ),
    engaged as (
      select u.id, u.display_name, max(t.created_at) as last_text_at
        from u join texts_u t on t.user_id = u.id
       where t.created_at > p_now - interval '24 hours'
         and not exists (select 1 from calls_u k where k.user_id = u.id and k.connected_at > p_now - interval '24 hours')
       group by u.id, u.display_name
    )
    select jsonb_build_object(
      'generated_at', p_now,
      'include_team', v_team,
      'today', v_today,
      'cohorts', (select coalesce(jsonb_agg(
                    jsonb_build_object('day', c.jd, 'n', c.n, 'returned', c.returned)
                    || (select jsonb_object_agg('d' || ck.k, jsonb_build_object(
                                 'eligible', c.jd + ck.k <= v_today, 'complete', c.jd + ck.k < v_today,
                                 'called', ck.called, 'active', ck.active))
                          from cohort_k ck where ck.jd = c.jd)
                    order by c.jd), '[]'::jsonb) from cohort c),
      'callers_daily', (select coalesce(jsonb_agg(jsonb_build_object('day', x.d, 'first_time', x.f, 'returning', x.r)
                                                  order by x.d), '[]'::jsonb)
                          from (select cd.d, count(*) filter (where fc.d = cd.d) as f,
                                       count(*) filter (where fc.d < cd.d) as r
                                  from call_days cd join first_call fc on fc.user_id = cd.user_id
                                 group by cd.d) x),
      'calls_per_user', (select coalesce(jsonb_agg(jsonb_build_object('calls', x.n, 'users', x.users) order by x.n),
                                         '[]'::jsonb)
                           from (select n, count(*) as users from per_user group by n) x),
      'streaks', (select coalesce(jsonb_agg(jsonb_build_object('streak', x.s, 'users', x.users) order by x.s), '[]'::jsonb)
                    from (select ch_streak_days(s.streak_days, v_today) as s, count(*) as users
                            from ch_user_stats s join u on u.id = s.user_id group by 1) x),
      'qualified_days', (select coalesce(jsonb_agg(jsonb_build_object('days', x.dd, 'users', x.users) order by x.dd),
                                         '[]'::jsonb)
                           from (select coalesce(cardinality(s.streak_days), 0) as dd, count(*) as users
                                   from ch_user_stats s join u on u.id = s.user_id group by 1) x),
      'engaged_not_calling', jsonb_build_object(
        'n', (select count(*) from engaged),
        'users', (select coalesce(jsonb_agg(jsonb_build_object('user_id', e.id, 'display_name', e.display_name,
                                                               'last_text_at', e.last_text_at)
                                            order by e.last_text_at desc), '[]'::jsonb)
                    from (select * from engaged order by last_text_at desc limit 25) e))
    )
  );
end;
$$;

-- ---------------------------------------------------------------- grants: service_role only
revoke all on function
  ch_admin_retention(bool, timestamptz),
  ch_new_ref_code(), ch_clients_ref_code(), ch_norm_ref_code(text), ch_norm_source(text),
  ch_join_attribution(text, text, text, timestamptz), ch_attribute_join(uuid, text), ch_client_handles_attribute(),
  ch_clients_attribute(), ch_site_visit(text, text, text, text, text, timestamptz), ch_user_by_handle(text),
  ch_user_status(uuid, timestamptz), ch_admin_set_team(uuid, bool, text, text, timestamptz),
  ch_admin_metrics(bool, timestamptz, int)
  from public, anon, authenticated;
grant execute on function
  ch_admin_retention(bool, timestamptz),
  ch_new_ref_code(), ch_clients_ref_code(), ch_norm_ref_code(text), ch_norm_source(text),
  ch_join_attribution(text, text, text, timestamptz), ch_attribute_join(uuid, text), ch_client_handles_attribute(),
  ch_clients_attribute(), ch_site_visit(text, text, text, text, text, timestamptz), ch_user_by_handle(text),
  ch_user_status(uuid, timestamptz), ch_admin_set_team(uuid, bool, text, text, timestamptz),
  ch_admin_metrics(bool, timestamptz, int)
  to service_role;

commit;
