-- Apply after schema.sql and 20261011_program_upload.sql before enabling public onboarding.
-- Durable, deployment-wide ceilings; failures deny issuance and paid parsing.
begin;
create table if not exists public.program_request_budget (
  action text not null check (action in ('workspace', 'parser')),
  started_at timestamptz not null default clock_timestamp()
);
create index if not exists program_request_budget_action_time
  on public.program_request_budget (action, started_at);
alter table public.program_request_budget enable row level security;
revoke all on public.program_request_budget from public, anon, authenticated, service_role;

create or replace function public.consume_program_budget(p_action text)
returns boolean language plpgsql security definer set search_path = '' as $$
declare
  v_limit integer;
  v_now timestamptz;
begin
  if p_action = 'workspace' then v_limit := 30;
  elsif p_action = 'parser' then v_limit := 60;
  else raise exception 'Invalid budget action';
  end if;
  -- A transaction-scoped lock serializes check + insert across processes and instances.
  perform pg_catalog.pg_advisory_xact_lock(809918, case when p_action = 'workspace' then 1 else 2 end);
  v_now := pg_catalog.clock_timestamp();
  delete from public.program_request_budget
    where action = p_action and started_at <= v_now - interval '1 hour';
  if (select count(*) from public.program_request_budget
      where action = p_action and started_at > v_now - interval '1 hour') >= v_limit then
    return false;
  end if;
  insert into public.program_request_budget(action, started_at) values (p_action, v_now);
  return true;
end;
$$;
revoke all on function public.consume_program_budget(text) from public, anon, authenticated;
grant execute on function public.consume_program_budget(text) to service_role;

-- Keep day assignment aligned with the already-supported pull-up parser and worker key.
create or replace function public.assign_coach_program_day(p_token text, p_client_id uuid, p_day_id uuid)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
  v_coach uuid;
  v_client uuid;
  v_assignment uuid;
begin
  select id into v_coach from public.coaches where share_token = p_token;
  if v_coach is null then raise exception 'Invalid coach'; end if;
  -- Serialize concurrent assignment requests for the same client, before deactivation.
  select id into v_client from public.clients
    where id = p_client_id and coach_id = v_coach for update;
  if v_client is null then raise exception 'Invalid client'; end if;
  perform d.id from public.program_days d join public.programs p on p.id = d.program_id
    where d.id = p_day_id and p.coach_id = v_coach for share of d, p;
  if not found then raise exception 'Invalid training day'; end if;
  if not exists (
    select 1 from public.program_days d,
      lateral jsonb_array_elements(d.exercises) e
    where d.id = p_day_id and e->>'supported' = 'true'
      and e->>'exercise_key' in ('squat', 'pushup', 'lunge', 'jumping_jack', 'bicep_curl', 'pullup')
      and (e->>'reps')::int > 0 and (e->>'sets')::int > 0
  ) then raise exception 'Day has no countable exercises'; end if;
  update public.assignments set active = false where client_id = v_client and active;
  insert into public.assignments (client_id, program_day_id, active)
    values (v_client, p_day_id, true) returning id into v_assignment;
  return v_assignment;
end;
$$;

revoke all on function public.assign_coach_program_day(text, uuid, uuid) from public, anon, authenticated;
grant execute on function public.assign_coach_program_day(text, uuid, uuid) to service_role;
commit;
