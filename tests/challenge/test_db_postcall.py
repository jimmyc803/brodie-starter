"""Migration 20261014_challenge_postcall.sql: ch_postcall / ch_postcall_pending / ch_event_run."""
from __future__ import annotations

from datetime import timedelta

import pytest
from psycopg.types.json import Jsonb

from challenge.store import PgStore, StoreError
from tests.challenge.test_dispatcher_api import T0, commit_ev, mkuser, rep

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def st(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    conn.execute("update competition_config set value=%s where key='rank_drop_min'", (Jsonb(1),))
    return PgStore(db)


def call(st, cid, handle, reps, at=T0):
    r = st.rpc("ch_call_start", {"p_call_id": cid, "p_line_id": "line-1", "p_handle": handle,
                                 "p_mode": "chert_meta", "p_now": at})
    assert r["decision"] == "accept", r
    ev = commit_ev(cid)
    ev["payload"]["reps"] = reps
    assert st.rpc("ch_commit_reps", {"p_call_id": cid, "p_payload": ev["payload"], "p_now": at + timedelta(seconds=200)})["ok"]
    for k in (900, 1200):
        st.rpc("ch_tick", {"p_now": at + timedelta(seconds=k)})


def test_postcall_idempotent_and_pending(st, conn):
    uid, h = mkuser(conn)
    call(st, "pc1", h, [rep(1, T0.isoformat()), rep(2, T0.isoformat(), valid=False)])
    now = T0 + timedelta(seconds=300)
    assert [p["call_id"] for p in st.rpc("ch_postcall_pending", {"p_now": now, "p_limit": 10})] == ["pc1"]
    assert st.rpc("ch_postcall_pending", {"p_now": T0 + timedelta(seconds=201), "p_limit": 10}) == []  # < 30s old
    r = st.rpc("ch_postcall", {"p_call_id": "pc1", "p_now": now})
    assert r["ok"] and r["already"] is False
    n = conn.execute("select count(*) from messages").fetchone()[0]
    assert st.rpc("ch_postcall", {"p_call_id": "pc1", "p_now": now}) == {"ok": True, "already": True}
    assert conn.execute("select count(*) from messages").fetchone()[0] == n
    assert st.rpc("ch_postcall_pending", {"p_now": now, "p_limit": 10}) == []
    ctx = conn.execute("select ctx from messages where template='post_call'").fetchone()[0]
    assert ctx["valid_reps"] == 1 and ctx["rejected_reps"] == 1


def test_postcall_rollback_does_not_consume_rank_drop(st, conn):
    a, ha = mkuser(conn)
    b, hb = mkuser(conn)
    call(st, "r1", hb, [rep(1, T0.isoformat())])
    st.rpc("ch_postcall", {"p_call_id": "r1", "p_now": T0 + timedelta(seconds=1300)})  # b is #1 in rank_state
    call(st, "r2", ha, [rep(1, T0.isoformat()), rep(2, T0.isoformat())], at=T0 + timedelta(seconds=1500))
    # a has no handle -> post_call enqueue fails -> whole txn (incl. rank_state update) rolls back
    saved = conn.execute("select handle, kind, linked_via from client_handles where client_id=%s", (a,)).fetchall()
    conn.execute("delete from client_handles where client_id=%s", (a,))
    with pytest.raises(StoreError):
        st.rpc("ch_postcall", {"p_call_id": "r2", "p_now": T0 + timedelta(seconds=2000)})
    assert conn.execute("select postcall_done_at from calls where id='r2'").fetchone()[0] is None
    for hd, k, lv in saved:
        conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,%s,%s)", (hd, a, k, lv))
    assert st.rpc("ch_postcall", {"p_call_id": "r2", "p_now": T0 + timedelta(seconds=2010)})["rank_drops"] == 1
    keys = [r[0] for r in conn.execute("select dedupe_key from messages where template='rank_drop'")]
    assert keys == [f"rank_drop:{b}:r2"]


def test_postcall_rejects_uncommitted_and_unknown(st, conn):
    uid, h = mkuser(conn)
    assert st.rpc("ch_postcall", {"p_call_id": "nope", "p_now": T0})["ok"] is False
    st.rpc("ch_call_start", {"p_call_id": "nc", "p_line_id": "line-1", "p_handle": h, "p_mode": "chert_meta", "p_now": T0})
    assert st.rpc("ch_postcall", {"p_call_id": "nc", "p_now": T0}) == {"ok": False, "reason": "not_committed"}


def test_event_run_dedupes(st, conn):
    uid, h = mkuser(conn)
    st.rpc("ch_call_start", {"p_call_id": "ev1", "p_line_id": "line-1", "p_handle": h, "p_mode": "chert_meta", "p_now": T0})
    args = {"p_idem_key": "k1", "p_call_id": "ev1", "p_kind": "call_ended", "p_now": T0 + timedelta(seconds=200),
            "p_payload": {"ended_at": (T0 + timedelta(seconds=195)).isoformat(), "count_end_at": None, "rep_count": 1}}
    a = st.rpc("ch_event_run", args)
    b = st.rpc("ch_event_run", args)
    assert a["duplicate"] is False and b["duplicate"] is True and b["result"] == a["result"]
    with pytest.raises(StoreError):
        st.rpc("ch_event_run", {**args, "p_idem_key": "k2", "p_kind": "bogus"})
