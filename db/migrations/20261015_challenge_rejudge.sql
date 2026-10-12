-- Task 14: rejudge RPCs (scripts/rejudge.py, admin console rejudge dry-run/apply).
--   ch_rejudge_fetch(p_since, p_limit)  -> jsonb array, one object per stored rep that has metrics, over accepted,
--                                          non-void, committed calls with reps.at >= p_since (null = all), oldest first.
--                                          Keys: rep_id, call_id, user_id, display_name, rep_number, at, valid, reject_reasons,
--                                          multiplier, points, in_challenge, judge_version + the C2 metric columns.
--   ch_rejudge_apply(p_changes, p_judge_version, p_thresholds, p_actor, p_reason, p_now)
--        p_changes = [{rep_id, valid, reject_reasons, points}] -> updates those reps (valid/reject_reasons/points,
--        judge_version), writes ONE audit_log row ('rejudge') with the thresholds and per-user point deltas.
--        Reason + actor required. Idempotent: reps whose values already match are not counted as changed.
begin;

create or replace function ch_rejudge_fetch(p_since timestamptz, p_limit int default 100000) returns jsonb
language sql stable security definer set search_path = public as $$
  select coalesce(jsonb_agg(x order by x_at, x_rep), '[]'::jsonb)
  from (
    select jsonb_build_object(
             'rep_id', r.id, 'call_id', c.id, 'user_id', c.user_id, 'display_name', cl.display_name,
             'rep_number', r.rep_number, 'at', r.at, 'valid', coalesce(r.valid, false),
             'reject_reasons', to_jsonb(coalesce(r.reject_reasons, '{}'::text[])),
             'multiplier', coalesce(r.multiplier, 1), 'points', coalesce(r.points, 0),
             'in_challenge', coalesce(r.in_challenge, false), 'judge_version', r.judge_version,
             'min_elbow_deg_l', r.min_elbow_deg_l, 'min_elbow_deg_r', r.min_elbow_deg_r,
             'top_elbow_deg', r.top_elbow_deg, 'max_hip_line_dev_deg', r.max_hip_line_dev_deg,
             'min_knee_deg', r.min_knee_deg, 'knee_floor_contact', r.knee_floor_contact,
             'shoulder_wrist_drop', r.shoulder_wrist_drop, 'shoulder_elbow_gap', r.shoulder_elbow_gap,
             'min_keypoint_conf', r.min_keypoint_conf, 'frame_conf_frac', r.frame_conf_frac,
             'persons_in_frame', r.persons_in_frame, 'rep_duration_s', r.rep_duration_s, 'torso_ok', r.torso_ok,
             'side', r.side, 'classifier_labels', to_jsonb(coalesce(r.classifier_labels, '{}'::text[]))) as x,
           r.at as x_at, r.rep_number as x_rep
    from reps r
    join sets s on s.id = r.set_id
    join calls c on c.session_id = s.session_id
    join clients cl on cl.id = c.user_id
    where c.decision = 'accept' and not c.void and r.persons_in_frame is not null
      and (p_since is null or r.at >= p_since)
    order by r.at, r.rep_number
    limit greatest(coalesce(p_limit, 100000), 0)
  ) q
$$;

create or replace function ch_rejudge_apply(p_changes jsonb, p_judge_version text, p_thresholds jsonb, p_actor text,
                                            p_reason text, p_now timestamptz) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_changed int;
  v_users jsonb;
begin
  perform ch_require_reason(p_reason, p_actor);
  if p_changes is null or jsonb_typeof(p_changes) <> 'array' then
    raise exception 'changes_required' using errcode = '22023';
  end if;
  create temp table _rejudge_in on commit drop as
    select (e ->> 'rep_id')::uuid as rep_id, (e ->> 'valid')::bool as valid,
           coalesce(array(select jsonb_array_elements_text(e -> 'reject_reasons')), '{}'::text[]) as reasons,
           (e ->> 'points')::int as points
    from jsonb_array_elements(p_changes) e;
  -- per-user points delta, from the stored values before they are overwritten
  select coalesce(jsonb_object_agg(uid::text, jsonb_build_object('before', b, 'after', a)), '{}'::jsonb)
    into v_users
  from (select c.user_id as uid, sum(coalesce(r.points, 0))::int as b, sum(i.points)::int as a
          from _rejudge_in i
          join reps r on r.id = i.rep_id
          join sets s on s.id = r.set_id
          join calls c on c.session_id = s.session_id
         where r.valid is distinct from i.valid or r.reject_reasons is distinct from i.reasons
            or r.points is distinct from i.points
         group by c.user_id) q;
  update reps r
     set valid = i.valid, reject_reasons = i.reasons, points = i.points, judge_version = p_judge_version
    from _rejudge_in i
   where r.id = i.rep_id
     and (r.valid is distinct from i.valid or r.reject_reasons is distinct from i.reasons
          or r.points is distinct from i.points);
  get diagnostics v_changed = row_count;
  drop table _rejudge_in;
  insert into audit_log (actor, action, target, before, after, reason, at)
  values (p_actor, 'rejudge', p_judge_version,
          jsonb_build_object('users_points', (select coalesce(jsonb_object_agg(k, v -> 'before'), '{}'::jsonb)
                                                from jsonb_each(v_users) t(k, v))),
          jsonb_build_object('judge_version', p_judge_version, 'thresholds', p_thresholds,
                             'reps_submitted', jsonb_array_length(p_changes), 'reps_changed', v_changed,
                             'users_points', (select coalesce(jsonb_object_agg(k, v -> 'after'), '{}'::jsonb)
                                               from jsonb_each(v_users) t(k, v))),
          p_reason, coalesce(p_now, now()));
  return jsonb_build_object('ok', true, 'changed', v_changed, 'users', v_users);
end;
$$;

do $$
declare r record;
begin
  for r in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' and p.proname in ('ch_rejudge_fetch', 'ch_rejudge_apply') loop
    execute format('revoke all on function %s from public, anon, authenticated', r.sig);
    execute format('grant execute on function %s to service_role', r.sig);
  end loop;
end $$;

commit;
