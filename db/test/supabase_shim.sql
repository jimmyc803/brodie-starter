-- Minimal Supabase environment for local Postgres tests (db/test/harness.py). NOT for production.
-- Roles anon/authenticated/service_role, Supabase's default grants in schema public, auth.uid()/auth.jwt()/auth.users,
-- storage.buckets/objects (enough for 20261011_program_upload.sql), and the supabase_realtime publication.
-- Idempotent; roles are cluster-wide so they are created only once.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated nologin noinherit; end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin noinherit bypassrls;
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;

-- Supabase grants everything in public to the API roles by default; RLS + explicit revokes are the protection.
alter default privileges in schema public grant all on tables to anon, authenticated, service_role;
alter default privileges in schema public grant all on sequences to anon, authenticated, service_role;
alter default privileges in schema public grant all on functions to anon, authenticated, service_role;

create schema if not exists auth;
grant usage on schema auth to anon, authenticated, service_role;

create table if not exists auth.users (
  id         uuid primary key,
  email      text,
  phone      text,
  created_at timestamptz not null default now()
);

create or replace function auth.jwt() returns jsonb language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claims', true), ''), '{}')::jsonb
$$;

create or replace function auth.uid() returns uuid language sql stable as $$
  select nullif(coalesce(nullif(current_setting('request.jwt.claim.sub', true), ''), auth.jwt() ->> 'sub'), '')::uuid
$$;

create or replace function auth.role() returns text language sql stable as $$
  select coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), auth.jwt() ->> 'role')
$$;

grant execute on function auth.jwt(), auth.uid(), auth.role() to anon, authenticated, service_role;

create schema if not exists storage;
grant usage on schema storage to anon, authenticated, service_role;

create table if not exists storage.buckets (
  id                 text primary key,
  name               text not null,
  public             boolean default false,
  file_size_limit    bigint,
  allowed_mime_types text[],
  created_at         timestamptz default now()
);

create table if not exists storage.objects (
  id         uuid primary key default gen_random_uuid(),
  bucket_id  text references storage.buckets(id),
  name       text,
  owner      uuid,
  metadata   jsonb,
  created_at timestamptz default now()
);
alter table storage.objects enable row level security;

do $$
begin
  if not exists (select 1 from pg_publication where pubname = 'supabase_realtime') then
    create publication supabase_realtime;
  end if;
end $$;

-- Supabase installs extensions in schema `extensions` (not public), and API roles' search_path does not include it
-- for `set search_path = public` functions. Mirror that so an unqualified pgcrypto call fails here exactly as it
-- does live (gen_random_bytes in new_share_token broke every clients insert on 2026-10-13).
create schema if not exists extensions;
grant usage on schema extensions to anon, authenticated, service_role;
create extension if not exists pgcrypto with schema extensions;
-- Supabase's database default search_path includes `extensions` (so plain sessions and schema.sql see pgcrypto), but
-- `set search_path = public` RPCs do not. Cloned test databases don't inherit this setting, which is stricter: there
-- every pgcrypto call must be schema-qualified.
do $$ begin
  execute format('alter database %I set search_path = "$user", public, extensions', current_database());
end $$;
set search_path = "$user", public, extensions;
