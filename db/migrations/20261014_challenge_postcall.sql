-- Task 20 fix round: atomic/durable post-call processing + idempotent event log.
begin;

alter table calls add column if not exists postcall_done_at timestamptz;

create table if not exists ch_event_log (
  idem_key   text primary key,
  call_id    text,
  kind       text not null,
  result     jsonb not null,
  created_at timestamptz not null default now()
);
alter table ch_event_log enable row level security;
revoke all on table ch_event_log from public, anon, authenticated;
grant select, insert, update, delete on table ch_event_log to service_role;

-- ---------------------------------------------------------------- ch_postcall
-- One transaction: post_call intent + unthrottled rank_drop intents + calls.postcall_done_at.
-- Lock order: line_state rows -> user advisory lock -> rows. Idempotent; a failure rolls everything back
-- (including rank_state), so a rank drop is never consumed without its intent being written.
create or replace function ch_postcall(p_call_id text, p_now timestamptz, p_card_delivery text default 'link')
returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_call   calls;
  v_site   text := coalesce(ch_cfg('site_url') #>> '{}', 'https://brodie-pushups.vercel.app');
  v_url    text;
  v_st     jsonb;
  v_stats  record;
  v_ctx    jsonb;
  v_drops  int := 0;
  d        record;
begin
  if p_now is null then
    raise exception 'ch_postcall: p_now required';
  end if;
  select * into v_call from calls where id = p_call_id;
  if not found or v_call.decision <> 'accept' or v_call.user_id is null then
    return jsonb_build_object('ok', false, 'reason', 'not_accepted');
  end if;
  if v_call.session_id is null then
    return jsonb_build_object('ok', false, 'reason', 'not_committed');
  end if;

  perform ch_calls_lock_lines();
  perform ch_calls_lock_user(v_call.user_id);
  select * into v_call from calls where id = p_call_id for update;
  if v_call.postcall_done_at is not null then
    return jsonb_build_object('ok', true, 'already', true);
  end if;

  select * into v_stats from ch_call_stats where call_id = p_call_id;
  v_st := ch_user_status(v_call.user_id, p_now);
  v_url := rtrim(v_site, '/') || '/r/' || p_call_id;
  v_ctx := jsonb_build_object(
    'valid_reps', v_stats.valid_reps, 'rejected_reps', v_stats.rejected_reps, 'points_earned', v_stats.points,
    'points', coalesce(v_st -> 'points', '0'::jsonb), 'rank', coalesce(v_st -> 'rank', '"-"'::jsonb),
    'streak', coalesce(v_st -> 'streak', '0'::jsonb), 'result_url', v_url, 'call_id', p_call_id);
  if p_card_delivery = 'attachment' then
    v_ctx := v_ctx || jsonb_build_object('media_url', v_url || '/card.png');
  end if;
  perform ch_outbox_enqueue(null, v_call.user_id, 'post_call', null,
                            case when p_card_delivery = 'attachment' then v_url || '/card.png' end,
                            'post_call:' || p_call_id, null, p_now, v_ctx);

  for d in select * from jsonb_to_recordset(ch_rank_deltas(p_now)) as x(
             user_id uuid, old_rank int, new_rank int, points int, ahead_display_name text, ahead_points int,
             throttled bool) loop
    continue when d.throttled;
    perform ch_outbox_enqueue(null, d.user_id, 'rank_drop', null, null,
                              'rank_drop:' || d.user_id || ':' || p_call_id, null, p_now,
                              jsonb_build_object('old_rank', d.old_rank, 'rank', d.new_rank,
                                                 'next_rank', d.new_rank - 1,
                                                 'points_gap', greatest(coalesce(d.ahead_points, 0) - coalesce(d.points, 0), 0),
                                                 'points', d.points, 'ahead_display_name', d.ahead_display_name));
    v_drops := v_drops + 1;
  end loop;

  update calls set postcall_done_at = p_now where id = p_call_id;
  return jsonb_build_object('ok', true, 'already', false, 'rank_drops', v_drops);
end;
$$;

-- Committed calls whose post-call work has not completed (sweeper input for the jobs loop).
create or replace function ch_postcall_pending(p_now timestamptz, p_limit int default 50) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(jsonb_build_object('call_id', id, 'user_id', user_id) order by committed_at), '[]'::jsonb)
  from (select id, user_id, committed_at from calls
         where decision = 'accept' and session_id is not null and postcall_done_at is null
           and committed_at < p_now - interval '30 seconds'
         order by committed_at limit greatest(p_limit, 0)) q
$$;

-- ---------------------------------------------------------------- ch_event_run
-- Effect + event-log row in ONE transaction. A duplicate idem_key returns the stored result without
-- re-running the effect. Only successful results are logged, so a failed attempt can be retried.
create or replace function ch_event_run(p_idem_key text, p_call_id text, p_kind text, p_payload jsonb,
                                        p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_prev   jsonb;
  v_res    jsonb;
begin
  if p_idem_key is null or p_idem_key = '' then
    raise exception 'ch_event_run: idem_key required';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('ch_event:' || p_idem_key, 0));
  select result into v_prev from ch_event_log where idem_key = p_idem_key;
  if found then
    return jsonb_build_object('result', v_prev, 'duplicate', true);
  end if;
  if p_kind = 'call_started' then
    v_res := jsonb_build_object('ok', true);
  elsif p_kind = 'call_ended' then
    v_res := ch_call_end(p_call_id, (p_payload ->> 'ended_at')::timestamptz,
                         (p_payload ->> 'count_end_at')::timestamptz, (p_payload ->> 'rep_count')::int, p_now);
  elsif p_kind = 'reps_committed' then
    v_res := ch_commit_reps(p_call_id, p_payload, p_now);
  else
    raise exception 'ch_event_run: bad kind %', p_kind;
  end if;
  if coalesce((v_res ->> 'ok')::bool, false) then
    insert into ch_event_log (idem_key, call_id, kind, result, created_at)
      values (p_idem_key, p_call_id, p_kind, v_res, p_now);
  end if;
  return jsonb_build_object('result', v_res, 'duplicate', false);
end;
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in ('ch_postcall', 'ch_postcall_pending', 'ch_event_run') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
