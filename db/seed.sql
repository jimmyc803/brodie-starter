-- Demo seed: coach Tristan, client Ryan, a Day 1 program day, an active assignment. Idempotent (fixed ids, on conflict do nothing).
-- Run after db/schema.sql: supabase db query --linked --project-ref <ref> -f db/seed.sql
-- The worker's DEMO_CLIENT_ID for this seed is 00000000-0000-4000-8000-00000000c11e.
insert into coaches (id, name, persona, dashboard_token) values
  ('00000000-0000-4000-8000-00000000c0ac', 'Tristan',
   'High energy gym coach. Short, punchy encouragement. Call the client by name once per break.',
   'demo-tristan-dash-R7mQ2vK9xL4pN8sW1tY3')
on conflict (id) do nothing;
insert into clients (id, coach_id, name) values
  ('00000000-0000-4000-8000-00000000c11e', '00000000-0000-4000-8000-00000000c0ac', 'Ryan')
on conflict (id) do nothing;
insert into programs (id, coach_id, title) values
  ('00000000-0000-4000-8000-00000000f00d', '00000000-0000-4000-8000-00000000c0ac', 'Tristan 4-week starter')
on conflict (id) do nothing;
insert into program_days (id, program_id, day_number, title, exercises) values
  ('00000000-0000-4000-8000-00000000da01', '00000000-0000-4000-8000-00000000f00d', 1, 'Day 1 - Full body',
   '[{"exercise":"squats","sets":1,"reps":10},{"exercise":"pushups","sets":1,"reps":8},{"exercise":"jumping jacks","sets":1,"reps":20},{"exercise":"lunges","sets":1,"reps":10}]'::jsonb)
on conflict (id) do nothing;
insert into assignments (id, client_id, program_day_id) values
  ('00000000-0000-4000-8000-00000000a551', '00000000-0000-4000-8000-00000000c11e', '00000000-0000-4000-8000-00000000da01')
on conflict (id) do nothing;
