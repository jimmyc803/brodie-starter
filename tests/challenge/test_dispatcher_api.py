"""Dispatcher API vs a real migrated Postgres (PgStore) with a fake Outbox."""
from __future__ import annotations

import itertools
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from challenge.dispatcher.app import create_app
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.postcall import StoreOutbox
from challenge.store import PgStore

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=ET)
H = {"X-Brodie-Token": "tok"}
_seq = itertools.count(1)


class FakeOutbox:
    def __init__(self):
        self.sent = []

    def enqueue(self, **kw):
        dup = any(s["dedupe_key"] == kw["dedupe_key"] for s in self.sent)
        if not dup:
            self.sent.append(kw)
        return {"duplicate": dup}


@pytest.fixture
def env(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    now = {"t": T0}
    ob = FakeOutbox()
    st = PgStore(db)
    app = create_app(st, ob, clock=lambda: now["t"], flags=Flags(CALLER_ID_SOURCE="chert_meta"), token="tok")
    return TestClient(app), conn, st, ob, now


def mkuser(conn, name=None):
    n = next(_seq)
    name = name or f"disp_{n}"
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = conn.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,%s,%s,%s) returning id",
                       (coach, name, name, T0 - timedelta(days=1))).fetchone()[0]
    handle = f"+1666{n:07d}"
    conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')",
                 (handle, uid))
    return str(uid), handle


def start(c, call_id, handle):
    return c.post("/calls/start", headers=H, json={"call_id": call_id, "line_id": "line-1", "handle": handle})


def rep(n, at, valid=True):
    return {"n": n, "t": float(n), "at": at, "valid": valid, "reject_reasons": [] if valid else ["shallow"],
            "faults": [], "in_challenge": False, "min_elbow_deg_l": 80.5, "classifier_labels": ["pushups - correct"],
            "persons_in_frame": 1, "torso_ok": True, "side": "left"}


def msgs(conn, template):
    return conn.execute("select user_id::text, ctx, media_url, dedupe_key from messages where template=%s order by id",
                        (template,)).fetchall()


def commit_ev(call_id, key=None):
    key = key or f"{call_id}:reps_committed"      # /calls/event requires idem_key == <call_id>:<kind>
    at = (T0 + timedelta(seconds=10)).isoformat()
    return {"kind": "reps_committed", "call_id": call_id, "idem_key": key, "at": at, "payload": {
        "started_at": T0.isoformat(), "ended_at": (T0 + timedelta(seconds=195)).isoformat(),
        "liveness_result": "pass", "judge_version": "j1",
        "reps": [rep(1, at), rep(2, at), rep(3, at, valid=False)]}}


def test_auth_required(env):
    c, *_ = env
    body = {"call_id": "a", "line_id": "line-1", "handle": "x"}
    assert c.post("/calls/start", json=body).status_code == 401
    assert c.post("/calls/start", headers={"X-Brodie-Token": "nope"}, json=body).status_code == 401
    assert c.post("/calls/event", json={"kind": "call_started", "call_id": "a", "idem_key": "i"}).status_code == 401


def test_rate_limit(db):
    app = create_app(PgStore(db), FakeOutbox(), clock=lambda: T0, flags=Flags(), token="tok", rate_per_min=3)
    c = TestClient(app)
    codes = [c.post("/calls/start", json={"call_id": "a", "line_id": "l"}).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_start_accept_and_reject(env):
    c, conn, *_ = env
    uid, handle = mkuser(conn)
    r = start(c, "c-acc", handle)
    assert r.status_code == 200
    j = r.json()
    assert j["decision"] == "accept" and j["user_id"] == uid and j["reason"] == "ok"
    assert conn.execute("select state from line_state where line_id='line-1'").fetchone()[0] == "in_call"
    assert start(c, "c-acc", handle).json() == j  # idempotent replay
    j2 = start(c, "c-unreg", "+19990000000").json()
    assert j2["decision"] == "reject" and j2["reason"] == "not_registered" and j2["cue"] == "not_signed_up"
    assert j2["user_id"] is None


def test_calling_busy_line_auto_queues_and_texts(env):
    c, conn, st, ob, now = env
    a, ha = mkuser(conn)
    b, hb = mkuser(conn)
    assert start(c, "c-a", ha).json()["decision"] == "accept"
    j = start(c, "c-b", hb).json()
    assert j["decision"] == "reject" and j["reason"] == "queued" and j["cue"] == "queued" and j["position"] == 1
    assert conn.execute("select user_id::text, status from queue").fetchall() == [(b, "waiting")]
    assert conn.execute("select reject_reason from calls where id='c-b'").fetchone()[0] == "not_your_turn"
    [sent] = ob.sent
    assert sent["user_id"] == b and sent["template"] == "call_queued" and sent["dedupe_key"] == "call:c-b"
    assert sent["ctx"]["position"] == 1 and sent["ctx"]["eta"] and sent["proactive"] is False
    assert start(c, "c-b", hb).json() == j  # replay: same answer, still one queue entry, text deduped
    assert conn.execute("select count(*) from queue").fetchone()[0] == 1 and len(ob.sent) == 1
    j2 = start(c, "c-b2", hb).json()  # calling again while waiting keeps the spot
    assert j2["reason"] == "queued" and j2["position"] == 1
    assert conn.execute("select count(*) from queue").fetchone()[0] == 1


def test_unregistered_caller_is_texted_join(env):
    c, conn, st, ob, now = env
    j = start(c, "c-new", "+19995550000").json()
    assert j["reason"] == "not_registered" and j["cue"] == "not_signed_up"
    assert [(s["handle"], s["template"], s["dedupe_key"]) for s in ob.sent] == [
        ("+19995550000", "not_registered", "call:c-new")]


def test_at_cap_caller_is_not_queued(env):
    c, conn, st, ob, now = env
    old = conn.execute("select value from competition_config where key = 'daily_call_cap'").fetchone()
    conn.execute("insert into competition_config (key, value) values ('daily_call_cap', '0')"
                 " on conflict (key) do update set value = excluded.value")
    try:
        _, h = mkuser(conn)
        j = start(c, "c-cap", h).json()
        assert j["reason"] == "at_cap" and ob.sent == []
        assert conn.execute("select count(*) from queue").fetchone()[0] == 0
    finally:
        if old:
            conn.execute("update competition_config set value = %s where key = 'daily_call_cap'", (Jsonb(old[0]),))
        else:
            conn.execute("delete from competition_config where key = 'daily_call_cap'")


def test_claim_window_mode_rejects_walkin(db, conn):
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    app = create_app(PgStore(db), FakeOutbox(), clock=lambda: T0, flags=Flags(CALLER_ID_SOURCE="claim_window"), token="tok")
    ob = FakeOutbox()
    app = create_app(PgStore(db), ob, clock=lambda: T0, flags=Flags(CALLER_ID_SOURCE="claim_window"), token="tok")
    j = TestClient(app).post("/calls/start", headers=H, json={"call_id": "c-walk", "line_id": "line-1"}).json()
    assert j["decision"] == "reject" and j["reason"] == "not_your_turn" and ob.sent == []


def test_end_and_commit_idempotent_with_postcall(env):
    c, conn, st, ob, now = env
    uid, handle = mkuser(conn)
    assert start(c, "c-1", handle).json()["decision"] == "accept"
    now["t"] = T0 + timedelta(seconds=200)
    end = {"kind": "call_ended", "call_id": "c-1", "idem_key": "c-1:call_ended", "at": now["t"].isoformat(),
           "payload": {"ended_at": (T0 + timedelta(seconds=195)).isoformat(),
                       "count_end_at": (T0 + timedelta(seconds=180)).isoformat(), "rep_count": 2}}
    assert c.post("/calls/event", headers=H, json={"kind": "call_started", "call_id": "c-1", "idem_key": "c-1:call_started"}).json() == {"ok": True, "duplicate": False}
    assert c.post("/calls/event", headers=H, json=end).json()["ok"] is True
    assert c.post("/calls/event", headers=H, json=end).json()["ok"] is True
    r1 = c.post("/calls/event", headers=H, json=commit_ev("c-1")).json()
    r2 = c.post("/calls/event", headers=H, json=commit_ev("c-1")).json()
    assert r1["ok"] and r1["already"] is False and r2["ok"] and r2["duplicate"] is True
    assert conn.execute("select count(*) from sessions where client_id=%s", (uid,)).fetchone()[0] == 1
    assert conn.execute("select count(*) from reps r join sets s on s.id=r.set_id join sessions x on x.id=s.session_id"
                        " where x.client_id=%s", (uid,)).fetchone()[0] == 3
    pc = msgs(conn, "post_call")
    assert len(pc) == 1 and pc[0][0] == uid and pc[0][3] == "post_call:c-1"
    assert r1["postcall"]["ok"] and r2["postcall"]["already"] is True
    assert conn.execute("select postcall_done_at is not null from calls where id='c-1'").fetchone()[0]
    ctx = pc[0][1]
    assert ctx["valid_reps"] == 2 and ctx["rejected_reps"] == 1 and ctx["result_url"].endswith("/r/c-1")
    assert "media_url" not in ctx and pc[0][2] is None  # CARD_DELIVERY=link
    # rendering the stored ctx must work with the real template
    from challenge.messaging.templates import render
    assert "Work logged" in render("post_call", ctx, False)


def test_commit_unaccepted_call(env):
    c, *_ = env
    r = c.post("/calls/event", headers=H, json=commit_ev("never-started")).json()
    assert r["ok"] is False


def test_rank_drop_text_only_unthrottled(env):
    c, conn, st, ob, now = env
    a, ha = mkuser(conn)
    b, hb = mkuser(conn)
    # seed rank_state: b was #1, a was #2; now a leads after a's call -> b dropped? need >= rank_drop_min (2)
    conn.execute("update competition_config set value=%s where key='rank_drop_min'", (Jsonb(1),))
    st.rpc("ch_rank_deltas", {"p_now": T0})  # baseline (nobody ranked yet)
    for cid, h, uid in (("rb", hb, b), ("ra", ha, a)):
        assert start(c, cid, h).json()["decision"] == "accept"
        c.post("/calls/event", headers=H, json={"kind": "call_ended", "call_id": cid, "idem_key": f"{cid}:call_ended",
               "payload": {"ended_at": (T0 + timedelta(seconds=195)).isoformat(), "count_end_at": None, "rep_count": 1}})
        st.rpc("ch_tick", {"p_now": T0 + timedelta(seconds=600)})
        if cid == "rb":
            ev = commit_ev(cid)
            ev["payload"]["reps"] = [rep(1, ev["at"])]
            c.post("/calls/event", headers=H, json=ev)
            now["t"] = T0 + timedelta(seconds=700)
    # a overtakes b with more reps
    ev = commit_ev("ra")
    r = c.post("/calls/event", headers=H, json=ev).json()
    assert r["ok"] and r["postcall"]["ok"] is True
    drops = [d for d in msgs(conn, "rank_drop") if d[3].endswith(":ra")]  # a's call overtook b
    assert [d[0] for d in drops] == [b] and drops[0][1]["old_rank"] == 1 and drops[0][1]["rank"] == 2
    # replay (new idem_key): DB already consumed deltas; no new drop texts
    total = len(msgs(conn, "rank_drop"))
    st.rpc("ch_event_run", {"p_idem_key": "k-ra-2", "p_call_id": "ra", "p_kind": "reps_committed",
                            "p_payload": commit_ev("ra")["payload"], "p_now": now["t"]})
    assert len(msgs(conn, "rank_drop")) == total


def test_attachment_mode_sets_media_url(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    ob = FakeOutbox()
    app = create_app(PgStore(db), ob, clock=lambda: T0, token="tok",
                     flags=Flags(CALLER_ID_SOURCE="chert_meta", CARD_DELIVERY="attachment"))
    c = TestClient(app)
    uid, handle = mkuser(conn)
    assert start(c, "c-att", handle).json()["decision"] == "accept"
    assert c.post("/calls/event", headers=H, json=commit_ev("c-att")).json()["ok"]
    row = msgs(conn, "post_call")[0]
    assert row[1]["media_url"].endswith("/r/c-att/card.png") and row[2].endswith("/r/c-att/card.png")


def test_store_outbox_writes_messages(env):
    c, conn, st, ob, now = env
    uid, handle = mkuser(conn)
    so = StoreOutbox(st, lambda: T0)
    assert so.enqueue(user_id=uid, template="rank_drop", ctx={"x": 1}, dedupe_key="d1", proactive=True)["duplicate"] is False
    assert so.enqueue(user_id=uid, template="rank_drop", ctx={"x": 1}, dedupe_key="d1", proactive=True)["duplicate"] is True
    row = conn.execute("select handle, template, body, ctx from messages where dedupe_key='d1'").fetchone()
    assert row[0] == handle and row[1] == "rank_drop" and row[2] is None and row[3] == {"x": 1}


def test_health_shows_flags(env):
    c, *_ = env
    j = c.get("/health").json()
    assert j["ok"] and j["db"] and j["provider"] == "mock"
    assert j["flags"] == {"CALLER_ID_SOURCE": "chert_meta", "MESSAGING_PROVIDER": "mock", "HANGUP_MODE": "unverified",
                          "REVEAL_MODE": "audio_only", "CARD_DELIVERY": "link"}
    assert j["line_states"] and j["line_states"][0]["line_id"] == "line-1"
    assert "MESSAGING_PROVIDER" in j["fallbacks"]


def test_flags_from_env_and_invalid():
    f = Flags.from_env({"CARD_DELIVERY": "attachment", "LINE_OFFLINE_GAP_S": "60"})
    assert f.CARD_DELIVERY == "attachment" and f.LINE_OFFLINE_GAP_S == 60 and "CARD_DELIVERY" not in f.fallbacks()
    with pytest.raises(Exception):
        Flags.from_env({"HANGUP_MODE": "bogus"})


def test_duplicate_idem_key_returns_stored_result(env):
    c, conn, st, ob, now = env
    uid, handle = mkuser(conn)
    assert start(c, "c-idem", handle).json()["decision"] == "accept"
    ev = commit_ev("c-idem")
    r1 = c.post("/calls/event", headers=H, json=ev).json()
    assert r1["ok"] and r1["duplicate"] is False and r1["already"] is False
    r2 = c.post("/calls/event", headers=H, json=ev).json()
    assert r2["duplicate"] is True and r2["already"] is False  # stored result, effect not re-run
    assert conn.execute("select count(*) from ch_event_log where idem_key='c-idem:reps_committed'").fetchone()[0] == 1
    # a different key for the same commit runs the RPC again and sees it is already committed
    r3 = st.rpc("ch_event_run", {"p_idem_key": "other-key", "p_call_id": "c-idem", "p_kind": "reps_committed",
                                 "p_payload": ev["payload"], "p_now": now["t"]})
    assert r3["duplicate"] is False and r3["result"]["already"] is True


def test_failed_effect_is_not_logged_and_can_retry(env):
    c, conn, *_ = env
    uid, handle = mkuser(conn)
    ev = commit_ev("late")
    assert c.post("/calls/event", headers=H, json=ev).json()["ok"] is False
    assert conn.execute("select count(*) from ch_event_log where idem_key='late:reps_committed'").fetchone()[0] == 0
    assert start(c, "late", handle).json()["decision"] == "accept"
    assert c.post("/calls/event", headers=H, json=ev).json()["ok"] is True


def test_postcall_failure_leaves_pending(env):
    c, conn, st, ob, now = env
    uid, handle = mkuser(conn)
    assert start(c, "c-pend", handle).json()["decision"] == "accept"
    conn.execute("delete from client_handles where client_id=%s", (uid,))  # outbox cannot resolve a handle
    j = c.post("/calls/event", headers=H, json=commit_ev("c-pend")).json()
    assert j["ok"] is True and j["postcall"] == "pending"
    assert conn.execute("select count(*) from messages").fetchone()[0] == 0
    assert conn.execute("select postcall_done_at from calls where id='c-pend'").fetchone()[0] is None
    pend = st.rpc("ch_postcall_pending", {"p_now": T0 + timedelta(hours=1), "p_limit": 10})
    assert [p["call_id"] for p in pend] == ["c-pend"]


def test_line_offline_gap_flag_applied(db, conn):
    st = PgStore(db)
    before = st.rpc("ch_config_get", {})["line_offline_gap_s"]
    try:
        create_app(st, FakeOutbox(), clock=lambda: T0, token="tok", flags=Flags(LINE_OFFLINE_GAP_S=77))
        assert st.rpc("ch_config_get", {})["line_offline_gap_s"] == 77
    finally:
        st.rpc("ch_config_set", {"p_key": "line_offline_gap_s", "p_value": __import__("challenge.store", fromlist=["Json"]).Json(before),
                                 "p_actor": "test", "p_reason": "restore"})


def test_scope_per_min_overrides(monkeypatch):
    from challenge.dispatcher.ratelimit import RateLimiter, scope_per_min
    monkeypatch.delenv("DISPATCHER_RATE_PER_MIN_WEB", raising=False)
    assert scope_per_min("web") == 20_000          # /web arrives from Vercel's few egress IPs
    assert scope_per_min("worker") is None         # everything else uses the global limit
    monkeypatch.setenv("DISPATCHER_RATE_PER_MIN_WEB", "3")
    assert scope_per_min("web") == 3
    monkeypatch.setenv("DISPATCHER_RATE_PER_MIN_WEB", "0")
    with pytest.raises(ValueError):
        scope_per_min("web")
    lim = RateLimiter(2, now=lambda: 0.0)
    assert [lim.check("a", 4) for _ in range(5)] == [True] * 4 + [False]
    assert [lim.check("b") for _ in range(3)] == [True, True, False]


def test_reps_committed_response_forwards_authoritative_points(env):
    c, conn, *_ = env
    uid, handle = mkuser(conn)
    assert start(c, "c-pts", handle).json()["decision"] == "accept"
    r = c.post("/calls/event", headers=H, json=commit_ev("c-pts")).json()
    assert r["ok"] is True and r["points"] == conn.execute(
        "select points from ch_call_stats where call_id=%s", ("c-pts",)).fetchone()[0]


def test_idem_key_must_be_call_id_and_kind(env):
    """ch_event_run matches on idem_key alone: call A's key replayed for call B must not return A's stored result."""
    c, conn, *_ = env
    uid, handle = mkuser(conn)
    assert start(c, "c-a", handle).json()["decision"] == "accept"
    assert c.post("/calls/event", headers=H, json=commit_ev("c-a")).json()["points"] is not None
    stolen = commit_ev("c-b", "c-a:reps_committed")
    r = c.post("/calls/event", headers=H, json=stolen)
    assert r.status_code == 400 and "points" not in r.json()
    wrong_kind = dict(commit_ev("c-a"), kind="call_ended")
    assert c.post("/calls/event", headers=H, json=wrong_kind).status_code == 400
    assert c.post("/calls/event", headers=H, json=dict(commit_ev("c-b"), idem_key="")).status_code == 400
    assert conn.execute("select count(*) from ch_event_log where idem_key like 'c-b%'").fetchone()[0] == 0
