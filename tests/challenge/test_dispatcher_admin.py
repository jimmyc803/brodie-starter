"""Task 25: dispatcher admin API (broadcast / rejudge / raffle), /internal/alert and the shared rate limiter, vs PgStore."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from challenge.dispatcher.admin import STOP_HINT, raffle_index
from challenge.dispatcher.app import create_app
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.ratelimit import RateLimiter
from challenge.store import PgStore
from tests.challenge.test_dispatcher_api import FakeOutbox, mkuser, rep

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=ET)
ROOT = Path(__file__).resolve().parents[2]
ADMIN = "boss@example.com"
TOK = {"X-Brodie-Token": "tok"}


def hdr(email=ADMIN, reason=None):
    h = dict(TOK, **{"X-Admin-Email": email})
    if reason is not None:
        h["X-Admin-Reason"] = quote(reason)
    return h


def _load(name):
    spec = importlib.util.spec_from_file_location(f"t25_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(db, conn, monkeypatch):
    monkeypatch.delenv("ADMIN_ALERT_HANDLES", raising=False)
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log, admin_allowlist"
                 " restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    conn.execute("update competition_config set value='[]'::jsonb where key='team_alert_handles'")
    conn.execute("insert into admin_allowlist (email) values ('Boss@Example.com')")
    now = {"t": T0}
    st = PgStore(db)
    app = create_app(st, FakeOutbox(), clock=lambda: now["t"], flags=Flags(CALLER_ID_SOURCE="chert_meta"), token="tok")
    return TestClient(app), conn, st, now


def give_reps(c, conn, handle, n_valid, call_id, n_invalid=0):
    """One accepted call with n_valid valid reps (+ n_invalid rejected) committed through the worker API."""
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    r = c.post("/calls/start", headers=TOK, json={"call_id": call_id, "line_id": "line-1", "handle": handle}).json()
    assert r["decision"] == "accept", r
    at = (T0 + timedelta(seconds=10)).isoformat()
    reps = [rep(i + 1, at) for i in range(n_valid)] + [rep(n_valid + i + 1, at, valid=False) for i in range(n_invalid)]
    ev = {"kind": "reps_committed", "call_id": call_id, "idem_key": f"k-{call_id}", "at": at, "payload": {
        "started_at": T0.isoformat(), "ended_at": (T0 + timedelta(seconds=195)).isoformat(),
        "liveness_result": "pass", "judge_version": "j1", "reps": reps}}
    assert c.post("/calls/event", headers=TOK, json=ev).json()["ok"] is True


# ------------------------------------------------------------------ auth matrix

def test_admin_auth_matrix(env):
    c, conn, *_ = env
    body = {"body": "hi", "dry_run": False}
    assert c.post("/admin/broadcast", json=body).status_code == 401
    assert c.post("/admin/broadcast", headers=dict(hdr(reason="r"), **{"X-Brodie-Token": "nope"}), json=body).status_code == 401
    assert c.post("/admin/broadcast", headers=TOK, json=body).status_code == 403  # no email
    assert c.post("/admin/broadcast", headers=hdr("eve@example.com", "r"), json=body).status_code == 403
    for path, b in (("/admin/broadcast", body), ("/admin/rejudge", {"apply": True}), ("/admin/raffle", {"seed": "s"})):
        r = c.post(path, headers=hdr(), json=b)
        assert r.status_code == 400 and "Reason" in r.text, (path, r.text)
        assert c.post(path, headers=hdr(reason="   "), json=b).status_code == 400
    assert conn.execute("select count(*) from messages").fetchone()[0] == 0
    assert conn.execute("select count(*) from audit_log").fetchone()[0] == 0
    # read-only variants need no reason; email match is case-insensitive
    assert c.post("/admin/broadcast", headers=hdr(" BOSS@example.COM "), json={"body": "hi", "dry_run": True}).status_code == 200
    assert c.post("/admin/rejudge", headers=hdr(), json={"apply": False}).status_code == 200
    assert c.post("/admin/raffle", headers=hdr(), json={"seed": "s", "dry_run": True}).status_code == 200
    assert c.post("/admin/raffle", headers=hdr(reason="draw day"), json={"seed": "s"}).status_code == 200
    # allowlist is checked in the DB on every request
    conn.execute("delete from admin_allowlist")
    assert c.post("/admin/rejudge", headers=hdr(), json={"apply": False}).status_code == 403


# ------------------------------------------------------------------ broadcast

def _people(conn):
    a, _ = mkuser(conn)
    b, _ = mkuser(conn)
    out, _ = mkuser(conn)
    ban, _ = mkuser(conn)
    conn.execute("update clients set opted_out_at=%s where id=%s", (T0, out))
    conn.execute("update clients set banned_at=%s, ban_reason='x' where id=%s", (T0, ban))
    return {a, b}


def test_broadcast_dry_run_then_idempotent_apply(env):
    c, conn, *_ = env
    expected = _people(conn)
    d = c.post("/admin/broadcast", headers=hdr(), json={"body": "  Big news!  ", "dry_run": True}).json()
    text = "Big news!" + STOP_HINT
    assert d["recipients"] == 2 and d["sample_body"] == text and d["preview"] == text
    assert conn.execute("select count(*) from messages").fetchone()[0] == 0

    r1 = c.post("/admin/broadcast", headers=hdr(reason="launch hype"), json={"body": "Big news!", "dry_run": False}).json()
    assert (r1["recipients"], r1["enqueued"], r1["duplicates"]) == (2, 2, 0)
    rows = conn.execute("select user_id::text, body, template, dedupe_key, not_before, status from messages").fetchall()
    sha = hashlib.sha256(text.encode()).hexdigest()
    assert {r[0] for r in rows} == expected
    assert all(r[1] == text and r[2] == "broadcast" and r[3] == f"broadcast:{sha}:{r[0]}" and r[5] == "queued"
               for r in rows)
    assert all(r[4] == T0 for r in rows)  # 10:00 ET: outside quiet hours, sendable now

    r2 = c.post("/admin/broadcast", headers=hdr(reason="again"), json={"body": "Big news!", "dry_run": False}).json()
    assert (r2["recipients"], r2["enqueued"], r2["duplicates"]) == (2, 0, 2)
    assert conn.execute("select count(*) from messages").fetchone()[0] == 2
    audit = conn.execute("select actor, action, target, reason, after from audit_log order by id").fetchall()
    assert [(a[0], a[1], a[2], a[3]) for a in audit] == [(ADMIN, "broadcast", sha, "launch hype"),
                                                         (ADMIN, "broadcast", sha, "again")]
    assert audit[0][4]["enqueued"] == 2 and audit[1][4]["duplicates"] == 2


def test_broadcast_respects_quiet_hours_and_validates(env):
    c, conn, _, now = env
    mkuser(conn)
    now["t"] = datetime(2026, 10, 13, 23, 30, tzinfo=ET)
    r = c.post("/admin/broadcast", headers=hdr(reason="late"), json={"body": "Night", "dry_run": False}).json()
    assert r["enqueued"] == 1
    nb = conn.execute("select not_before from messages").fetchone()[0]
    assert nb == datetime(2026, 10, 14, 9, 0, tzinfo=ET)
    assert c.post("/admin/broadcast", headers=hdr(), json={"dry_run": True}).status_code == 400
    assert c.post("/admin/broadcast", headers=hdr(), json={"body": "  ", "dry_run": True}).status_code == 400
    assert c.post("/admin/broadcast", headers=hdr(), json={"body": "x" * 1001, "dry_run": True}).status_code == 400
    assert c.post("/admin/broadcast", headers=hdr(), json={"template": "nope", "dry_run": True}).status_code == 400
    t = c.post("/admin/broadcast", headers=hdr(), json={"template": "ph_start", "dry_run": True}).json()
    assert t["sample_body"].startswith("Power hour is LIVE") and t["sample_body"].endswith(STOP_HINT)
    assert t["sample_body"].count("STOP to opt out") == 1


# ------------------------------------------------------------------ raffle

def test_raffle_threshold_deterministic_and_matches_cli(env, capsys):
    c, conn, st, _ = env
    u99, h99 = mkuser(conn)
    u100, h100 = mkuser(conn)
    u150, h150 = mkuser(conn)
    uban, hban = mkuser(conn)
    give_reps(c, conn, h99, 99, "r-99", n_invalid=5)
    give_reps(c, conn, h100, 100, "r-100")
    give_reps(c, conn, h150, 150, "r-150")
    give_reps(c, conn, hban, 120, "r-ban")
    conn.execute("update clients set banned_at=%s where id=%s", (T0, uban))

    seed = "powerball 2026-10-18: 04 12 33 41 59 / 07"
    d1 = c.post("/admin/raffle", headers=hdr(), json={"seed": seed, "dry_run": True}).json()
    ids = sorted([u100, u150])
    assert d1["eligible_count"] == 2 and d1["min_valid_reps"] == 100
    assert d1["eligible_hash"] == hashlib.sha256(",".join(ids).encode()).hexdigest()
    idx = int(hashlib.sha256((seed + ":" + ",".join(ids)).encode()).hexdigest(), 16) % 2
    assert d1["index"] == idx == raffle_index(seed, ids)
    assert d1["winner"]["user_id"] == ids[idx]
    names = dict(conn.execute("select id::text, display_name from clients").fetchall())
    assert d1["winner"]["display_name"] == names[ids[idx]]
    assert conn.execute("select count(*) from audit_log where action='raffle'").fetchone()[0] == 0

    d2 = c.post("/admin/raffle", headers=hdr(reason="final draw"), json={"seed": seed}).json()
    assert {k: d2[k] for k in d1 if k != "dry_run"} == {k: d1[k] for k in d1 if k != "dry_run"}
    a = conn.execute("select actor, target, reason, after from audit_log where action='raffle'").fetchall()
    assert len(a) == 1 and a[0][:3] == (ADMIN, seed, "final draw")
    assert a[0][3]["eligible_hash"] == d1["eligible_hash"] and a[0][3]["winner"]["user_id"] == ids[idx]
    assert a[0][3]["eligible_user_ids"] == ids and a[0][3]["seed"] == seed

    cli = _load("raffle")
    assert cli.main(["--seed", seed, "--dry-run"], store=st) == 0
    out = json.loads(capsys.readouterr().out)
    assert {k: out[k] for k in d1} == d1
    assert cli.main(["--seed", seed], store=st) == 2  # logged draw needs actor + reason
    assert cli.main(["--seed", seed, "--actor", "Ops@Example.com", "--reason", "cli draw"], store=st) == 0
    assert json.loads(capsys.readouterr().out)["winner"] == d1["winner"]
    assert conn.execute("select actor from audit_log where action='raffle' order by id desc limit 1").fetchone()[0] == "ops@example.com"

    # boundary: one more valid rep makes the 99 user eligible; a different seed is a different (still valid) draw
    give_reps(c, conn, h99, 1, "r-99b")
    d3 = c.post("/admin/raffle", headers=hdr(), json={"seed": seed, "dry_run": True}).json()
    assert d3["eligible_count"] == 3 and d3["winner"]["user_id"] in {u99, u100, u150}
    assert c.post("/admin/raffle", headers=hdr(reason="r"), json={"seed": "  "}).status_code == 400


def test_raffle_no_eligible(env):
    c, conn, *_ = env
    r = c.post("/admin/raffle", headers=hdr(reason="r"), json={"seed": "x"}).json()
    assert r["eligible_count"] == 0 and r["winner"] is None and r["index"] is None
    assert conn.execute("select count(*) from audit_log where action='raffle'").fetchone()[0] == 1


# ------------------------------------------------------------------ rejudge

def test_rejudge_dry_run_and_apply(env):
    c, conn, *_ = env
    _, h = mkuser(conn)
    give_reps(c, conn, h, 3, "rj-1")
    d = c.post("/admin/rejudge", headers=hdr(), json={"apply": False}).json()
    assert d["reps_loaded"] == 3 and d["apply"] is False and "applied" not in d
    before = conn.execute("select count(*) from reps where valid").fetchone()[0]
    assert c.post("/admin/rejudge", headers=hdr(), json={"thresholds": {"nope": 1}}).status_code == 400
    assert c.post("/admin/rejudge", headers=hdr(), json={"thresholds": {"min_rep_s": "fast"}}).status_code == 400
    assert c.post("/admin/rejudge", headers=hdr(), json={"since": "2026-10-13T00:00:00"}).status_code == 400
    assert (d["reps_changed"], d["valid_before"], d["valid_after"]) == (3, 3, 0)  # sparse metrics fail strict gates
    assert d["points_before"] == 3 and d["points_after"] == 0 and d["users"][0]["delta"] == -3
    assert conn.execute("select count(*) from reps where valid").fetchone()[0] == 3  # dry run writes nothing
    a = c.post("/admin/rejudge", headers=hdr(reason="new thresholds"),
               json={"thresholds": {"min_rep_s": 0.5}, "apply": True}).json()
    assert a["apply"] is True and a["applied"]["ok"] is True and a["thresholds"]["min_rep_s"] == 0.5
    assert a["applied"]["changed"] == a["reps_changed"]
    after = conn.execute("select count(*) from reps where valid").fetchone()[0]
    assert after == a["valid_after"] and before == a["valid_before"]
    assert a["reps_changed"] == 3 and a["applied"]["changed"] == 3 and after == 0
    assert conn.execute("select actor, reason from audit_log where action='rejudge'").fetchall() == [(ADMIN, "new thresholds")]
    again = c.post("/admin/rejudge", headers=hdr(), json={"thresholds": {"min_rep_s": 0.5}}).json()
    assert again["reps_changed"] == 0


# ------------------------------------------------------------------ /internal/alert

def test_internal_alert_dedupe_and_handles(env, monkeypatch):
    c, conn, _, now = env
    body = {"kind": "worker_down", "message": "no heartbeat"}
    assert c.post("/internal/alert", json=body).status_code == 401
    assert c.post("/internal/alert", headers=TOK, json=body).status_code == 503  # no handles -> alert.sh emails
    conn.execute("update competition_config set value=%s where key='team_alert_handles'",
                 (Jsonb(["+15550000001", "ops@example.com"]),))
    now["t"] = datetime(2026, 10, 14, 2, 0, tzinfo=ET)  # quiet hours: alerts bypass them
    r1 = c.post("/internal/alert", headers=TOK, json=body).json()
    assert r1 == {"ok": True, "recipients": 2, "enqueued": 2, "deduped": False}
    now["t"] += timedelta(minutes=3)
    assert c.post("/internal/alert", headers=TOK, json=body).json()["deduped"] is True
    assert c.post("/internal/alert", headers=TOK, json={"kind": "other", "message": "x"}).json()["enqueued"] == 2
    now["t"] += timedelta(minutes=10)
    assert c.post("/internal/alert", headers=TOK, json=body).json()["enqueued"] == 2
    rows = conn.execute("select handle, template, body, not_before, created_at from messages where body like '%%worker_down%%'"
                        " order by id").fetchall()
    assert len(rows) == 4 and all(r[1] == "alert" and r[3] == r[4] for r in rows)
    assert rows[0][2] == "Brodie alert [worker_down]: no heartbeat"
    # infra/alert.sh shape {component, message}; env override of the handle list
    monkeypatch.setenv("ADMIN_ALERT_HANDLES", " +15550000009 , ")
    r = c.post("/internal/alert", headers=TOK, json={"component": "infra", "message": "disk"}).json()
    assert r["recipients"] == 1 and r["enqueued"] == 1
    assert conn.execute("select handle from messages order by id desc limit 1").fetchone()[0] == "+15550000009"
    assert c.post("/internal/alert", headers=TOK, json={"message": "no kind"}).status_code == 400


# ------------------------------------------------------------------ rate limiter

def test_limiter_429_scoped_and_proxy_aware(db):
    app = create_app(PgStore(db), FakeOutbox(), clock=lambda: T0, flags=Flags(), token="tok", rate_per_min=2)
    c = TestClient(app)
    assert [c.get("/health").status_code for _ in range(3)] == [200, 200, 429]
    assert [c.post("/admin/raffle", json={"seed": "s"}).status_code for _ in range(3)] == [401, 401, 429]
    assert [c.post("/internal/alert", json={"kind": "k", "message": "m"}).status_code for _ in range(3)] == [401, 401, 429]
    # a /health flood does not starve the worker scope
    assert c.post("/calls/start", json={"call_id": "a", "line_id": "l"}).status_code == 401
    # X-Forwarded-For is ignored unless TRUSTED_PROXY: spoofed addresses share the socket peer's bucket
    app.state.rate_limiter = RateLimiter(2, trusted_proxy=False)
    codes = [c.get("/health", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code for i in range(3)]
    assert codes == [200, 200, 429]
    # behind a trusted proxy the LAST hop is the client; a forged leading entry does not help
    app.state.rate_limiter = RateLimiter(2, trusted_proxy=True)
    assert [c.get("/health", headers={"X-Forwarded-For": f"6.6.6.{i}, 1.2.3.4"}).status_code
            for i in range(3)] == [200, 200, 429]
    assert c.get("/health", headers={"X-Forwarded-For": "5.6.7.8"}).status_code == 200


def test_limiter_window_and_env(monkeypatch):
    t = {"v": 0.0}
    lim = RateLimiter(2, now=lambda: t["v"], trusted_proxy=False, max_keys=2)
    assert [lim.check("a"), lim.check("a"), lim.check("a")] == [True, True, False]
    t["v"] = 60.0
    assert lim.check("a") is True
    assert lim.check("b") and lim.check("c")  # sweep keeps memory bounded
    assert len(lim.hits) <= 3
    monkeypatch.setenv("TRUSTED_PROXY", "1")
    assert RateLimiter(5).trusted_proxy is True
    monkeypatch.setenv("TRUSTED_PROXY", "true")
    assert RateLimiter(5).trusted_proxy is False
