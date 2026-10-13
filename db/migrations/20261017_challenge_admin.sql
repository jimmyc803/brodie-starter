-- Task 25: dispatcher admin RPCs (POST /admin/broadcast, admin auth).
--   ch_admin_allowed(p_email)            -> {allowed bool}; case/whitespace-insensitive match on admin_allowlist.email.
--   ch_admin_broadcast(p_body, p_not_before, p_dry_run, p_actor, p_reason, p_now)
--        -> {recipients, digest, dry_run[, enqueued, duplicates]}. Recipients = registered (joined_at), non-banned,
--        opted-in clients with a handle (phone preferred, as ch_calls_notify). Apply enqueues one outbox row per recipient
--        via ch_outbox_enqueue (template 'broadcast', ctx {"_proactive": true} so the outbox re-checks opt-out/ban and
--        quiet hours at send time, body as given, dedupe_key 'broadcast:<sha256hex(body)>:<user_id>',
--        not_before = p_not_before) and writes ONE audit_log row ('broadcast'), all in one transaction. Re-applying the
--        same body enqueues nothing new. Reason + actor required for apply only.
begin;

create or replace function ch_admin_allowed(p_email text) returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object('allowed',
    coalesce(p_email is not null and btrim(p_email) <> '' and exists (
      select 1 from admin_allowlist a where lower(btrim(a.email)) = lower(btrim(p_email))), false))
$$;

create or replace function ch_broadcast_recipients()
returns table (user_id uuid, handle text)
language sql stable security definer set search_path = public as $$
  select cl.id, h.handle
  from clients cl
  cross join lateral (
    select ch.handle from client_handles ch
     where ch.client_id = cl.id
     order by (ch.kind = 'phone') desc nulls last, ch.created_at nulls last, ch.handle
     limit 1) h
  where cl.joined_at is not null and cl.banned_at is null and cl.opted_out_at is null
$$;

create or replace function ch_admin_broadcast(p_body text, p_not_before timestamptz, p_dry_run bool, p_actor text,
                                              p_reason text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_digest text;
  v_n      int := 0;
  v_new    int := 0;
  v_r      record;
  v_res    jsonb;
begin
  if p_body is null or btrim(p_body) = '' then
    raise exception 'body_required' using errcode = '22023';
  end if;
  v_digest := encode(sha256(convert_to(p_body, 'UTF8')), 'hex');
  if coalesce(p_dry_run, true) then
    select count(*) into v_n from ch_broadcast_recipients();
    return jsonb_build_object('recipients', v_n, 'digest', v_digest, 'dry_run', true);
  end if;
  perform ch_require_reason(p_reason, p_actor);
  for v_r in select r.user_id, r.handle from ch_broadcast_recipients() r order by r.user_id loop
    v_res := ch_outbox_enqueue(v_r.handle, v_r.user_id, 'broadcast', p_body, null,
                               'broadcast:' || v_digest || ':' || v_r.user_id::text,
                               coalesce(p_not_before, p_now), p_now, jsonb_build_object('_proactive', true));
    v_n := v_n + 1;
    if not coalesce((v_res ->> 'duplicate')::bool, false) then
      v_new := v_new + 1;
    end if;
  end loop;
  insert into audit_log (actor, action, target, before, after, reason, at)
    values (p_actor, 'broadcast', v_digest, null,
            jsonb_build_object('recipients', v_n, 'enqueued', v_new, 'duplicates', v_n - v_new, 'body', p_body,
                               'not_before', coalesce(p_not_before, p_now)),
            p_reason, coalesce(p_now, now()));
  return jsonb_build_object('recipients', v_n, 'digest', v_digest, 'dry_run', false, 'enqueued', v_new,
                            'duplicates', v_n - v_new);
end;
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public'
             and p.proname in ('ch_admin_allowed', 'ch_broadcast_recipients', 'ch_admin_broadcast') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
