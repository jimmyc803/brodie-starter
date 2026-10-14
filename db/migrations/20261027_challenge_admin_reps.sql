-- Admin score adjustments move valid reps too (owner request 2026-10-13; D-44 in docs/challenge/DECISIONS.md).
--
-- Before this migration, `ch_admin_adjust` only wrote score_adjustments.points, and valid_reps was defined purely
-- as "reps the judge accepted on non-void calls". So an admin correction moved a competitor's points but left
-- their rep count alone: the leaderboard card showed, say, 45 pts next to 52 reps, and the board's VALID REPS
-- tile (the sum of leaderboard_public.valid_reps) stayed at the pre-correction number. One rep is one point in
-- this competition, so that split reads as a bug to everyone looking at the board.
--
-- Now score_adjustments carries a reps delta as well:
--   score_adjustments.reps      new column, default 0.
--   ch_admin_adjust(..., p_reps) p_reps null (the shape every existing caller uses) means "move reps with points",
--                               i.e. reps := points. Pass p_reps explicitly to decouple them - including 0, for a
--                               points-only correction (a power-hour multiplier fix, a prize bonus).
--   ch_valid_reps / ch_user_stats.valid_reps  = judged valid reps + Σ score_adjustments.reps, floored at 0 so a
--                               large negative correction can never show a negative rep count.
--
-- Everything the public sees reads one of those two (leaderboard_public, user_public, ch_user_status, ch_web_me,
-- the texted stats), so they all move together. Deliberately NOT changed:
--   user_daily_public / ch_metrics  per-DAY and per-CALL reporting stays judged-reps-only. An adjustment belongs
--                                   to a user, not to a call, and attributing it to the ET day it was typed would
--                                   make "reps on 2026-10-14" disagree with that day's calls.
--
-- Backfill: existing adjustment rows get reps = points (the default rule above, applied retroactively), which is
-- what "the rep counts on the board right now are wrong" means. Guarded on the column being new, so re-applying
-- this migration never re-backfills a row an admin has since set deliberately.
begin;

-- ---------------------------------------------------------------- column + backfill
do $$
declare v_new bool := not exists (
  select 1 from information_schema.columns
  where table_schema = 'public' and table_name = 'score_adjustments' and column_name = 'reps');
begin
  if v_new then
    alter table score_adjustments add column reps int not null default 0;
    update score_adjustments set reps = points;
  end if;
end $$;

-- ---------------------------------------------------------------- totals
create or replace function ch_valid_reps(p_user_id uuid) returns int
language sql stable security definer set search_path = public as $$
  select greatest(
    coalesce((select sum(valid_reps) from ch_call_stats
              where user_id = p_user_id and decision = 'accept' and not void), 0)
  + coalesce((select sum(reps) from score_adjustments where user_id = p_user_id), 0), 0)::int
$$;

create or replace view ch_user_stats as
with cs as (
  select * from ch_call_stats where decision = 'accept' and user_id is not null
), call_agg as (
  select user_id,
         sum(points) filter (where not void) as points,
         sum(valid_reps) filter (where not void) as valid_reps,
         max(last_point_at) filter (where not void) as last_point_at,
         array_agg(distinct date_et) filter (where counted_toward_cap and not void and valid_reps > 0) as streak_days,
         (array_agg(call_id order by points desc, connected_at asc) filter (where not void))[1] as best_call_id,
         max(points) filter (where not void) as best_call_points
  from cs group by user_id
), adj_agg as (
  select user_id, sum(points) as points, sum(reps) as reps, max(at) as last_at from score_adjustments group by user_id
), base as (
  select cl.id as user_id, cl.display_name, cl.joined_at, cl.banned_at, cl.opted_out_at,
         (coalesce(ca.points, 0) + coalesce(aa.points, 0))::int as points,
         greatest(coalesce(ca.valid_reps, 0) + coalesce(aa.reps, 0), 0)::int as valid_reps,
         case when ca.last_point_at is null then aa.last_at
              when aa.last_at is null then ca.last_point_at
              else greatest(ca.last_point_at, aa.last_at) end as reached_at,
         coalesce(ca.streak_days, '{}'::date[]) as streak_days,
         ca.best_call_id, ca.best_call_points,
         (cl.banned_at is null and cl.display_name is not null) as listed
  from clients cl
  left join call_agg ca on ca.user_id = cl.id
  left join adj_agg aa on aa.user_id = cl.id
  where cl.joined_at is not null
)
select b.user_id, b.display_name, b.joined_at, b.banned_at, b.opted_out_at, b.points, b.valid_reps, b.reached_at,
       b.streak_days, b.best_call_id, b.best_call_points,
       ch_level_for_points(b.points, (select value from competition_config where key = 'avatar_level_thresholds')) as avatar_level,
       b.listed,
       case when b.listed then row_number() over (
         partition by b.listed order by b.points desc, b.reached_at asc nulls last, b.joined_at asc, b.user_id) end::int as rank
from base b;

-- ---------------------------------------------------------------- admin RPC
-- The 4-arg signature is dropped rather than kept alongside: two functions differing only by a defaulted argument
-- are ambiguous to a named-argument call, which is how PostgREST (and every caller here) invokes it.
drop function if exists ch_admin_adjust(uuid, int, text, text);

create or replace function ch_admin_adjust(p_user_id uuid, p_points int, p_reason text, p_actor text,
                                           p_reps int default null) returns jsonb
language plpgsql volatile security definer set search_path = public as $$
declare
  v_reps   int := coalesce(p_reps, p_points);
  v_before int;
  v_after  int;
  v_rbefore int;
  v_rafter  int;
  v_id     bigint;
begin
  perform ch_require_reason(p_reason, p_actor);
  if p_points is null or (p_points = 0 and v_reps = 0) then
    raise exception 'points_required' using errcode = '22023';
  end if;
  perform 1 from clients where id = p_user_id and joined_at is not null for update;
  if not found then
    return jsonb_build_object('ok', false, 'reason', 'not_found');
  end if;
  v_before  := ch_user_points(p_user_id);
  v_rbefore := ch_valid_reps(p_user_id);
  insert into score_adjustments (user_id, points, reps, reason, actor) values (p_user_id, p_points, v_reps, p_reason, p_actor)
    returning id into v_id;
  v_after  := ch_user_points(p_user_id);
  v_rafter := ch_valid_reps(p_user_id);
  insert into audit_log (actor, action, target, before, after, reason)
    values (p_actor, 'adjust_points', p_user_id::text,
            jsonb_build_object('points', v_before, 'valid_reps', v_rbefore),
            jsonb_build_object('points', v_after, 'valid_reps', v_rafter, 'delta', p_points, 'reps_delta', v_reps,
                               'adjustment_id', v_id),
            p_reason);
  return jsonb_build_object('ok', true, 'adjustment_id', v_id, 'points', v_after, 'valid_reps', v_rafter,
                            'reps_delta', v_reps);
end;
$$;

revoke all on function ch_admin_adjust(uuid, int, text, text, int) from public, anon, authenticated;
grant execute on function ch_admin_adjust(uuid, int, text, text, int) to service_role;

commit;
