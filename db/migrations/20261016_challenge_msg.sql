-- Messaging fix round: inbound processed marker, cross-process outbound rate window, sent_at stamping.
begin;

alter table messages add column if not exists processed_at timestamptz;

create or replace function ch_inbound_done(p_id bigint, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  update messages set processed_at = coalesce(processed_at, p_now)
   where id = p_id and direction = 'in';
  return jsonb_build_object('ok', found);
end;
$$;

create or replace function ch_inbound_is_done(p_id bigint) returns boolean
language sql stable security definer set search_path = public as $$
  select coalesce((select processed_at is not null from messages where id = p_id and direction = 'in'), false);
$$;

create or replace function ch_outbox_sent_recent(p_now timestamptz, p_window_s int) returns int
language sql stable security definer set search_path = public as $$
  select count(*)::int from messages
   where direction = 'out' and status = 'sent'
     and sent_at > p_now - make_interval(secs => greatest(coalesce(p_window_s, 0), 0))
     and sent_at <= p_now;
$$;

-- Stamps sent_at from the dispatcher clock after ch_outbox_mark('sent'), so the rate window follows that clock.
-- (ch_outbox_mark keeps its signature: re-applying 20261013 must not create an ambiguous overload.)
create or replace function ch_outbox_stamp_sent(p_id bigint, p_sent_at timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
begin
  update messages set sent_at = p_sent_at where id = p_id and direction = 'out' and status = 'sent';
  return jsonb_build_object('ok', found);
end;
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in (
             'ch_inbound_done', 'ch_inbound_is_done', 'ch_outbox_sent_recent', 'ch_outbox_stamp_sent') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
