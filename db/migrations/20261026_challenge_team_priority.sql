-- Team members get the front of the line (owner request 2026-10-13; D-43 in docs/challenge/DECISIONS.md).
--
-- Companion to 20261026_challenge_team_no_cap.sql (D-38, C7.t), which exempted `clients.is_team` from
-- daily_call_cap and deliberately left queue ORDER alone ("never refused for being at cap, but never jumps the
-- line either"). The owner then asked for the other half: a team member should also be popped first. D-38's
-- reasoning is hereby superseded for order only - the honest count is still what the rest of the system reads.
--
-- Same one flag, no new column and no new admin RPC: `clients.is_team` (audited `ch_admin_set_team`, one-click in
-- the admin console's users page) now means three things - excluded from growth metrics, exempt from the cap, and
-- first in the queue.
--
-- Order was duplicated in two places, both replaced here with ONE expression:
--   ch_calls_waiting(p_now)                 the pop order + the 1-based position every reader shows
--   ch_queue_position(p_user_id, p_now)     ch_user_status's queue_position (hand-rolled copy of the same order)
-- ch_queue_position now delegates to ch_calls_waiting, so the two can no longer drift.
--
-- New order: priority desc, then the old keys (calls_today asc, entered_at asc, id asc). So:
--   * a team member waiting is popped before every non-team member, however long they have waited;
--   * among team members the fair order still applies (fewest calls today first, then who got in line first);
--   * among everyone else nothing changes at all.
--
-- What this does NOT do (deliberate):
--   * No preemption. Priority is applied when an idle line pops someone; a call already connected, and a claim
--     already notified, are never taken away. A team member waits for the current call to end like anyone else.
--   * ch_calls_today / calls_left / the leaderboard are untouched: a team member's calls still count and score.
--   * Eligibility is untouched (banned / opted out / not joined / already on a line are still skipped), so a
--     team member cannot be popped onto two lines at once.
--   * Reported positions stay truthful: a waiting non-team member's `queue_position` and the admin console's
--     `position` both grow when a team member joins ahead of them, because both read this one ordering.
--
-- Idempotent: three `create or replace function` calls, no DDL on tables.
begin;

-- ---------------------------------------------------------------- queue priority
-- Popped first: a team / test account (clients.is_team, ch_admin_set_team). Same flag as ch_calls_uncapped, kept
-- as its own function so the ordering reads as priority rather than as something about the cap.
create or replace function ch_calls_priority(p_user_id uuid) returns bool
language sql stable security definer set search_path = public as $$
  select coalesce((select c.is_team from clients c where c.id = p_user_id), false)
$$;

-- Waiting entries in pop order (priority desc, calls_today asc, entered_at asc, id asc) with 1-based position.
create or replace function ch_calls_waiting(p_now timestamptz)
returns table (queue_id bigint, user_id uuid, entered_at timestamptz, calls_today int, pos int)
language sql stable security definer set search_path = public as $$
  select w.id, w.user_id, w.entered_at, w.ct,
         (row_number() over (order by w.prio desc, w.ct, w.entered_at, w.id))::int
  from (select q.id, q.user_id, q.entered_at, ch_calls_today(q.user_id, p_now) as ct,
               ch_calls_priority(q.user_id) as prio
        from queue q where q.status = 'waiting') w
$$;

-- ch_queue_position - one ordering: delegate to ch_calls_waiting instead of repeating the sort keys.
create or replace function ch_queue_position(p_user_id uuid, p_now timestamptz) returns int
language sql stable security definer set search_path = public as $$
  select w.pos from ch_calls_waiting(p_now) w where w.user_id = p_user_id
$$;

-- ---------------------------------------------------------------- grants (create or replace keeps the ACL of the
-- replaced functions; ch_calls_priority is new)
revoke all on function ch_calls_priority(uuid) from public, anon, authenticated;
grant execute on function ch_calls_priority(uuid) to service_role;

commit;
