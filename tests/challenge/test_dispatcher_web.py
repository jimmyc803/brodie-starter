"""Web-only join / queue / status (/web/*) vs a real migrated Postgres, with locally signed Supabase-style JWTs."""
from __future__ import annotations

import base64
import hashlib
import hmac
import itertools
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from challenge.dispatcher.app import create_app
from challenge.dispatcher.flags import Flags
from challenge.dispatcher.web import AuthError, JwtVerifier, web_enabled
from challenge.store import PgStore

ET = ZoneInfo("America/New_York")
T0 = datetime(2026, 10, 13, 10, 0, tzinfo=ET)
SECRET = "test-jwt-secret-that-is-at-least-32-bytes-long!!"
ISS = "https://proj.supabase.test/auth/v1"
H = {"X-Brodie-Token": "tok"}
_seq = itertools.count(1)
EC_KEY = ec.generate_private_key(ec.SECP256R1())


def claims(sub: str | None = None, **over) -> dict:
    now = int(datetime.now().timestamp())
    c = {"sub": sub or str(uuid.uuid4()), "aud": "authenticated", "role": "authenticated", "iss": ISS,
         "email": f"user{next(_seq)}@example.com", "exp": now + 3600, "iat": now, "is_anonymous": False}
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def hs(c: dict, secret: str = SECRET) -> str:
    return jwt.encode(c, secret, algorithm="HS256")


def es(c: dict, kid: str = "k1", key=EC_KEY) -> str:
    return jwt.encode(c, key, algorithm="ES256", headers={"kid": kid})


def raw_hs256(c: dict, key: bytes) -> str:
    """Hand-rolled HS256 (PyJWT refuses to HMAC with a PEM key, an attacker would not)."""
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    body = b64(json.dumps(c).encode())
    sig = b64(hmac.new(key, f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class FakeOutbox:
    def __init__(self):
        self.sent = []

    def enqueue(self, **kw):
        self.sent.append(kw)
        return {"duplicate": False}


def _jwks(kid):
    if kid != "k1":
        raise AuthError("unknown kid")
    return EC_KEY.public_key()


@pytest.fixture
def env(db, conn):
    conn.execute("truncate clients, calls, messages, audit_log, power_hours, join_pending, ch_event_log, queue"
                 " restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null, version=0, updated_at=now()")
    now = {"t": T0}
    st = PgStore(db)
    verifier = JwtVerifier(hs_secret=SECRET, jwks=_jwks, issuer=ISS)
    app = create_app(st, FakeOutbox(), clock=lambda: now["t"],
                     flags=Flags(MESSAGING_PROVIDER="web_only", CALLER_ID_SOURCE="chert_meta"),
                     token="tok", web_verifier=verifier)
    return TestClient(app), conn, st, now


def join(c, tok, name, handle, **over):
    body = {"display_name": name, "handle": handle, "age_ok": True, "rules_ok": True, **over}
    return c.post("/web/join", headers=bearer(tok), json=body)


def new_user(c, name):
    tok = hs(claims())
    r = join(c, tok, name, f"+1555{next(_seq):07d}")
    assert r.status_code == 200 and r.json()["ok"], r.text
    return tok


# ---------------------------------------------------------------- auth

def test_rejects_missing_forged_expired_and_wrong_tokens(env):
    c, *_ = env
    good = claims()
    pem = EC_KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    other_ec = ec.generate_private_key(ec.SECP256R1())
    bad = {
        "none": None,
        "not bearer": {"Authorization": f"Basic {hs(good)}"},
        "garbage": bearer("not.a.jwt"),
        "forged secret": bearer(hs(good, secret="x" * 48)),
        "expired": bearer(hs(claims(exp=int(datetime.now().timestamp()) - 5))),
        "wrong aud": bearer(hs(claims(aud="anon"))),
        "wrong iss": bearer(hs(claims(iss="https://evil.test/auth/v1"))),
        "service role": bearer(hs(claims(role="service_role", sub=None))),
        "anon role": bearer(hs(claims(role="anon"))),
        "anonymous user": bearer(hs(claims(is_anonymous=True))),
        "no sub": bearer(hs({k: v for k, v in claims().items() if k != "sub"})),
        "non-uuid sub": bearer(hs(claims(sub="admin"))),
        "no exp": bearer(hs({k: v for k, v in claims().items() if k != "exp"})),
        "alg none": bearer(jwt.encode(good, None, algorithm="none")),
        "es forged key": bearer(es(good, key=other_ec)),
        "es unknown kid": bearer(es(good, kid="k2")),
        "alg confusion (HS256 keyed with the public key)": bearer(raw_hs256(good, pem)),
    }
    for label, headers in bad.items():
        r = c.get("/web/me", headers=headers or {})
        assert r.status_code == 401, (label, r.status_code, r.text)
        r = c.post("/web/queue", headers=headers or {}, json={"action": "join"})
        assert r.status_code == 401, (label, r.status_code)
    # The same claims signed correctly are accepted, via both key types.
    assert c.get("/web/me", headers=bearer(hs(good))).status_code == 200
    assert c.get("/web/me", headers=bearer(es(good))).status_code == 200


def test_hs256_rejected_when_only_jwks_configured():
    v = JwtVerifier(jwks=_jwks, issuer=ISS)
    with pytest.raises(AuthError):
        v.verify(hs(claims()))
    assert v.verify(es(claims()))["role"] == "authenticated"


def test_disabled_outside_web_only(db):
    app = create_app(PgStore(db), FakeOutbox(), flags=Flags(MESSAGING_PROVIDER="mock"), token="tok",
                     web_verifier=JwtVerifier(hs_secret=SECRET, issuer=ISS))
    c = TestClient(app)
    assert c.get("/web/me", headers=bearer(hs(claims()))).status_code == 404
    assert web_enabled("web_only", {}) and not web_enabled("chert", {}) and web_enabled("chert", {"WEB_JOIN_ENABLED": "1"})


def test_unconfigured_verifier_is_unavailable_not_open(db):
    app = create_app(PgStore(db), FakeOutbox(), flags=Flags(MESSAGING_PROVIDER="web_only"), token="tok",
                     web_verifier=JwtVerifier())
    r = TestClient(app).get("/web/me", headers=bearer(hs(claims())))
    assert r.status_code == 503


# ---------------------------------------------------------------- happy path

def test_join_queue_status_happy_path(env):
    c, conn, st, now = env
    sub = str(uuid.uuid4())
    tok = hs(claims(sub=sub, email="Ana@Example.com"))

    r = c.get("/web/me", headers=bearer(tok))
    assert r.status_code == 200
    assert r.json()["registered"] is False and r.json()["email"] == "ana@example.com"

    assert join(c, tok, "Ana_W", "(555) 010-0001", age_ok=False).json()["reason"] == "confirm_required"
    assert join(c, tok, "a", "5550100001").json()["reason"] == "bad_name"
    assert join(c, tok, "Ana_W", "not a phone").json()["reason"] == "bad_handle"

    r = join(c, tok, "Ana_W", "(555) 010-0001")
    body = r.json()
    assert body["ok"] and body["reason"] == "ok" and body["me"]["registered"] is True
    assert body["me"]["handle"] == "+15550100001" and body["me"]["display_name"] == "Ana_W"
    row = conn.execute("select c.auth_user_id::text, h.linked_via, c.age_confirmed_at is not null, c.rules_accepted_at"
                       " is not null from clients c join client_handles h on h.client_id = c.id"
                       " where c.display_name = 'Ana_W'").fetchone()
    assert row == (sub, "web", True, True)
    assert join(c, tok, "Other_Name", "+15550100009").json()["reason"] == "already_registered"

    me = c.get("/web/me", headers=bearer(tok)).json()
    assert me["queue"] == {"status": None, "position": None, "eta": None}
    assert me["calls_left"] == 5 and me["points_today"] == 0 and me["claim"] is None
    assert me["line_open"] is True  # idle line, nobody waiting, chert_meta walk-in possible

    # Someone else queues first; Ana is #2 with an ETA range.
    bo = new_user(c, "Bo_K")
    assert c.post("/web/queue", headers=bearer(bo), json={"action": "join"}).json()["me"]["queue"]["position"] == 1
    r = c.post("/web/queue", headers=bearer(tok), json={"action": "join"}).json()
    assert r["ok"] and r["reason"] == "ok"
    q = r["me"]["queue"]
    assert q["status"] == "waiting" and q["position"] == 2
    assert q["eta"]["hi_min"] - q["eta"]["lo_min"] == 5 and q["eta"]["lo_min"] >= 5
    assert r["me"]["line_open"] is False
    assert c.post("/web/queue", headers=bearer(tok), json={"action": "join"}).json()["reason"] == "already"

    # Scheduler pops Bo; Bo sees the claim with seconds left, Ana moves to #1.
    st.rpc("ch_tick", {"p_now": T0})
    now["t"] = T0 + timedelta(seconds=30)
    bo_me = c.get("/web/me", headers=bearer(bo)).json()
    assert bo_me["claim"]["seconds_left"] == 60 and bo_me["queue"]["status"] == "notified"
    ana = c.get("/web/me", headers=bearer(tok)).json()
    assert ana["claim"] is None and ana["queue"]["position"] == 1

    # Ana leaves; leaving twice is harmless.
    r = c.post("/web/queue", headers=bearer(tok), json={"action": "leave"}).json()
    assert r["reason"] == "left" and r["me"]["queue"]["status"] is None
    assert c.post("/web/queue", headers=bearer(tok), json={"action": "leave"}).json()["reason"] == "not_queued"


def test_claim_call_and_points_today(env):
    c, conn, st, now = env
    tok = new_user(c, "Cy_R")
    handle = c.get("/web/me", headers=bearer(tok)).json()["handle"]
    assert c.post("/web/queue", headers=bearer(tok), json={"action": "join"}).json()["ok"]
    st.rpc("ch_tick", {"p_now": T0})
    me = c.get("/web/me", headers=bearer(tok)).json()
    assert me["claim"]["seconds_left"] == 90 and me["claim"]["line_id"] == "line-1"

    # Claim holder FaceTimes in (identified by the web-registered handle), commits 2 valid reps.
    r = c.post("/calls/start", headers=H, json={"call_id": "wc1", "line_id": "line-1", "handle": handle}).json()
    assert r["decision"] == "accept"
    assert c.get("/web/me", headers=bearer(tok)).json()["in_call"] is True
    at = (T0 + timedelta(seconds=10)).isoformat()
    rep = {"t": 1.0, "at": at, "valid": True, "reject_reasons": [], "faults": [], "in_challenge": False}
    ev = {"kind": "reps_committed", "call_id": "wc1", "idem_key": "wc1-c", "at": at, "payload": {
        "started_at": T0.isoformat(), "ended_at": (T0 + timedelta(seconds=195)).isoformat(), "liveness_result": "pass",
        "judge_version": "j1", "reps": [{**rep, "n": 1}, {**rep, "n": 2}]}}
    assert c.post("/calls/event", headers=H, json=ev).json()["ok"]
    end = {"kind": "call_ended", "call_id": "wc1", "idem_key": "wc1-e", "at": at, "payload": {
        "ended_at": (T0 + timedelta(seconds=195)).isoformat(), "count_end_at": (T0 + timedelta(seconds=180)).isoformat(),
        "rep_count": 2}}
    assert c.post("/calls/event", headers=H, json=end).json()["ok"]
    now["t"] = T0 + timedelta(seconds=200)
    me = c.get("/web/me", headers=bearer(tok)).json()
    assert me["points_today"] == 2 and me["points"] == 2 and me["calls_left"] == 4 and me["in_call"] is False
    assert me["rank"] == 1

    # Next ET day: today's points reset, total stays.
    now["t"] = datetime(2026, 10, 14, 0, 0, 1, tzinfo=ET)
    me = c.get("/web/me", headers=bearer(tok)).json()
    assert me["points_today"] == 0 and me["points"] == 2 and me["calls_left"] == 5


def test_opt_toggle(env):
    c, conn, *_ = env
    tok = new_user(c, "Di_Z")
    assert c.post("/web/queue", headers=bearer(tok), json={"action": "join"}).json()["ok"]
    r = c.post("/web/opt", headers=bearer(tok), json={"opted_out": True}).json()
    assert r["ok"] and r["me"]["opted_out"] is True and r["me"]["queue"]["status"] is None  # STOP leaves the queue
    r = c.post("/web/opt", headers=bearer(tok), json={"opted_out": False}).json()
    assert r["me"]["opted_out"] is False


# ---------------------------------------------------------------- isolation / conflicts

def test_never_exposes_or_touches_another_user(env):
    c, conn, *_ = env
    a, b = new_user(c, "Ev_A"), new_user(c, "Fi_B")
    me_a = c.get("/web/me", headers=bearer(a)).json()
    me_b = c.get("/web/me", headers=bearer(b)).json()
    assert me_a["display_name"] == "Ev_A" and me_b["display_name"] == "Fi_B"
    assert "user_id" not in me_a and me_a["handle"] != me_b["handle"]
    # No endpoint takes a user id; smuggled fields are rejected, not honoured.
    uid_b = conn.execute("select id::text from clients where display_name = 'Fi_B'").fetchone()[0]
    r = c.post("/web/queue", headers=bearer(a), json={"action": "join", "user_id": uid_b})
    assert r.status_code == 422
    r = c.post("/web/opt", headers=bearer(a), json={"opted_out": True, "p_user_id": uid_b})
    assert r.status_code == 422
    assert conn.execute("select count(*) from queue").fetchone()[0] == 0
    # Registered-only actions for an unregistered login.
    stranger = hs(claims())
    assert c.post("/web/queue", headers=bearer(stranger), json={"action": "join"}).status_code == 409
    assert c.post("/web/opt", headers=bearer(stranger), json={"opted_out": True}).status_code == 409


def test_handle_and_name_conflicts_never_merge_accounts(env):
    c, conn, *_ = env
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = conn.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,'Gus','Gus_I',%s)"
                       " returning id", (coach, T0)).fetchone()[0]
    conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values ('+15550199999',%s,'phone','join')",
                 (uid,))
    tok = hs(claims())
    assert join(c, tok, "Hal_J", "555-019-9999").json()["reason"] == "handle_taken"
    assert join(c, tok, "gus_i", "+15550188888").json()["reason"] == "taken"
    assert c.get("/web/me", headers=bearer(tok)).json()["registered"] is False
    assert conn.execute("select count(*) from clients where auth_user_id is not null").fetchone()[0] == 0
    # Apple ID email handles are accepted and lowercased.
    r = join(c, tok, "Hal_J", "Hal.J@iCloud.com").json()
    assert r["ok"] and r["me"]["handle"] == "hal.j@icloud.com"


def test_registration_closed(env):
    c, conn, *_ = env
    conn.execute("update competition_config set value = 'false' where key = 'registration_open'")
    try:
        assert join(c, hs(claims()), "Ivy_K", "+15550177777").json()["reason"] == "closed"
    finally:
        conn.execute("update competition_config set value = 'true' where key = 'registration_open'")


def test_rate_limited_per_user(db, monkeypatch):
    monkeypatch.setenv("WEB_RATE_PER_USER_MIN", "3")
    app = create_app(PgStore(db), FakeOutbox(), clock=lambda: T0, flags=Flags(MESSAGING_PROVIDER="web_only"),
                     token="tok", web_verifier=JwtVerifier(hs_secret=SECRET, issuer=ISS))
    c = TestClient(app)
    tok, other = hs(claims()), hs(claims())
    codes = [c.get("/web/me", headers=bearer(tok)).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    assert c.get("/web/me", headers=bearer(other)).status_code == 200  # budgets are per user
    # Rejected tokens never reach the per-user budget or the database.
    assert c.get("/web/me", headers=bearer(hs(claims(), secret="y" * 48))).status_code == 401


def test_concurrent_joins_create_one_account_per_login_and_handle(env):
    from concurrent.futures import ThreadPoolExecutor

    _, conn, st, _ = env
    sub = str(uuid.uuid4())

    def go(args):
        return st.rpc("ch_web_join", {"p_auth_user_id": args[0], "p_display_name": args[1], "p_handle": args[2],
                                      "p_now": T0})

    with ThreadPoolExecutor(8) as ex:
        same_login = list(ex.map(go, [(sub, f"Jo_{i}", f"+1555030000{i}") for i in range(6)]))
        same_handle = list(ex.map(go, [(str(uuid.uuid4()), f"Ka_{i}", "+15550400000") for i in range(6)]))
    assert sorted(r["reason"] for r in same_login) == ["already_registered"] * 5 + ["ok"]
    assert sorted(r["reason"] for r in same_handle) == ["handle_taken"] * 5 + ["ok"]
    assert conn.execute("select count(*) from clients where auth_user_id = %s", (sub,)).fetchone()[0] == 1
    assert conn.execute("select count(*) from client_handles where client_id ="
                        " (select id from clients where auth_user_id = %s)", (sub,)).fetchone()[0] == 1
