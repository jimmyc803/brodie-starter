-- Run after migration in an isolated/dev database. Always rolls test rows back.
begin;
do $$
declare
  coach_a uuid; coach_b uuid; client_a uuid; client_b uuid;
  program_a uuid; program_b uuid; day_a uuid; day_b uuid;
  rejected boolean;
begin
  insert into public.coaches(name, share_token) values ('RPC test A', 'rpc-test-a-123456789') returning id into coach_a;
  insert into public.coaches(name, share_token) values ('RPC test B', 'rpc-test-b-123456789') returning id into coach_b;
  insert into public.clients(coach_id, name) values (coach_a, 'A') returning id into client_a;
  insert into public.clients(coach_id, name) values (coach_b, 'B') returning id into client_b;
  program_a := public.save_coach_program('rpc-test-a-123456789', coach_a::text || '/fixture.pdf', '{"title":"Test","days":[{"day_number":1,"title":"Day","exercises":[{"exercise_key":"squat","name":"Squats","sets":3,"reps":10,"notes":"","supported":true}]}]}');
  program_b := public.save_coach_program('rpc-test-b-123456789', coach_b::text || '/fixture.pdf', '{"title":"Test","days":[{"day_number":1,"title":"Day","exercises":[{"exercise_key":"squat","name":"Squats","sets":3,"reps":10,"notes":"","supported":true}]}]}');
  select id into day_a from public.program_days where program_id = program_a;
  select id into day_b from public.program_days where program_id = program_b;
  perform public.assign_coach_program_day('rpc-test-a-123456789', client_a, day_a);
  perform public.assign_coach_program_day('rpc-test-a-123456789', client_a, day_a);
  if (select count(*) from public.assignments where client_id=client_a and active) <> 1 then raise exception 'Multiple active assignments'; end if;
  rejected := false;
  begin perform public.assign_coach_program_day('rpc-test-a-123456789', client_b, day_a);
  exception when others then rejected := true; end;
  if not rejected then raise exception 'Cross-coach client accepted'; end if;
  rejected := false;
  begin perform public.assign_coach_program_day('rpc-test-a-123456789', client_a, day_b);
  exception when others then rejected := true; end;
  if not rejected then raise exception 'Cross-coach day accepted'; end if;
  if (select count(*) from public.assignments where client_id=client_a and active and program_day_id=day_a) <> 1 then raise exception 'Failed assignment lost prior plan'; end if;
  rejected := false;
  begin perform public.save_coach_program('rpc-test-a-123456789', coach_b::text || '/fixture.pdf', '{"title":"Wrong","days":[]}');
  exception when others then rejected := true; end;
  if not rejected then raise exception 'Foreign PDF path accepted'; end if;
  rejected := false;
  begin perform public.save_coach_program('rpc-test-a-123456789', coach_a::text || '/fixture.pdf', '{"title":"Rollback","days":[{"day_number":1,"title":"OK","exercises":[{}]},{"day_number":1,"title":"Duplicate","exercises":[{}]}]}');
  exception when others then rejected := true; end;
  if not rejected or exists(select 1 from public.programs where coach_id=coach_a and title='Rollback') then raise exception 'Partial program persisted'; end if;
  update public.program_days set exercises = '[{"exercise_key":null,"supported":false,"sets":3,"reps":10,"name":"Bench press"}]' where id=day_a;
  rejected := false;
  begin perform public.assign_coach_program_day('rpc-test-a-123456789', client_a, day_a);
  exception when others then rejected := true; end;
  if not rejected then raise exception 'Manual-only day accepted'; end if;
  if (select count(*) from public.assignments where client_id=client_a and active) <> 1 then raise exception 'Refused manual day lost prior assignment'; end if;
  if has_function_privilege('anon', 'public.assign_coach_program_day(text,uuid,uuid)', 'EXECUTE') or
     has_function_privilege('authenticated', 'public.save_coach_program(text,text,jsonb)', 'EXECUTE') then
    raise exception 'RPC executable by public client';
  end if;
end $$;
rollback;
