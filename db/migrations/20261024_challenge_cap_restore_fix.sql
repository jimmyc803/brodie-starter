-- Cap fix for 20261023_challenge_call_reliability (found by scripts/simulate.py after deploy; DB regression test in
-- tests/challenge/test_db_call_reliability.py). A holder with 4 counted calls whose call timed out (exempt -> turn
-- restored) could use the restored turn (5th counted call) and then the reconciler's late ch_commit_reps for the
-- timed-out call recomputed counted_toward_cap without any cap check: 6 counted calls in one ET day (cap 5).
-- Rule: a call whose turn was restored (calls.turn_restored_at set) is also cap-exempt when the user's OTHER accepted
-- calls of that ET day - counted, or still in progress (no ended_at yet) - already reach daily_call_cap. Otherwise a
-- late commit still re-counts it (unchanged: test_timeout_then_late_commit_recounts). Its reps score either way.
-- In-progress calls are included so a late commit can never take the slot of the call the user is on right now.
-- Every path that sets counted_toward_cap (ch_call_end, ch_commit_reps incl. the late-commit reconcile, the ch_tick
-- in_call timeout) runs ch_calls_settle afterwards under the line + user locks, and settle clears counted_toward_cap
-- for an exempt call, so only the exemption predicate changes. Idempotent (create or replace; no config writes).
begin;

create or replace function ch_calls_cap_exempt(p_call calls) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce(p_call.decision = 'accept' and p_call.ended_at is not null and (
           (p_call.via_claim
            and extract(epoch from p_call.ended_at - p_call.connected_at) < ch_calls_cfg_int('min_counted_call_s', 30)
            and case when p_call.session_id is not null
                     then not exists (select 1 from sets s join reps r on r.set_id = s.id
                                       where s.session_id = p_call.session_id
                                         and r.valid is true and coalesce(r.points, 0) > 0)
                     else coalesce(p_call.rep_count, 0) = 0 end)
           or (p_call.end_reason = 'timeout' and p_call.session_id is null and coalesce(p_call.rep_count, 0) = 0)
           or (p_call.turn_restored_at is not null
               and (select count(*) from calls o
                     where o.user_id = p_call.user_id and o.id <> p_call.id and o.decision = 'accept'
                       and (o.counted_toward_cap or o.ended_at is null)
                       and o.connected_at >= ch_et_day_start(ch_et_day(p_call.connected_at))
                       and o.connected_at <  ch_et_day_start(ch_et_day(p_call.connected_at) + 1))
                   >= ch_calls_cfg_int('daily_call_cap', 5))),
         false)
$$;

revoke all on function ch_calls_cap_exempt(calls) from public, anon, authenticated;
grant execute on function ch_calls_cap_exempt(calls) to service_role;

commit;
