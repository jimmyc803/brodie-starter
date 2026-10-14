"""Migration 20261026_challenge_team_priority.sql: clients.is_team puts a team member at the front of the line.

Pop order is now (priority desc, calls_today asc, entered_at asc, id asc): a team member is popped before every
non-team member however long the others have waited, team members are still fair among themselves, and nothing
changes for anyone else. Priority is applied at pop time only - a connected call or a live claim is never taken
away. ch_queue_position and the admin queue view read the same single ordering, so reported places stay truthful.
"""
from __future__ import annotations

from datetime import timedelta

# Same fixture and helpers as the call-lifecycle suite (`st` has to be in this namespace to be requestable).
from tests.challenge.test_db_calls import (  # noqa: F401
    add_line2, et, full_call, join, line, st, start, tick, user,
)

CAP = 5


def team(conn, uid, on=True):
    conn.execute("update clients set is_team=%s where id=%s", (on, uid))


def waiting(conn, now):
    """(user_id, pos) for every waiting entry, in pop order."""
    return conn.execute("select user_id, pos from ch_calls_waiting(%s) order by pos", (now,)).fetchall()


def pos(st, uid, now):
    return st.rpc("ch_queue_position", {"p_user_id": uid, "p_now": now})


def burn(st, handle, at, n):
    for _ in range(n):
        _, at = full_call(st, handle, at, dur_s=60)
    return at


# ---------------------------------------------------------------- pop order


def test_team_member_is_popped_before_a_longer_waiting_rookie(st, conn):
    rookie, _ = user(conn)
    tm, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, rookie, at)["ok"] is True                    # 0 calls today, in line first
    assert join(st, tm, at + timedelta(seconds=30))["ok"] is True
    assert [r[0] for r in waiting(conn, at + timedelta(minutes=1))] == [tm, rookie]
    t = tick(st, at + timedelta(minutes=1))
    assert [c["user_id"] for c in t["claims"]] == [str(tm)]
    assert line(conn)[:2] == ("claimed", tm)


def test_team_member_with_more_calls_today_still_goes_first(st, conn):
    """Priority outranks the fair key: this is the whole point of the migration."""
    tm, th = user(conn)
    team(conn, tm)
    rookie, _ = user(conn)
    at = burn(st, th, et(2026, 10, 13, 12, 0), 3)
    assert join(st, rookie, at)["ok"] is True                    # 0 calls today
    assert join(st, tm, at + timedelta(seconds=1))["ok"] is True  # 3 calls today
    t = tick(st, at + timedelta(seconds=2))
    assert [c["user_id"] for c in t["claims"]] == [str(tm)]


def test_team_member_past_the_cap_is_popped_first(st, conn):
    """Priority and the D-38 exemption compose: over the cap and still first."""
    tm, th = user(conn)
    team(conn, tm)
    rookie, _ = user(conn)
    at = burn(st, th, et(2026, 10, 13, 12, 0), CAP)
    assert join(st, rookie, at)["ok"] is True
    j = join(st, tm, at + timedelta(seconds=1))
    assert (j["ok"], j["uncapped"]) == (True, True)
    t = tick(st, at + timedelta(seconds=2))
    assert [c["user_id"] for c in t["claims"]] == [str(tm)]


def test_team_members_are_fair_among_themselves(st, conn):
    busy, bh = user(conn)
    fresh, _ = user(conn)
    team(conn, busy)
    team(conn, fresh)
    at = burn(st, bh, et(2026, 10, 13, 12, 0), 2)
    assert join(st, busy, at)["ok"] is True                      # 2 calls today, in line first
    assert join(st, fresh, at + timedelta(seconds=1))["ok"] is True   # 0 calls today
    assert [r[0] for r in waiting(conn, at + timedelta(seconds=2))] == [fresh, busy]


def test_two_team_members_with_the_same_count_keep_entered_at_order(st, conn):
    a, _ = user(conn)
    b, _ = user(conn)
    team(conn, a)
    team(conn, b)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, a, at)["ok"] is True
    assert join(st, b, at + timedelta(seconds=5))["ok"] is True
    assert [r[0] for r in waiting(conn, at + timedelta(seconds=6))] == [a, b]


def test_order_among_non_team_users_is_unchanged(st, conn):
    busy, bh = user(conn)
    late, _ = user(conn)
    at = burn(st, bh, et(2026, 10, 13, 12, 0), 2)
    assert join(st, busy, at)["ok"] is True
    assert join(st, late, at + timedelta(seconds=1))["ok"] is True
    assert [r[0] for r in waiting(conn, at + timedelta(seconds=2))] == [late, busy]   # fewest calls today wins


def test_several_team_members_are_popped_before_anyone_else(st, conn):
    rookie, _ = user(conn)
    a, _ = user(conn)
    b, _ = user(conn)
    team(conn, a)
    team(conn, b)
    at = et(2026, 10, 13, 12, 0)
    add_line2(conn)
    assert join(st, rookie, at)["ok"] is True
    assert join(st, a, at + timedelta(seconds=1))["ok"] is True
    assert join(st, b, at + timedelta(seconds=2))["ok"] is True
    t = tick(st, at + timedelta(seconds=3))
    assert sorted(c["user_id"] for c in t["claims"]) == sorted([str(a), str(b)])      # both lines go to the team
    assert [r[0] for r in waiting(conn, at + timedelta(seconds=4))] == [rookie]


def test_unmarking_a_team_member_drops_them_back_into_fair_order(st, conn):
    tm, _ = user(conn)
    rookie, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, rookie, at)["ok"] is True
    assert join(st, tm, at + timedelta(seconds=1))["ok"] is True
    team(conn, tm, False)
    assert [r[0] for r in waiting(conn, at + timedelta(seconds=2))] == [rookie, tm]
    t = tick(st, at + timedelta(seconds=3))
    assert [c["user_id"] for c in t["claims"]] == [str(rookie)]


def test_priority_flag_reads_the_one_team_flag(st, conn):
    uid, _ = user(conn)
    assert conn.execute("select ch_calls_priority(%s)", (uid,)).fetchone()[0] is False
    team(conn, uid)
    assert conn.execute("select ch_calls_priority(%s)", (uid,)).fetchone()[0] is True
    assert conn.execute("select ch_calls_priority(gen_random_uuid())").fetchone()[0] is False


# ---------------------------------------------------------------- no preemption


def test_a_team_member_does_not_take_a_live_claim_away(st, conn):
    rookie, _ = user(conn)
    tm, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, rookie, at)["ok"] is True
    tick(st, at + timedelta(seconds=1))                          # rookie is notified, line claimed
    assert line(conn)[:2] == ("claimed", rookie)
    assert join(st, tm, at + timedelta(seconds=2))["ok"] is True
    tick(st, at + timedelta(seconds=3))
    assert line(conn)[:2] == ("claimed", rookie)                 # still theirs
    assert conn.execute("select status from queue where user_id=%s order by id desc limit 1",
                        (tm,)).fetchone()[0] == "waiting"


def test_a_team_member_does_not_cut_into_a_connected_call(st, conn):
    _walkin, wh = user(conn)
    tm, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    _, r = start(st, wh, at)
    assert r["decision"] == "accept"
    assert join(st, tm, at + timedelta(seconds=5))["ok"] is True
    t = tick(st, at + timedelta(seconds=10))
    assert t["claims"] == []                                     # the line is in_call; nobody is popped
    assert line(conn)[0] == "in_call"


# ---------------------------------------------------------------- reported places


def test_queue_position_follows_the_same_ordering(st, conn):
    rookie, _ = user(conn)
    tm, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, rookie, at)["ok"] is True
    assert pos(st, rookie, at) == 1
    assert join(st, tm, at + timedelta(seconds=1))["ok"] is True
    now = at + timedelta(seconds=2)
    assert (pos(st, tm, now), pos(st, rookie, now)) == (1, 2)    # the rookie honestly moved back
    assert pos(st, user(conn)[0], now) is None                   # not in line


def test_user_status_and_queue_view_agree_with_the_pop_order(st, conn):
    rookie, _ = user(conn)
    tm, _ = user(conn)
    team(conn, tm)
    at = et(2026, 10, 13, 12, 0)
    assert join(st, rookie, at)["ok"] is True
    assert join(st, tm, at + timedelta(seconds=1))["ok"] is True
    now = at + timedelta(seconds=2)
    assert st.rpc("ch_user_status", {"p_user_id": tm, "p_now": now})["queue_position"] == 1
    assert st.rpc("ch_user_status", {"p_user_id": rookie, "p_now": now})["queue_position"] == 2
    view = st.rpc("ch_queue_view", {"p_now": now})
    assert [(e["user_id"], e["position"]) for e in view["queue"]] == [(str(tm), 1), (str(rookie), 2)]
