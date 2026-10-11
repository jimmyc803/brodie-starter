-- Apply after db/schema.sql in the Supabase SQL editor. No public storage policies.
begin;
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('programs', 'programs', false, 3145728, array['application/pdf'])
on conflict (id) do update set public = false, file_size_limit = excluded.file_size_limit,
  allowed_mime_types = excluded.allowed_mime_types;

create or replace function public.save_coach_program(p_token text, p_pdf_path text, p_program jsonb)
returns uuid language plpgsql security definer set search_path = '' as $$
declare
  v_coach uuid;
  v_program uuid;
  v_day jsonb;
begin
  select id into v_coach from public.coaches where share_token = p_token;
  if v_coach is null then raise exception 'Invalid coach'; end if;
  if p_pdf_path is null or p_pdf_path not like v_coach::text || '/%.pdf' then
    raise exception 'Invalid PDF ownership';
  end if;
  if jsonb_typeof(p_program->'days') is distinct from 'array'
    or jsonb_array_length(p_program->'days') not between 1 and 60
    or coalesce(length(p_program->>'title'), 0) not between 1 and 200 then
    raise exception 'Invalid program';
  end if;
  insert into public.programs (coach_id, title, pdf_path, parsed)
    values (v_coach, p_program->>'title', p_pdf_path, p_program) returning id into v_program;
  for v_day in select value from jsonb_array_elements(p_program->'days') loop
    if jsonb_typeof(v_day->'exercises') is distinct from 'array'
      or jsonb_array_length(v_day->'exercises') not between 1 and 50
      or (v_day->>'day_number')::int not between 1 and 365
      or coalesce(length(v_day->>'title'), 0) not between 1 and 200 then
      raise exception 'Invalid training day';
    end if;
    insert into public.program_days (program_id, day_number, title, exercises)
      values (v_program, (v_day->>'day_number')::int, v_day->>'title', v_day->'exercises');
  end loop;
  return v_program;
end;
$$;

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
      and e->>'exercise_key' in ('squat', 'pushup', 'lunge', 'jumping_jack', 'bicep_curl')
      and (e->>'reps')::int > 0 and (e->>'sets')::int > 0
  ) then raise exception 'Day has no countable exercises'; end if;
  update public.assignments set active = false where client_id = v_client and active;
  insert into public.assignments (client_id, program_day_id, active)
    values (v_client, p_day_id, true) returning id into v_assignment;
  return v_assignment;
end;
$$;

revoke all on function public.save_coach_program(text, text, jsonb) from public, anon, authenticated;
revoke all on function public.assign_coach_program_day(text, uuid, uuid) from public, anon, authenticated;
grant execute on function public.save_coach_program(text, text, jsonb) to service_role;
grant execute on function public.assign_coach_program_day(text, uuid, uuid) to service_role;
commit;
