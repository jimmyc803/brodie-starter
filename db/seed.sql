-- Demo seed: coach Tristan, client Ryan, Day 1 (squats 3x10, pushups 3x8, lunges 2x10, bicep curls 3x12), one active
-- assignment. Idempotent (fixed ids, on conflict do nothing). Run after db/schema.sql.
-- Worker env for this seed: DEMO_CLIENT_ID=00000000-0000-4000-8000-00000000c11e
-- Coach dashboard: /c/demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c
insert into coaches (id, name, share_token, persona) values
  ('00000000-0000-4000-8000-00000000c0ac', 'Tristan', 'demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c',
   'High energy gym coach. Short, punchy encouragement. Use the client''s name once per break.')
on conflict (id) do nothing;
insert into clients (id, coach_id, name, share_token) values
  ('00000000-0000-4000-8000-00000000c11e', '00000000-0000-4000-8000-00000000c0ac', 'Ryan', 'demo-ryan-Hc8vN2mK5pQ9xL1sT4wY7zA3')
on conflict (id) do nothing;
insert into programs (id, coach_id, title) values
  ('00000000-0000-4000-8000-00000000f00d', '00000000-0000-4000-8000-00000000c0ac', 'Tristan 4-week starter')
on conflict (id) do nothing;
insert into program_days (id, program_id, day_number, title, exercises) values
  ('00000000-0000-4000-8000-00000000da01', '00000000-0000-4000-8000-00000000f00d', 1, 'Day 1 - Full body',
   '[{"exercise_key":"squat","name":"Squats","sets":3,"reps":10,"notes":"","supported":true},
     {"exercise_key":"pushup","name":"Push-ups","sets":3,"reps":8,"notes":"","supported":true},
     {"exercise_key":"lunge","name":"Lunges","sets":2,"reps":10,"notes":"","supported":true},
     {"exercise_key":"bicep_curl","name":"Bicep curls","sets":3,"reps":12,"notes":"Light dumbbells","supported":true}]'::jsonb)
on conflict (id) do nothing;
insert into assignments (id, client_id, program_day_id, active) values
  ('00000000-0000-4000-8000-00000000a551', '00000000-0000-4000-8000-00000000c11e', '00000000-0000-4000-8000-00000000da01', true)
on conflict (id) do nothing;
