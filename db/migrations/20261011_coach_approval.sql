-- Coach applications: web sign-ups start 'pending' (sandbox only) until the team approves them in /admin.
-- Existing (seeded / hand-made) coaches are approved.
alter table public.coaches add column if not exists status text not null default 'approved';
alter table public.coaches drop constraint if exists coaches_status_check;
alter table public.coaches add constraint coaches_status_check check (status in ('pending', 'approved', 'rejected'));
alter table public.coaches add column if not exists application jsonb;      -- answers from /start (where they coach, clients, links)
alter table public.coaches add column if not exists reviewed_at timestamptz;
create index if not exists coaches_status_idx on public.coaches (status, created_at desc);
