"""Migration 20261026_challenge_team_no_cap.sql: clients.is_team exempts a team member from daily_call_cap.

Every gate that used to compare ch_calls_today against the configured cap now compares it against
ch_calls_cap_for(user). The honest count must not change: an uncapped user is never refused for being at cap, and
their calls still count and still score. Queue ORDER is a separate concern - 20261026_challenge_team_priority.sql
(D-43) later put team members at the front of the line; test_db_team_priority.py owns that.
"""
from __future__ import annotations

from datetime import timedelta

# Same fixture and helpers as the call-lifecycle suite. `st` is a pytest fixture: it has to be in this module's
# namespace for the tests below to request it, so the "unused import" is load-bearing.
from tests.challenge.test_db_calls import (  # noqa: F401
    T0, et, full_call, join, line, set_cfg, st, start, tick, user,
)

CAP = 5


def uncap(conn, uid, on=True):
    """Mark a team / test account (the flag 20261025_challenge_metrics.sql added; ch_admin_set_team toggles it)."""
    conn.execute("update clients set is_team=%s where id=%s", (on, uid))


def status(st, uid, now):
    return st.rpc("ch_user_status", {"p_user_id": uid, "p_now": now})


def web_me(st, uid, now):
    return st.rpc("ch_web_me", {"p_user_id": uid, "p_now": now})


def burn_cap(st, handle, at, n=CAP):
    """n counted walk-in calls, returning when the line is idle again."""
    for _ in range(n):
        _, at = full_call(st, handle, at, dur_s=60)
    return at


# ---------------------------------------------------------------- the cap itself


def test_uncapped_user_calls_past_the_cap_while_the_count_stays_honest(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, at)).fetchone()[0] == CAP
    # the gate is gone, but the count is not rewritten
    _, r = start(st, h, at)
    assert (r["decision"], r["reason"]) == ("accept", "ok")
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, at)).fetchone()[0] == CAP


def test_default_user_is_still_capped(st, conn):
    uid, h = user(conn)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    assert conn.execute("select is_team from clients where id=%s", (uid,)).fetchone()[0] is False
    r = start(st, h, at)[1]
    assert (r["decision"], r["reason"], r["cue"]) == ("reject", "at_cap", "at_cap")


def test_recapping_a_team_member_restores_the_gate(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    _, at = full_call(st, h, at, dur_s=60)       # 6th call, over the cap, accepted and counted
    assert conn.execute("select ch_calls_today(%s, %s)", (uid, at)).fetchone()[0] == CAP + 1
    uncap(conn, uid, False)
    assert start(st, h, at)[1]["reason"] == "at_cap"


def test_cap_for_follows_the_configured_cap_for_everyone_else(st, conn):
    uid, _ = user(conn)
    other, _ = user(conn)
    uncap(conn, uid)
    set_cfg(conn, "daily_call_cap", 3)
    assert conn.execute("select ch_calls_cap_for(%s)", (other,)).fetchone()[0] == 3
    assert conn.execute("select ch_calls_cap_for(%s)", (uid,)).fetchone()[0] == 2147483647
    # an unknown user is not uncapped
    assert conn.execute("select ch_calls_uncapped(gen_random_uuid())").fetchone()[0] is False


# ---------------------------------------------------------------- queue


def test_queue_join_past_the_cap(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    j = join(st, uid, at)
    assert (j["ok"], j["reason"], j["uncapped"]) == (True, "ok", True)
    # calls_left keeps reporting against the configured cap, so existing readers still get a small number
    assert (j["calls_today"], j["calls_left"]) == (CAP, 0)


def test_queue_join_still_reports_at_cap_for_everyone_else(st, conn):
    uid, h = user(conn)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    j = join(st, uid, at)
    assert (j["ok"], j["reason"], j["uncapped"], j["calls_left"]) == (False, "at_cap", False, 0)


def test_tick_keeps_and_pops_an_uncapped_waiting_entry(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    assert join(st, uid, at)["ok"] is True
    t = tick(st, at + timedelta(seconds=1))
    assert [c["user_id"] for c in t["claims"]] == [str(uid)]
    assert conn.execute("select status from queue where user_id=%s order by id desc limit 1",
                        (uid,)).fetchone()[0] == "notified"
    assert line(conn)[:2] == ("claimed", uid)


def test_tick_still_expires_a_capped_waiting_entry(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    assert join(st, uid, at)["ok"] is True
    uncap(conn, uid, False)          # recapped while waiting: step 2 expires the entry
    t = tick(st, at + timedelta(seconds=1))
    assert t["claims"] == []
    assert conn.execute("select status from queue where user_id=%s order by id desc limit 1",
                        (uid,)).fetchone()[0] == "expired"


def test_the_honest_count_is_what_the_fair_key_still_uses(st, conn):
    """ch_calls_today is left honest, so the fair key is unaffected: among equals, fewer calls today wins.

    (Team members themselves are popped first since D-43 - see test_db_team_priority.py.)
    """
    busy, bh = user(conn)
    rookie, _ = user(conn)
    at = burn_cap(st, bh, et(2026, 10, 13, 12, 0), n=3)
    assert join(st, busy, at)["ok"] is True                            # 3 calls today, in line first
    assert join(st, rookie, at + timedelta(seconds=1))["ok"] is True   # 0 calls today, in line second
    t = tick(st, at + timedelta(seconds=2))
    assert [c["user_id"] for c in t["claims"]] == [str(rookie)]         # the lower tier still wins


# ---------------------------------------------------------------- reporting


def test_user_status_and_web_me_expose_uncapped(st, conn):
    uid, h = user(conn)
    other, _ = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    s = status(st, uid, at)
    assert (s["uncapped"], s["calls_today"], s["calls_left"]) == (True, CAP, 0)
    assert status(st, other, at)["uncapped"] is False
    me = web_me(st, uid, at)
    assert (me["uncapped"], me["daily_call_cap"]) == (True, CAP)
    assert me["line_open"] is True      # past the cap, the line is still open to a team member


def test_web_me_line_open_false_for_a_capped_user(st, conn):
    uid, h = user(conn)
    burn_cap(st, h, et(2026, 10, 13, 12, 0))
    at = et(2026, 10, 13, 20, 0)
    assert web_me(st, uid, at)["line_open"] is False


# ---------------------------------------------------------------- admin RPC


def test_admin_set_team_lifts_the_cap_and_audits(st, conn):
    """No new admin RPC: the existing audited ch_admin_set_team is what uncaps someone."""
    uid, h = user(conn)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0))
    assert start(st, h, at)[1]["reason"] == "at_cap"
    r = st.rpc("ch_admin_set_team", {"p_user_id": uid, "p_team": True, "p_reason": "team member: line testing",
                                     "p_actor": "admin@example.com", "p_now": T0})
    assert (r["ok"], r["changed"]) == (True, True)
    assert start(st, h, at)[1]["decision"] == "accept"
    row = conn.execute("select actor, action, before, after, reason from audit_log where action='set_team'").fetchall()
    assert row == [("admin@example.com", "set_team", {"is_team": False}, {"is_team": True},
                    "team member: line testing")]


def test_admin_set_team_false_puts_the_cap_back(st, conn):
    uid, h = user(conn)
    uncap(conn, uid)
    at = burn_cap(st, h, et(2026, 10, 13, 12, 0), n=CAP + 2)
    st.rpc("ch_admin_set_team", {"p_user_id": uid, "p_team": False, "p_reason": "done testing",
                                 "p_actor": "admin@example.com", "p_now": T0})
    assert start(st, h, at)[1]["reason"] == "at_cap"
