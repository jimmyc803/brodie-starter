"""Task 24 fix round (CONTRACTS C7.s, migration 20261019_challenge_sim_fixes.sql)."""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from psycopg.types.json import Jsonb

from db.test.harness import connect

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 14, 12, 0, tzinfo=ET)
CLAIM_S = 90


def rpc(c, fn: str, **kw):
    params = {k: Jsonb(v) if isinstance(v, (dict, list)) else v for k, v in kw.items()}
    return c.execute(f"select {fn}({', '.join(f'{k} => %({k})s' for k in kw)})", params).fetchone()[0]


def cfg(c, key, value):
    c.execute("insert into competition_config (key, value, updated_by) values (%s, %s, 'test')"
              " on conflict (key) do update set value = excluded.value", (key, Jsonb(value)))


@pytest.fixture
def c(db):
    conn = connect(db)
    conn.execute("truncate clients, calls, messages, audit_log restart identity cascade")
    conn.execute("delete from line_state where line_id <> 'line-1'")
    conn.execute("delete from lines where id <> 'line-1'")
    conn.execute("update lines set active = true, facetime_handle = null")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, updated_at=now()")
    for k, v in {"competition_frozen": False, "window_start": "2026-10-12T20:00:00-04:00",
                 "window_end": "2026-10-18T23:59:59-04:00", "claim_window_s": CLAIM_S, "daily_call_cap": 5,
                 "brodie_number": None, "outbound_rate_per_min": 20}.items():
        cfg(conn, k, v)
    conn.execute("delete from competition_config where key = 'frozen_at'")
    try:
        yield conn
    finally:
        cfg(conn, "competition_frozen", False)
        conn.execute("delete from competition_config where key = 'frozen_at'")
        conn.close()


def user(c, i: int) -> str:
    coach = c.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = c.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s) returning id",
                    (coach, f"u{i}", f"user_{i}", T0 - timedelta(days=1))).fetchone()[0]
    c.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
              (f"+1666000{i:04d}", uid))
    return str(uid)


def msgs(c, template: str) -> list[tuple]:
    return c.execute("select dedupe_key, status, ctx from messages where template = %s order by id", (template,)).fetchall()


def qstatus(c, uid: str) -> list[str]:
    return [r[0] for r in c.execute("select status from queue where user_id = %s order by id", (uid,))]


# ---------------------------------------------------------------- freeze vs admin pause (P3 + bug b)

def test_admin_pause_keeps_queue_window_end_closes_it_without_missed_slot(c):
    a, b = user(c, 1), user(c, 2)
    assert rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)["ok"]
    assert rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=1))["ok"]
    assert rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=2))["claims"][0]["user_id"] == a
    cfg(c, "competition_frozen", True)  # admin "freeze early" / pause
    t = T0 + timedelta(seconds=2 + CLAIM_S + 1)
    r = rpc(c, "ch_tick", p_now=t)
    assert r["claims"] == [] and r["no_shows"] == []
    # the paused claim goes back to waiting (keeps its place), the waiting entry stays, nobody is told "text QUEUE"
    assert qstatus(c, a) == ["waiting"] and qstatus(c, b) == ["waiting"]
    assert msgs(c, "missed_slot") == []
    rpc(c, "ch_tick", p_now=t + timedelta(minutes=30))
    assert qstatus(c, a) == ["waiting"] and qstatus(c, b) == ["waiting"]
    cfg(c, "competition_frozen", False)
    r = rpc(c, "ch_tick", p_now=t + timedelta(minutes=31))
    assert [x["user_id"] for x in r["claims"]] == [a], "paused user lost their place"

    # window_end: the claim made just before it expires as 'expired' (no missed_slot); waiting entries close
    end = t + timedelta(minutes=31, seconds=30)
    cfg(c, "window_end", end.isoformat())
    rpc(c, "ch_tick", p_now=end)
    assert qstatus(c, b) == ["expired"]
    assert qstatus(c, a) == ["notified"]  # claim made 30 s before window_end is still live
    rpc(c, "ch_tick", p_now=end + timedelta(seconds=CLAIM_S))
    assert qstatus(c, a) == ["expired"]
    assert msgs(c, "missed_slot") == [], "missed_slot ('text QUEUE') sent after the freeze"
    assert c.execute("select state from line_state where line_id='line-1'").fetchone()[0] == "idle"


def test_claim_expiry_before_freeze_still_sends_missed_slot(c):
    a = user(c, 1)
    assert rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)["ok"]
    rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=1))
    r = rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=1 + CLAIM_S))
    assert len(r["no_shows"]) == 1 and qstatus(c, a) == ["no_show"]
    assert [m[0] for m in msgs(c, "missed_slot")] == [f"missed_slot:{r['no_shows'][0]['queue_id']}"]


# ---------------------------------------------------------------- youre_up names the line (bug a)

def test_youre_up_names_the_line(c):
    from challenge.messaging.templates import render

    cfg(c, "brodie_number", "+15550009999")
    a = user(c, 1)
    rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)
    rpc(c, "ch_tick", p_now=T0)
    ctx = msgs(c, "youre_up")[-1][2]
    assert ctx["line_handle"] == "+15550009999"  # one active line -> the public Brodie number
    assert "FaceTime +15550009999 now" in render("youre_up", ctx, False)

    # two lines: each line's own facetime_handle; never the shared brodie_number
    c.execute("insert into lines (id, chert_agent_name, active, facetime_handle) values ('line-2','brodie2',true,'+15550002222')")
    c.execute("insert into line_state (line_id, state, updated_at) values ('line-2','idle',now())")
    b, d = user(c, 2), user(c, 3)
    rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=5))
    rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=6))
    ctx = [m[2] for m in msgs(c, "youre_up") if m[2]["line_id"] == "line-2"][-1]
    assert ctx["line_handle"] == "+15550002222"
    rpc(c, "ch_queue_leave", p_user_id=a, p_reason="left", p_now=T0 + timedelta(seconds=7))
    rpc(c, "ch_queue_join", p_user_id=d, p_now=T0 + timedelta(seconds=8))
    rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=9))
    ctx = [m[2] for m in msgs(c, "youre_up") if m[2]["line_id"] == "line-1"][-1]
    assert ctx["line_handle"] == "brodie", "2 lines without facetime_handle must not both say the same number"


# ---------------------------------------------------------------- outbox: stale youre_up + bounded priority (P2)

def enqueue(c, key: str, template: str, due: datetime, ctx: dict | None = None, uid: str | None = None):
    return rpc(c, "ch_outbox_enqueue", p_handle="+16660000001", p_user_id=uid, p_template=template, p_body=None,
               p_media_url=None, p_dedupe_key=key, p_not_before=due, p_now=due, p_ctx=ctx or {})


def claim(c, now: datetime) -> list[str]:
    return [r["dedupe_key"] for r in rpc(c, "ch_outbox_claim", p_limit=1, p_now=now)]


def active_claim(c, uid: str, at: datetime) -> dict:
    """A queue row holding a live claim (notified, claim_expires_at = at + CLAIM_S) and its youre_up ctx."""
    until = at + timedelta(seconds=CLAIM_S)
    qid = c.execute("insert into queue (user_id, entered_at, notified_at, claim_expires_at, line_id, status)"
                    " values (%s,%s,%s,%s,'line-1','notified') returning id", (uid, at, at, until)).fetchone()[0]
    return {"queue_id": qid, "line_id": "line-1", "line_handle": "brodie", "claimed_until": until.isoformat(),
            "claim_window_s": CLAIM_S}


def test_obsolete_youre_up_is_suppressed_not_sent(c):
    a, b = user(c, 1), user(c, 2)
    rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)
    rpc(c, "ch_tick", p_now=T0)                     # a popped -> youre_up queued
    rpc(c, "ch_queue_leave", p_user_id=a, p_reason="left", p_now=T0 + timedelta(seconds=1))
    rpc(c, "ch_queue_join", p_user_id=b, p_now=T0 + timedelta(seconds=1))
    rpc(c, "ch_tick", p_now=T0 + timedelta(seconds=2))  # b popped
    assert claim(c, T0 + timedelta(seconds=3)) == [f"youre_up:{qstatus_id(c, b)}"]
    assert claim(c, T0 + timedelta(seconds=4)) == []
    rows = {k: (s, e) for k, s, e in c.execute("select dedupe_key, status, last_error from messages"
                                                " where template='youre_up'")}
    assert rows[f"youre_up:{qstatus_id(c, a)}"] == ("suppressed", "claim_inactive")
    # a youre_up still queued when its claim expires is suppressed too
    cid = active_claim(c, a, T0 + timedelta(seconds=10))
    enqueue(c, "late", "youre_up", T0 + timedelta(seconds=10), cid, a)
    assert claim(c, T0 + timedelta(seconds=10 + CLAIM_S)) == []
    assert c.execute("select status from messages where dedupe_key='late'").fetchone()[0] == "suppressed"
    # rows without a queue_id (legacy / hand-written) are not judged
    enqueue(c, "legacy", "youre_up", T0 + timedelta(seconds=200), {"claim_window_s": CLAIM_S})
    assert claim(c, T0 + timedelta(seconds=200)) == ["legacy"]


def qstatus_id(c, uid: str) -> int:
    return c.execute("select max(id) from queue where user_id = %s", (uid,)).fetchone()[0]


def test_youre_up_overtakes_fresh_bulk_but_not_old_rows(c):
    a = user(c, 1)
    enqueue(c, "bulk", "ph_start", T0, {"power_hour": "x"})
    enqueue(c, "up1", "youre_up", T0 + timedelta(seconds=10), active_claim(c, a, T0 + timedelta(seconds=10)), a)
    assert claim(c, T0 + timedelta(seconds=11)) == ["up1"]           # deadline T0+100 < bulk's T0+300
    c.execute("update queue set status = 'connected'")
    enqueue(c, "up2", "youre_up", T0 + timedelta(seconds=250), active_claim(c, a, T0 + timedelta(seconds=250)), a)
    assert claim(c, T0 + timedelta(seconds=251)) == ["bulk"]         # bulk (T0+300) now beats up2 (T0+340)
    assert claim(c, T0 + timedelta(seconds=252)) == ["up2"]


def test_youre_up_churn_cannot_starve_ordinary_texts(c):
    """LEAVE/QUEUE cycling: a fresh live youre_up every 2 s (30/min) against a 20/min sender. Strict youre_up
    priority would never send the ordinary row; earliest-deadline-first sends it within ~210 s of its due time."""
    users = [user(c, i) for i in range(1, 4)]
    enqueue(c, "status-reply", "ph_start", T0, {"power_hour": "x"})
    sent_at = None
    t, n = T0, 0
    while t < T0 + timedelta(minutes=10):
        if (t - T0).total_seconds() % 2 == 0:
            n += 1
            c.execute("update queue set status = 'left' where status = 'notified'")  # previous claimer LEAVEs
            enqueue(c, f"up{n}", "youre_up", t, active_claim(c, users[n % 3], t), users[n % 3])
        if (t - T0).total_seconds() % 3 == 0 and claim(c, t) == ["status-reply"]:
            sent_at = t
            break
        t += timedelta(seconds=1)
    assert sent_at is not None and sent_at - T0 <= timedelta(seconds=300), sent_at


# ---------------------------------------------------------------- line audit on opt-out / admin remove (bug c)

def line_audits(c) -> list[tuple]:
    return c.execute("select action, target, reason from audit_log where action like 'line:%%' order by id").fetchall()


@pytest.mark.parametrize("how", ["opt_out", "admin_remove"])
def test_freeing_a_claim_writes_the_line_audit_row(c, how):
    a = user(c, 1)
    rpc(c, "ch_queue_join", p_user_id=a, p_now=T0)
    rpc(c, "ch_tick", p_now=T0)
    v0 = c.execute("select version from line_state where line_id='line-1'").fetchone()[0]
    before = len(line_audits(c))
    if how == "opt_out":
        assert rpc(c, "ch_set_opt", p_user_id=a, p_opted_out=True, p_now=T0 + timedelta(seconds=5))["ok"]
    else:
        r = rpc(c, "ch_admin_queue_remove", p_queue_id=qstatus_id(c, a), p_reason="test", p_actor="admin@x")
        assert r["ok"] and r["lines_idled"] == ["line-1"]
    st, ver = c.execute("select state, version from line_state where line_id='line-1'").fetchone()
    assert st == "idle" and ver == v0 + 1
    new = line_audits(c)[before:]
    assert [(x[0], x[1]) for x in new] == [("line:claimed->idle", "line-1")]
    if how == "opt_out":
        at = c.execute("select at from audit_log where action='line:claimed->idle' order by id desc limit 1").fetchone()[0]
        assert at == T0 + timedelta(seconds=5)


# ---------------------------------------------------------------- ban with injected clock (bug d)

def test_admin_ban_uses_injected_clock_and_keeps_old_signature(c):
    a, b = user(c, 1), user(c, 2)
    at = T0 + timedelta(hours=3)
    assert rpc(c, "ch_admin_ban", p_user_id=a, p_reason="cheat", p_actor="admin@x", p_now=at)["ok"]
    assert c.execute("select banned_at from clients where id=%s", (a,)).fetchone()[0] == at
    assert c.execute("select at from audit_log where action='ban' and target=%s", (a,)).fetchone()[0] == at
    assert rpc(c, "ch_admin_unban", p_user_id=a, p_reason="appeal", p_actor="admin@x", p_now=at)["changed"]
    # the admin site's 3-arg call still works (wall clock)
    assert rpc(c, "ch_admin_ban", p_user_id=b, p_reason="cheat", p_actor="admin@x")["ok"]
    assert c.execute("select banned_at is not null from clients where id=%s", (b,)).fetchone()[0]
    with pytest.raises(Exception, match="p_now required"):
        rpc(c, "ch_admin_set_ban", p_user_id=b, p_ban=True, p_reason="x", p_actor="admin@x", p_now=None)


@pytest.mark.parametrize("fn", ["ch_admin_set_ban(uuid,bool,text,text,timestamptz)", "ch_admin_set_ban(uuid,bool,text,text)",
                                "ch_admin_ban(uuid,text,text,timestamptz)", "ch_admin_unban(uuid,text,text,timestamptz)",
                                "ch_set_opt(uuid,bool,timestamptz)", "ch_admin_queue_remove(bigint,text,text)",
                                "ch_outbox_claim(int,timestamptz)", "ch_tick(timestamptz)"])
def test_redefined_functions_service_role_only(c, fn):
    for role, ok in [("anon", False), ("authenticated", False), ("service_role", True)]:
        assert c.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn)).fetchone()[0] is ok, role
    assert c.execute("select prosecdef from pg_proc where oid = %s::regprocedure", (fn,)).fetchone()[0]
