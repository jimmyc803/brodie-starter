-- Task 23: scheduled-jobs support. Idempotent; every function security definer, service_role only.
begin;

-- Small key/value state for the jobs loop (attempt counters, alert dedupe, queue-update baselines).
create table if not exists ch_job_state (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
alter table ch_job_state enable row level security;
revoke all on table ch_job_state from public, anon, authenticated;
grant select, insert, update, delete on table ch_job_state to service_role;

create or replace function ch_job_get(p_key text) returns jsonb
language sql stable security definer set search_path = public as $$
  select value from ch_job_state where key = p_key
$$;

create or replace function ch_job_list(p_prefix text) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_object_agg(key, value), '{}'::jsonb) from ch_job_state
  where left(key, length(p_prefix)) = p_prefix
$$;

create or replace function ch_job_set(p_key text, p_value jsonb, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  insert into ch_job_state (key, value, updated_at) values (p_key, p_value, p_now)
    on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at;
  return jsonb_build_object('ok', true);
end;
$$;

create or replace function ch_job_delete(p_key text) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  delete from ch_job_state where key = p_key;
  return jsonb_build_object('ok', true);
end;
$$;

-- Atomic attempt counter: {n, first_at}.
create or replace function ch_job_incr(p_key text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v jsonb;
begin
  insert into ch_job_state (key, value, updated_at)
    values (p_key, jsonb_build_object('n', 1, 'first_at', p_now), p_now)
    on conflict (key) do update
      set value = jsonb_build_object('n', coalesce((ch_job_state.value ->> 'n')::int, 0) + 1,
                                     'first_at', coalesce(ch_job_state.value -> 'first_at', to_jsonb(p_now))),
          updated_at = p_now
    returning value into v;
  return v;
end;
$$;

-- Post-call sweeper input: skip calls the jobs loop gave up on.
create or replace function ch_postcall_pending(p_now timestamptz, p_limit int default 50) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object('call_id', id, 'user_id', user_id) order by committed_at), '[]'::jsonb)
  from (select c.id, c.user_id, c.committed_at from calls c
         where c.decision = 'accept' and c.session_id is not null and c.postcall_done_at is null
           and c.committed_at < p_now - interval '30 seconds'
           and not exists (select 1 from ch_job_state s where s.key = 'postcall_giveup:' || c.id)
         order by c.committed_at limit greatest(p_limit, 0)) q
$$;

-- ---------------------------------------------------------------- power hours
create or replace function ch_power_hour_row(p_date_et date) returns jsonb
language sql stable security definer set search_path = public as $$
  select to_jsonb(ph) from power_hours ph where ph.date_et = p_date_et
$$;

create or replace function ch_power_hour_ensure(p_date_et date, p_starts_at timestamptz, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  insert into power_hours (date_et, starts_at, ends_at)
    values (p_date_et, p_starts_at, p_starts_at + interval '1 hour')
    on conflict (date_et) do nothing;
  return (select to_jsonb(ph) from power_hours ph where ph.date_et = p_date_et);
end;
$$;

-- p_kind: announced | warned | started. Sets the timestamp once.
create or replace function ch_power_hour_mark(p_date_et date, p_kind text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  if p_kind not in ('announced', 'warned', 'started') then
    raise exception 'bad power hour mark %', p_kind using errcode = '22023';
  end if;
  update power_hours set
    announced_at = case when p_kind = 'announced' then coalesce(announced_at, p_now) else announced_at end,
    warned_at = case when p_kind = 'warned' then coalesce(warned_at, p_now) else warned_at end,
    started_announced_at = case when p_kind = 'started' then coalesce(started_announced_at, p_now) else started_announced_at end
   where date_et = p_date_et;
  return jsonb_build_object('ok', found);
end;
$$;

-- ---------------------------------------------------------------- audience for proactive texts
-- Registered, not opted out, not banned, reachable (has a handle).
create or replace function ch_jobs_audience(p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  with y as (
    select user_id, sum(points)::int as pts from ch_score_events
     where ch_et_day(at) = ch_et_day(p_now) - 1 group by user_id
  )
  select coalesce(jsonb_agg(jsonb_build_object(
      'user_id', s.user_id, 'display_name', s.display_name, 'points', s.points, 'rank', s.rank,
      'streak', ch_streak(s.user_id, p_now), 'yesterday_points', coalesce(y.pts, 0),
      'qualified_today', ch_et_day(p_now) = any(s.streak_days),
      'calls_today', ch_calls_today(s.user_id, p_now)) order by s.rank), '[]'::jsonb)
  from ch_user_stats s left join y on y.user_id = s.user_id
  where s.listed and s.opted_out_at is null
    and exists (select 1 from client_handles h where h.client_id = s.user_id)
$$;

-- ---------------------------------------------------------------- health snapshot for alerts
create or replace function ch_jobs_health(p_now timestamptz) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'lines', coalesce((select jsonb_agg(jsonb_build_object('line_id', ls.line_id, 'state', ls.state,
                                                           'updated_at', ls.updated_at))
                         from line_state ls join lines l on l.id = ls.line_id where l.active), '[]'::jsonb),
    'queue_len', (select count(*) from queue where status in ('waiting', 'notified')),
    'out_sent', (select count(*) from messages where direction = 'out' and status = 'sent'
                   and created_at > p_now - interval '15 minutes'),
    'out_failed', (select count(*) from messages where direction = 'out' and status = 'failed'
                     and created_at > p_now - interval '15 minutes'),
    'heartbeats', coalesce((select jsonb_object_agg(component, at) from heartbeats), '{}'::jsonb))
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in (
             'ch_job_get', 'ch_job_list', 'ch_job_set', 'ch_job_delete', 'ch_job_incr', 'ch_postcall_pending',
             'ch_power_hour_row', 'ch_power_hour_ensure', 'ch_power_hour_mark', 'ch_jobs_audience',
             'ch_jobs_health') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
