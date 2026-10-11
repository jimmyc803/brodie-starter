-- Brodie for Coaches: data contract (schema v1, 2026-10-11). Owner: Stanley. Reviewer: Jimmy.
--
-- Flow: a coach uploads a program PDF -> Gemini parses it into program_days -> the coach assigns a client a day
-- (assignments) -> the client calls Brodie -> the worker writes one session with its sets, reps and muscle_scores.
-- Nobody logs in. The recap pages are opened by unguessable tokens: /r/<client_token> and /c/<coach_token>.
-- The worker and the Next.js server use the service role key, so Row Level Security is on with no policies:
-- the anon key can read nothing, and every read goes through server code that looks up a token.
--
-- Exercise names are Brodie plan names: 'squats', 'pushups', 'jumping jacks', 'lunges', 'bicep curls'.
-- Muscle names and the color rule live in shared/muscles.json.
-- Run once in the Supabase SQL editor. Safe to re-run on an empty project (if not exists everywhere).

create extension if not exists pgcrypto;  -- gen_random_uuid(), gen_random_bytes()

-- A random URL-safe token, 32 characters, about 190 bits. Used for share links.
create or replace function new_share_token() returns text
language sql volatile as $$
  select translate(encode(gen_random_bytes(24), 'base64'), '+/', '-_')
$$;

create table if not exists coaches (
  id            uuid primary key default gen_random_uuid(),
  name          text not null,
  persona       text,                 -- prompt text appended to starter/persona.md for this coach's voice
  phone         text,                 -- E.164, for iMessage recaps
  dashboard_token text not null unique default new_share_token(),  -- /c/<token> lists this coach's clients
  created_at    timestamptz not null default now()
);

create table if not exists clients (
  id            uuid primary key default gen_random_uuid(),
  coach_id      uuid not null references coaches(id) on delete cascade,
  name          text not null,
  phone         text,                 -- E.164; later used to match the FaceTime caller
  created_at    timestamptz not null default now()
);

create table if not exists programs (
  id            uuid primary key default gen_random_uuid(),
  coach_id      uuid not null references coaches(id) on delete cascade,
  title         text not null,
  pdf_path      text,                 -- path in the 'programs' storage bucket
  parsed        jsonb,                -- Gemini's raw output, kept for debugging; program_days is the source of truth
  created_at    timestamptz not null default now()
);

create table if not exists program_days (
  id            uuid primary key default gen_random_uuid(),
  program_id    uuid not null references programs(id) on delete cascade,
  day_number    int  not null,
  title         text not null,        -- e.g. 'Day 1 - Lower body'
  -- ordered list: [{"exercise": "squats", "sets": 1, "reps": 10}, ...]
  -- The worker turns it into a Brodie plan string: 'squats:10,pushups:8' (one item per set).
  exercises     jsonb not null default '[]'::jsonb,
  created_at    timestamptz not null default now(),
  unique (program_id, day_number)
);

create table if not exists assignments (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  program_day_id uuid not null references program_days(id) on delete cascade,
  assigned_at    timestamptz not null default now()
  -- The client's current day = their newest assignment.
);
create index if not exists assignments_client_idx on assignments (client_id, assigned_at desc);

create table if not exists sessions (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references clients(id) on delete cascade,
  program_day_id uuid references program_days(id) on delete set null,
  status         text not null default 'live' check (status in ('live', 'done', 'abandoned')),
  started_at     timestamptz not null default now(),
  ended_at       timestamptz,
  room           text,                -- LiveKit room name, to find the worker's logs
  plan           text not null,       -- the exact plan string Brodie ran, e.g. 'squats:10,pushups:8'
  client_token   text not null unique default new_share_token(),  -- /r/<token>
  coach_token    text not null unique default new_share_token(),  -- /c/s/<token>
  recap_image_path text,              -- path in the 'recaps' storage bucket, set after the PNG is rendered
  overall_score  real,                -- 0..1, mean of the set quality scores
  created_at     timestamptz not null default now()
);
create index if not exists sessions_client_idx on sessions (client_id, started_at desc);

create table if not exists sets (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references sessions(id) on delete cascade,
  set_number    int  not null,        -- 1-based order in the session (Brodie's plan item + 1)
  exercise      text not null,
  planned_reps  int  not null,
  done_reps     int  not null default 0,  -- the count Brodie reached (session event at rest/done)
  closed_by     text not null default 'target' check (closed_by in ('target', 'timeout', 'gesture', 'call_ended')),
  started_at    timestamptz,
  ended_at      timestamptz,
  -- Per-set inputs to the color rule (shared/muscles.json), stored so the web never recomputes them:
  fault_rate    real,                 -- reps with >= 1 fault / done_reps
  completion    real,                 -- min(1, done_reps / planned_reps)
  dropoff       real,                 -- max(0, fault rate of the later half - fault rate of the earlier half)
  quality       real,                 -- 0..1
  unique (session_id, set_number)
);

create table if not exists reps (
  id            uuid primary key default gen_random_uuid(),
  set_id        uuid not null references sets(id) on delete cascade,
  rep_number    int  not null,        -- 1-based within the set (Brodie rep event 'n')
  exercise      text not null,
  t_offset_s    real not null,        -- seconds since the session started (when Brodie counted it)
  confidence    real,                 -- Brodie rep.confidence.agree, 0..1; null if unknown
  -- Brodie fault labels decided while this rep was in progress (since the previous rep), e.g.
  -- ["squats - knees over toes"]. Empty array = clean rep. The spoken text is in src/rtcoach/cues.json.
  faults        jsonb not null default '[]'::jsonb,
  unique (set_id, rep_number)
);

create table if not exists muscle_scores (
  id            uuid primary key default gen_random_uuid(),
  session_id    uuid not null references sessions(id) on delete cascade,
  muscle        text not null,        -- one of shared/muscles.json "muscles"
  score         real not null,        -- 0..1, weighted mean of the quality of the sets that worked it
  color         text not null check (color in ('green', 'yellow', 'red')),
  -- why: {"sets": [{"set_number": 1, "exercise": "squats", "role": "primary", "quality": 0.86}], "top_fault": "squats - knees over toes"}
  detail        jsonb not null default '{}'::jsonb,
  unique (session_id, muscle)
  -- Muscles with no row were not trained: draw them grey.
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
