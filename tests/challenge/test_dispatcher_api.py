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
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending restart identity cascade")
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


def commit_ev(call_id, key="k-commit"):
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


def test_claim_window_mode_rejects_walkin(db, conn):
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    app = create_app(PgStore(db), FakeOutbox(), clock=lambda: T0, flags=Flags(CALLER_ID_SOURCE="claim_window"), token="tok")
    j = TestClient(app).post("/calls/start", headers=H, json={"call_id": "c-walk", "line_id": "line-1"}).json()
    assert j["decision"] == "reject" and j["reason"] == "not_your_turn"


def test_end_and_commit_idempotent_with_postcall(env):
    c, conn, st, ob, now = env
    uid, handle = mkuser(conn)
    assert start(c, "c-1", handle).json()["decision"] == "accept"
    now["t"] = T0 + timedelta(seconds=200)
    end = {"kind": "call_ended", "call_id": "c-1", "idem_key": "k-end", "at": now["t"].isoformat(),
           "payload": {"ended_at": (T0 + timedelta(seconds=195)).isoformat(),
                       "count_end_at": (T0 + timedelta(seconds=180)).isoformat(), "rep_count": 2}}
    assert c.post("/calls/event", headers=H, json={"kind": "call_started", "call_id": "c-1", "idem_key": "k0"}).json() == {"ok": True}
    assert c.post("/calls/event", headers=H, json=end).json()["ok"] is True
    assert c.post("/calls/event", headers=H, json=end).json()["ok"] is True
    r1 = c.post("/calls/event", headers=H, json=commit_ev("c-1")).json()
    r2 = c.post("/calls/event", headers=H, json=commit_ev("c-1")).json()
    assert r1["ok"] and r1["already"] is False and r2["ok"] and r2["already"] is True
    assert conn.execute("select count(*) from sessions where client_id=%s", (uid,)).fetchone()[0] == 1
    assert conn.execute("select count(*) from reps r join sets s on s.id=r.set_id join sessions x on x.id=s.session_id"
                        " where x.client_id=%s", (uid,)).fetchone()[0] == 3
    pc = [s for s in ob.sent if s["template"] == "post_call"]
    assert len(pc) == 1 and pc[0]["user_id"] == uid and pc[0]["proactive"] is True
    ctx = pc[0]["ctx"]
    assert ctx["valid_reps"] == 2 and ctx["rejected_reps"] == 1 and ctx["result_url"].endswith("/r/c-1")
    assert "media_url" not in ctx  # CARD_DELIVERY=link
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
        c.post("/calls/event", headers=H, json={"kind": "call_ended", "call_id": cid, "idem_key": "e" + cid,
               "payload": {"ended_at": (T0 + timedelta(seconds=195)).isoformat(), "count_end_at": None, "rep_count": 1}})
        st.rpc("ch_tick", {"p_now": T0 + timedelta(seconds=600)})
        if cid == "rb":
            ev = commit_ev(cid)
            ev["payload"]["reps"] = [rep(1, ev["at"])]
            c.post("/calls/event", headers=H, json=ev)
            now["t"] = T0 + timedelta(seconds=700)
    # a overtakes b with more reps
    ev = commit_ev("ra", "k-ra")
    r = c.post("/calls/event", headers=H, json=ev).json()
    assert r["ok"] and r["postcall"]["post_call"] is True
    drops = [s for s in ob.sent if s["template"] == "rank_drop"]
    assert [d["user_id"] for d in drops] == [b] and drops[0]["ctx"]["old_rank"] == 1 and drops[0]["ctx"]["rank"] == 2
    # replay: DB already consumed deltas; no new drop texts
    c.post("/calls/event", headers=H, json=ev)
    assert len([s for s in ob.sent if s["template"] == "rank_drop"]) == 1


def test_attachment_mode_sets_media_url(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    ob = FakeOutbox()
    app = create_app(PgStore(db), ob, clock=lambda: T0, token="tok",
                     flags=Flags(CALLER_ID_SOURCE="chert_meta", CARD_DELIVERY="attachment"))
    c = TestClient(app)
    uid, handle = mkuser(conn)
    assert start(c, "c-att", handle).json()["decision"] == "accept"
    assert c.post("/calls/event", headers=H, json=commit_ev("c-att")).json()["ok"]
    assert ob.sent[0]["ctx"]["media_url"].endswith("/r/c-att/card.png")


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
