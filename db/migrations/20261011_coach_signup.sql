-- Coach self-sign-up (web /start): who signed up and how to reach them. Apply after db/schema.sql.
alter table public.coaches add column if not exists email text;
alter table public.coaches add column if not exists instagram text;
alter table public.coaches add column if not exists signup_source text;   -- 'web' for /start sign-ups, null for seeded coaches
create index if not exists coaches_email_idx on public.coaches (lower(email));
