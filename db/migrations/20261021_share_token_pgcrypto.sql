-- On Supabase pgcrypto lives in the `extensions` schema, so the unqualified gen_random_bytes() in new_share_token()
-- failed whenever it ran under a security definer function's `search_path = public` (ch_web_join, ch_join_confirm):
-- every new competitor insert errored with 42883. Qualify the call; safe to run twice.
create or replace function public.new_share_token() returns text
language sql volatile set search_path = public, extensions as $$
  select translate(encode(extensions.gen_random_bytes(24), 'base64'), '+/', '-_')
$$;
