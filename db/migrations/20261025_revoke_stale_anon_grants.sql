-- Defense in depth before launch: these tables have RLS on with no anon/authenticated policies (so access was already
-- denied), but still carried table grants to anon/authenticated. Revoke them. Server code uses service_role.
-- call_lines/line_claims come from the coach app's migrations and may not exist in every database. Idempotent.
do $$
declare t text;
begin
  foreach t in array array['call_lines', 'line_claims', 'schema_migrations'] loop
    if to_regclass('public.' || t) is not null then
      execute format('revoke all on table public.%I from anon, authenticated', t);
    end if;
  end loop;
end $$;
