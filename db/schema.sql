-- Brodie for Coaches: data contract (team CONTRACT block, 2026-10-11). Owner: Stanley. Web: Jimmy. Parser: Ryan.
--
-- Flow: coach uploads a program PDF -> Gemini parses it into program_days -> the coach assigns a client a day (assignments,
-- active) -> the client calls Brodie -> the worker writes one session with sets, reps and muscle_scores.
-- No login. Links: client recap /r/<sessions.share_token>, coach dashboard /c/<coaches.share_token>.
-- RLS is on with no policies: the anon key reads nothing; server code (web/ and the worker) uses the service role key.
--
-- Exercise keys: squat, pushup, lunge, jumping_jack, bicep_curl. Muscle keys and the scoring rule: shared/muscles.json.
-- Run once in the Supabase SQL editor (or: supabase db query --linked --project-ref <ref> -f db/schema.sql).

create extension if not exists pgcrypto;

-- Random URL-safe token, 32 chars, for share links.
create or replace function new_share_token() returns text
language sql volatile as $$
  select translate(encode(gen_random_bytes(24), 'base64'), '+/', '-_')
$$;

create table if not exists coaches (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  share_token   text not null unique default new_share_token(),   -- /c/<share_token>
  persona       text,                                              -- optional: how Brodie talks for this coach (appended to starter/persona.md)
  created_at    timestamptz not null default now()
);

create table if not exists clients (
  id            uuid primary key default gen_random_uuid(),
  coach_id      uuid not null references coaches(id) on delete cascade,
  name          text not null,
  share_token   text not null unique default new_share_token(),
  created_at    timestamptz not null default now()
);

create table if not exists programs (
  id            uuid primary key default gen_random_uuid(),
  coach_id      uuid not null references coaches(id) on delete cascade,
  title         text not null,
  pdf_path      text,                 -- path in the 'programs' storage bucket
  parsed        jsonb,                -- Gemini's raw output
  created_at    timestamptz not null default now()
);

create table if not exists program_days (
  id            uuid primary key default gen_random_uuid(),
  program_id    uuid not null references programs(id) on delete cascade,
  day_number    int  not null,
  title         text not null,
  -- [{"exercise_key": "squat"|null, "name": "Back squat", "sets": 3, "reps": 10, "notes": "", "supported": true}, ...]
  -- supported = Brodie can count it (exercise_key not null). The worker runs supported items as <sets> plan items each.
  exercises     jsonb not null default '[]'::jsonb,
  created_at    timestamptz not null default now(),
  unique (program_id, day_number)
);

create table if not exists assignments (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  program_day_id uuid not null references program_days(id) on delete cascade,
  active         boolean not null default true,     -- the worker runs the client's newest active assignment
  assigned_at    timestamptz not null default now()
);
create index if not exists assignments_client_idx on assignments (client_id, active, assigned_at desc);

create table if not exists sessions (
  id               uuid primary key default gen_random_uuid(),
  client_id        uuid not null references clients(id) on delete cascade,
  program_day_id   uuid references program_days(id) on delete set null,
  started_at       timestamptz not null default now(),
  ended_at         timestamptz,                      -- null while the call is live
  share_token      text not null unique default new_share_token(),   -- /r/<share_token>
  recap_image_path text,                             -- path in the 'recaps' storage bucket once rendered
  created_at       timestamptz not null default now()
);
create index if not exists sessions_client_idx on sessions (client_id, started_at desc);

create table if not exists sets (
  id             uuid primary key default gen_random_uuid(),
  session_id     uuid not null references sessions(id) on delete cascade,
  exercise_key   text not null,
  set_number     int  not null,       -- 1-based within the exercise
  planned_reps   int  not null,
  completed_reps int  not null default 0,  -- the count Brodie reached; 0 = the set never happened (call ended first)
  started_at     timestamptz,
  ended_at       timestamptz,
  unique (session_id, exercise_key, set_number)
);

create table if not exists reps (
  id            uuid primary key default gen_random_uuid(),
  set_id        uuid not null references sets(id) on delete cascade,
  rep_number    int  not null,
  t             real not null,        -- seconds since the session started
  faults        text[] not null default '{}',   -- Brodie fault labels, e.g. {"squats - knees over toes"}; empty = clean rep
  unique (set_id, rep_number)
);

create table if not exists muscle_scores (
  session_id    uuid not null references sessions(id) on delete cascade,
  muscle        text not null,        -- one of shared/muscles.json "muscles" (one row per muscle, 15 per session)
  score         real not null,        -- 0..1 (0 when not trained)
  color         text not null check (color in ('green', 'yellow', 'red', 'gray')),
  coverage      text not null check (coverage in ('primary', 'secondary', 'none')),
  primary key (session_id, muscle)
);

alter table coaches       enable row level security;
alter table clients       enable row level security;
alter table programs      enable row level security;
alter table program_days  enable row level security;
alter table assignments   enable row level security;
alter table sessions      enable row level security;
alter table sets          enable row level security;
alter table reps          enable row level security;
alter table muscle_scores enable row level security;
