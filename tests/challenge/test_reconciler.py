"""Checkpoint reconciler (task 32): checkpoints are written by the real CompetitionCall (fake dispatcher, fake clock,
scripted liveness stand-in) into temp dirs; the reconciler replays them through a fake dispatcher client (one test
goes through the real DispatcherClient over httpx.MockTransport to check the wire idem keys)."""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time

import httpx
import pytest

from challenge.judge.gates import JUDGE_VERSION
from challenge.worker.client import DispatcherClient, DispatcherError, utc_iso
from challenge.worker.controller import CallLock, CompetitionCall, checkpoint_path, write_json_atomic
from scripts import reconcile_sessions as rs
from scripts.reconcile_sessions import Reconciler


def run(coro):
    return asyncio.run(coro)


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeClient:
    """Dispatcher client stand-in: records events; `script[kind]` is a list of responses / exceptions used in order
    (then {ok: true})."""

    def __init__(self, script=None):
        self.script = {k: list(v) for k, v in (script or {}).items()}
        self.events = []

    async def start_call(self, call_id, line_id, handle=None, *, deadline_s=None):
        return {"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None}

    async def event(self, kind, call_id, payload, *, at=None, key=None):
        self.events.append({"kind": kind, "call_id": call_id, "payload": payload, "at": at,
                            "idem_key": key or f"{call_id}:{kind}"})
        todo = self.script.get(kind)
        r = todo.pop(0) if todo else {"ok": True, "duplicate": False}
        if isinstance(r, Exception):
            raise r
        return r

    def kinds(self):
        return [e["kind"] for e in self.events if e["kind"] != "call_started"]


class StubLiveness:
    """LivenessChallenge interface; fires at `fire` s and resolves to `outcome` on the first poll (None: never fires)."""

    def __init__(self, rng, thr, outcome=None, fire=20.0):
        self.outcome, self.fire = outcome, fire
        self.started = False
        self.active = False

    def schedule(self, t0):
        return t0 + self.fire

    def due(self, t):
        return self.outcome is not None and t >= self.fire

    def start(self, t):
        self.started = self.active = True
        self._w = (t, t + 5.0)
        return "challenge_lift_hold"

    def poll(self, t):
        self.active = False
        return self.outcome, None

    def windows(self):
        return [self._w] if self.started else []

    def on_frame(self, f):
        pass

    def on_rep(self, t):
        pass

    def finish(self, t):
        return "fail"


def valid_rep():
    return {"valid": True, "reject_reasons": [], "metrics": {"min_elbow_deg_l": 80.0, "side": "left"},
            "judge_version": JUDGE_VERSION}


def make_call(tmp_path, t0, call_id="call-1", rep_ts=(30.0, 40.0, 50.0), outcome=None, invalid_at=(40.0,), alive=False):
    """A mid-call checkpoint written by the real controller: accepted at t0, reps at rep_ts (call clock). alive=False:
    the worker then dies (its per-call lock is released, as the kernel does); alive=True: it still owns the call."""
    clock = Clock(t0)
    disp = FakeClient()

    async def go():
        c = CompetitionCall(call_id, "line-1", "+15550001111", disp, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room",
                            # the liveness challenge is off by default since j3; these rigs exercise it ON
                            judge_cfg={"liveness_enabled": True},
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr, outcome))
        assert await c.start()
        if outcome is not None:
            clock.t = t0 + 21.0
            c.tick()
            clock.t = t0 + 22.0
            c.tick()
        for t in rep_ts:
            clock.t = t0 + t
            ev = valid_rep() if t not in invalid_at else {"valid": False, "reject_reasons": ["too_shallow"], "metrics": {}}
            c.on_rep(ev, t0 + t)
        await asyncio.sleep(0)                      # let call_started go out
        return c

    c = run(go())
    assert c.lock is not None and c.lock.held                 # the worker owns the call while it runs
    if not alive:
        c.lock.release()
    return c, checkpoint_path(call_id, str(tmp_path)), disp


def load(path):
    with open(path) as f:
        return json.load(f)


def dead_pid():
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def set_fields(path, **kw):
    d = load(path)
    d.update(kw)
    with open(path, "w") as f:
        json.dump(d, f)


def rec(tmp_path, client, clock, alerts=None, **kw):
    sink = (lambda c, d: alerts.append((c, d))) if alerts is not None else rs.log_alert
    return Reconciler(client, str(tmp_path), clock=clock, alert=sink, **kw)


# ------------------------------------------------------------------ crash mid-call
def test_crash_mid_call_recovered_exactly_once_with_liveness_fail(tmp_path, caplog):
    caplog.set_level("DEBUG")
    t0 = time.time() - 1000
    call, path, _ = make_call(tmp_path, t0)
    d = load(path)
    assert d["committed"] is False and d["sealed"] is False and d["final"] is False
    client, alerts = FakeClient(), []
    r = rec(tmp_path, client, Clock(time.time()), alerts=alerts)
    out = run(r.run_once())
    assert [x["call_id"] for x in out["replayed"]] == ["call-1"] and out["replayed"][0]["committed"]
    assert client.kinds() == ["reps_committed", "call_ended"]
    assert [e["idem_key"] for e in client.events] == ["call-1:reps_committed", "call-1:call_ended"]
    rc = client.events[0]["payload"]
    assert rc["liveness_result"] == "fail"                         # no challenge passed (C7.l)
    assert rc["judge_version"] == JUDGE_VERSION
    assert len(rc["reps"]) == 3 and not any(x["valid"] for x in rc["reps"])
    assert sum("liveness_fail" in x["reject_reasons"] for x in rc["reps"]) == 2
    ended = client.events[1]["payload"]["ended_at"]
    assert ended == utc_iso(t0 + 50.0) == rc["ended_at"]            # ended at the last rep
    assert client.events[1]["payload"]["rep_count"] == 3
    assert client.events[1]["payload"]["count_end_at"] == utc_iso(t0 + 50.0)
    d = load(path)
    assert d["committed"] is True and d["sent"] == {"reps_committed": True, "call_ended": True}
    assert d["reconcile"]["attempts"] == 1 and alerts == []

    # duplicate run: nothing sent, file untouched
    before = open(path, "rb").read()
    out = run(r.run_once())
    assert out["replayed"] == [] and out["skipped"] == {"call-1": "committed"}
    assert len(client.events) == 2 and open(path, "rb").read() == before
    assert os.path.exists(path)                                     # never deleted
    assert "5550001111" not in open(path).read() and "5550001111" not in caplog.text   # no handle stored or logged


def test_crash_without_reps_ends_at_call_length(tmp_path):
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0, rep_ts=())
    client = FakeClient()
    run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert client.events[0]["payload"]["ended_at"] == utc_iso(t0 + 195.0)
    assert client.events[0]["payload"]["reps"] == []
    assert client.events[0]["payload"]["liveness_result"] == "skipped"
    assert load(path)["committed"] is True


def test_passed_liveness_keeps_valid_reps(tmp_path):
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0, outcome="pass")
    assert load(path)["liveness_result"] == "pass"
    client = FakeClient()
    run(rec(tmp_path, client, Clock(time.time())).run_once())
    p = client.events[0]["payload"]
    assert p["liveness_result"] == "pass"
    assert [x["valid"] for x in p["reps"]] == [True, False, True]
    assert not any("liveness_fail" in x["reject_reasons"] for x in p["reps"])


def test_wire_idem_keys_through_dispatcher_client(tmp_path):
    t0 = time.time() - 1000
    make_call(tmp_path, t0)
    seen = []

    def handler(req):
        seen.append((req.url.path, json.loads(req.content), req.headers.get("x-brodie-token")))
        return httpx.Response(200, json={"ok": True, "duplicate": False})

    async def go():
        c = DispatcherClient("http://disp", "tok", transport=httpx.MockTransport(handler), retries=0)
        try:
            return await rec(tmp_path, c, Clock(time.time())).run_once()
        finally:
            await c.aclose()

    out = run(go())
    assert out["replayed"][0]["committed"]
    assert [(p, b["kind"], b["idem_key"], tok) for p, b, tok in seen] == [
        ("/calls/event", "reps_committed", "call-1:reps_committed", "tok"),
        ("/calls/event", "call_ended", "call-1:call_ended", "tok")]


# ------------------------------------------------------------------ what is left alone
def test_fresh_in_progress_file_untouched(tmp_path):
    t0 = time.time() - 30
    c, path, _ = make_call(tmp_path, t0, alive=True)                    # the worker is counting this call
    before = open(path, "rb").read()
    client = FakeClient()
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["replayed"] == [] and out["skipped"] == {"call-1": "owner alive"}
    assert client.events == [] and open(path, "rb").read() == before
    assert c.lock.held                                                   # the reconciler did not disturb the owner


def test_unsealed_stale_with_live_pid_left_alone(tmp_path):
    """Stale and unsealed, but its worker still owns it (lock held): left alone however old the call is."""
    t0 = time.time() - 1000
    c, path, _ = make_call(tmp_path, t0, alive=True)
    assert load(path)["worker_pid"] == os.getpid()
    before = open(path, "rb").read()
    client = FakeClient()
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["skipped"] == {"call-1": "owner alive"} and client.events == []
    assert open(path, "rb").read() == before
    c.lock.release()                                                     # the worker dies: now it is replayed
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["replayed"][0]["committed"] and client.kinds() == ["reps_committed", "call_ended"]


def test_unsealed_stale_dead_pid_replayed_fresh_dead_pid_not(tmp_path):
    now = time.time()
    make_call(tmp_path, now - 1000, call_id="old")
    make_call(tmp_path, now - 100, call_id="young")
    pid = dead_pid()
    for cid in ("old", "young"):
        set_fields(checkpoint_path(cid, str(tmp_path)), worker_pid=pid)
    client = FakeClient()
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert [x["call_id"] for x in out["replayed"]] == ["old"]
    assert out["skipped"] == {"young": "not stale"}
    assert {e["call_id"] for e in client.events} == {"old"}
    assert load(checkpoint_path("old", str(tmp_path)))["committed"] is True
    assert load(checkpoint_path("young", str(tmp_path)))["committed"] is False


def test_stale_threshold_is_configurable(tmp_path):
    t0 = time.time() - 100
    make_call(tmp_path, t0)
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time()), stale_s=90).run_once())
    assert out["replayed"][0]["committed"]


def test_unsealed_final_waits_for_dead_pid_and_stale(tmp_path):
    """end() ran but the feed never sealed (deferred commit): the worker may still seal it; never replayed while it lives."""
    t0 = time.time() - 1000
    c, path, _ = make_call(tmp_path, t0, alive=True)
    set_fields(path, final=True, ended_t=t0 + 195, sealed=False)
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["skipped"] == {"call-1": "owner alive"} and client.events == []
    c.lock.release()                                                     # the worker dies with the commit deferred
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"]
    assert client.events[0]["payload"]["ended_at"] == utc_iso(t0 + 195)


def test_sealed_final_left_to_a_live_worker_within_grace(tmp_path):
    t0 = time.time() - 300
    clock = Clock(t0)
    disp = FakeClient({"reps_committed": [DispatcherError("down")]})

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        return await c.end("complete")

    assert run(worker())["committed"] is False
    path = checkpoint_path("call-1", str(tmp_path))
    d = load(path)
    assert d["sealed"] and d["final"] and not d["committed"]
    # while a worker still holds the call (e.g. its end() still in flight) the reconciler waits, however long
    held = CallLock.try_acquire(path)
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time() + 3600)).run_once())
    assert out["skipped"] == {"call-1": "owner alive"} and client.events == []
    held.release()                                                       # its end() returned: the call is free
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] and client.kinds() == ["reps_committed", "call_ended"]
    # the replayed payload is the one the worker built
    assert client.events[0]["payload"]["reps"] == [e for e in disp.events if e["kind"] == "reps_committed"][0]["payload"]["reps"]


def test_committed_by_worker_never_touched(tmp_path):
    t0 = time.time() - 1000
    clock = Clock(t0)
    disp = FakeClient()

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        clock.t = t0 + 195
        return await c.end("complete")

    assert run(worker())["committed"] is True
    path = checkpoint_path("call-1", str(tmp_path))
    before = open(path, "rb").read()
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["skipped"] == {"call-1": "committed"} and client.events == [] and open(path, "rb").read() == before


def test_foreign_and_unreadable_files_left_as_is(tmp_path):
    bad = tmp_path / "broken.challenge.json"
    bad.write_text("{not json")
    other = tmp_path / "x.challenge.json"
    other.write_text(json.dumps({"call_id": "y", "line_id": "l", "t0": 1.0, "committed": False}))
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"] == [] and set(out["skipped"]) == {"broken.challenge.json", "x.challenge.json"}
    assert bad.read_text() == "{not json" and client.events == []


def test_malformed_checkpoint_backs_off_and_does_not_block_others(tmp_path):
    now = time.time()
    _, bad, _ = make_call(tmp_path, now - 1000, call_id="a-bad")
    make_call(tmp_path, now - 1000, call_id="b-good")
    d = load(bad)
    d["reps"] = [{"n": 1}]                         # a rep without its fields
    with open(bad, "w") as f:
        json.dump(d, f)
    client, alerts = FakeClient(), []
    out = run(rec(tmp_path, client, Clock(now), alerts=alerts).run_once())
    assert [(x["call_id"], x["committed"]) for x in out["replayed"]] == [("a-bad", False), ("b-good", True)]
    assert {e["call_id"] for e in client.events} == {"b-good"}
    assert [a for a, _ in alerts] == ["commit_pending"]
    assert load(bad)["reconcile"]["next_try_t"] == pytest.approx(now + 60) and load(bad)["reps"] == [{"n": 1}]
    assert run(rec(tmp_path, client, Clock(now + 1), alerts=alerts).run_once())["skipped"]["a-bad"] == "backoff"


def test_missing_dir_and_lock(tmp_path):
    client = FakeClient()
    assert run(Reconciler(client, str(tmp_path / "nope")).run_once())["replayed"] == []
    assert not (tmp_path / "nope").exists()
    make_call(tmp_path, time.time() - 1000)
    import fcntl
    with open(tmp_path / rs.LOCK_NAME, "a") as lk:
        fcntl.flock(lk.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["locked"] is True and client.events == []
    assert run(rec(tmp_path, client, Clock(time.time())).run_once())["replayed"][0]["committed"]


# ------------------------------------------------------------------ dispatcher answers
@pytest.mark.parametrize("answer", [{"ok": True, "duplicate": False, "already": True},
                                    {"ok": False, "duplicate": False, "reason": "already"},
                                    {"ok": True, "duplicate": True}])
def test_already_is_success(tmp_path, answer):
    """The worker's reps_committed was acknowledged (its own ack: sent.reps_committed) and only call_ended failed:
    the replay never resends the reps, and an `already`/duplicate call_ended is delivered."""
    t0 = time.time() - 1000
    clock = Clock(t0)
    disp = FakeClient({"call_ended": [DispatcherError("down")]})

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda *a: None,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        await c.end("complete")

    run(worker())
    assert load(checkpoint_path("call-1", str(tmp_path)))["sent"] == {"reps_committed": True, "call_ended": False}
    client = FakeClient({"call_ended": [answer]})
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] and client.kinds() == ["call_ended"]
    assert load(checkpoint_path("call-1", str(tmp_path)))["committed"] is True


@pytest.mark.parametrize("answer", [{"ok": True, "duplicate": False, "already": True},
                                    {"ok": False, "duplicate": False, "reason": "already"},
                                    {"ok": True, "duplicate": True}])
def test_already_after_own_earlier_send_of_same_payload_is_success(tmp_path, answer):
    """An earlier replay got a 2xx for this exact payload (acked digest in the ledger) but its checkpoint save was
    lost: `already`/duplicate now is that commit, proven by the acked digest."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    first = FakeClient({"call_ended": [DispatcherError("down")]})
    assert run(rec(tmp_path, first, Clock(time.time())).run_once())["replayed"][0]["committed"] is False
    assert [e["acked"] for e in rs.read_ledger(path)] == [True]
    set_fields(path, sent={"reps_committed": False, "call_ended": False})   # the save after the ack never landed
    client = FakeClient({"reps_committed": [answer]})
    out = run(rec(tmp_path, client, Clock(time.time() + 3600)).run_once())
    assert out["replayed"][0]["committed"] and client.kinds() == ["reps_committed", "call_ended"]
    assert client.events[0]["payload"] == first.events[0]["payload"]
    assert load(checkpoint_path("call-1", str(tmp_path)))["committed"] is True


@pytest.mark.parametrize("answer", [{"ok": True, "duplicate": False, "already": True},
                                    {"ok": True, "duplicate": True},
                                    {"ok": False, "duplicate": False, "reason": "already"}])
def test_unprovable_stored_commit_is_a_conflict_kept_for_review(tmp_path, answer):
    """A crash replay (unsealed checkpoint, no acked digest) answered already/duplicate: the stored commit may carry
    other reps -> never committed:true; both sides kept; one alert."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    client, alerts = FakeClient({"reps_committed": [answer]}), []
    r = rec(tmp_path, client, Clock(time.time()), alerts=alerts)
    out = run(r.run_once())
    assert out["replayed"][0]["committed"] is False and out["replayed"][0]["error"] == "conflict"
    assert client.kinds() == ["reps_committed"]                                   # call_ended not sent after it
    d = load(path)
    assert d["committed"] is False and d["sent"]["reps_committed"] is False and d["reconcile"]["conflict"]
    c = load(path + rs.CONFLICT_SUFFIX)
    assert c["replayed_checkpoint"]["reps"] and c["ledger"] == [] and \
        c["conflict"]["digest"] == rs.payload_digest(client.events[0]["payload"])
    assert sorted(a for a, _ in alerts) == ["commit_conflict", "commit_pending"]
    assert run(r.run_once())["skipped"] == {"call-1": "payload conflict (admin review)"}
    assert len(client.events) == 1 and len(alerts) == 2


def test_backoff_after_failure_and_no_resend_of_acknowledged_event(tmp_path):
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0)
    client = FakeClient({"call_ended": [DispatcherError("down"), {"ok": False, "reason": "not_found"}]})
    alerts = []
    now = time.time()
    clock = Clock(now)
    r = rec(tmp_path, client, clock, alerts=alerts, backoff_s=60, backoff_max_s=100)
    out = run(r.run_once())
    assert out["replayed"][0]["committed"] is False
    assert client.kinds() == ["reps_committed", "call_ended"]
    d = load(path)
    assert d["committed"] is False and d["sent"] == {"reps_committed": True, "call_ended": False}
    assert d["reconcile"]["next_try_t"] == pytest.approx(now + 60) and d["reconcile"]["failures"] == 1
    assert [c for c, _ in alerts] == ["commit_pending"]
    clock.t = now + 30
    assert run(r.run_once())["skipped"] == {"call-1": "backoff"} and len(client.events) == 2
    clock.t = now + 61
    out = run(r.run_once())
    assert out["replayed"][0]["committed"] is False and client.kinds() == ["reps_committed", "call_ended", "call_ended"]
    d = load(path)
    assert d["reconcile"]["next_try_t"] == pytest.approx(now + 61 + 100)       # 120 capped at 100
    assert "not_found" in d["reconcile"]["last_error"]
    clock.t = now + 162
    out = run(r.run_once())
    assert out["replayed"][0]["committed"] is True
    assert client.kinds() == ["reps_committed", "call_ended", "call_ended", "call_ended"]   # reps_committed once
    d = load(path)
    assert d["committed"] is True and "next_try_t" not in d["reconcile"] and d["reconcile"]["attempts"] == 3


def test_reps_committed_failure_never_sends_call_ended(tmp_path):
    make_call(tmp_path, time.time() - 1000)
    client = FakeClient({"reps_committed": [DispatcherError("down")]})
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] is False and client.kinds() == ["reps_committed"]


# ------------------------------------------------------------------ late reps
def test_late_reps_alert_once_and_are_never_amended(tmp_path):
    t0 = time.time() - 1000
    clock = Clock(t0)
    disp = FakeClient({"reps_committed": [DispatcherError("down")]})

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda *a: None,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        await c.end("complete")
        c.on_rep(valid_rep(), t0 + 100)            # arrives after sealing: late
        return c

    c = run(worker())
    assert len(c.late_reps) == 1
    path = checkpoint_path("call-1", str(tmp_path))
    client, alerts = FakeClient(), []
    r = rec(tmp_path, client, Clock(time.time()), alerts=alerts)
    out = run(r.run_once())
    assert out["replayed"][0]["committed"] is False
    assert client.kinds() == ["reps_committed", "call_ended"]
    assert [x["t"] for x in client.events[0]["payload"]["reps"]] == [30.0]      # the sealed payload only
    assert client.events[1]["payload"]["rep_count"] == 1
    assert [a for a, _ in alerts] == ["commit_pending"]
    d = load(path)
    assert d["committed"] is False and len(d["late_reps"]) == 1 and d["reconcile"]["late_alerted"] is True
    for _ in range(2):                                                          # never amended, never re-alerted
        out = run(r.run_once())
        assert out["skipped"] == {"call-1": "late_reps (admin review)"}
    assert len(client.events) == 2 and len(alerts) == 1


def test_late_reps_with_both_events_already_sent(tmp_path):
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0)
    d = load(path)
    d.update(final=True, sealed=True, ended_t=t0 + 195, sent={"reps_committed": True, "call_ended": True},
             late_reps=[dict(d["reps"][0], n=9, t=60.0)])
    with open(path, "w") as f:
        json.dump(d, f)
    client, alerts = FakeClient(), []
    r = rec(tmp_path, client, Clock(time.time()), alerts=alerts)
    run(r.run_once())
    run(r.run_once())
    assert client.events == [] and [a for a, _ in alerts] == ["commit_pending"]
    assert load(path)["committed"] is False


# ------------------------------------------------------------------ plumbing
def test_http_alert_posts_internal_alert():
    seen = []

    def handler(req):
        seen.append((req.url.path, req.headers.get("x-brodie-token"), json.loads(req.content)))
        return httpx.Response(200, json={"ok": True})

    rs.HttpAlert("http://disp/", "tok", transport=httpx.MockTransport(handler))("commit_pending", "call c: x")
    assert seen == [("/internal/alert", "tok", {"kind": "commit_pending", "component": "reconciler",
                                                "message": "commit_pending: call c: x"})]


def test_http_alert_failure_is_logged_not_raised(caplog):
    def handler(req):
        raise httpx.ConnectError("down", request=req)

    rs.HttpAlert("http://disp", "tok", transport=httpx.MockTransport(handler))("commit_pending", "d")
    assert any("not delivered" in r.message for r in caplog.records)


def test_pid_alive():
    """Owner liveness is the per-call lock: held -> busy for everyone else; released -> acquirable; not reentrant
    across open descriptions (a second controller in the same process is refused too)."""
    p = os.path.join(tempfile.mkdtemp(), "c.challenge.json")
    a = CallLock.try_acquire(p)
    assert a is not None and a.held is True
    assert CallLock.try_acquire(p) is None
    a.release()
    a.release()                                                   # idempotent
    b = CallLock.try_acquire(p)
    assert b is not None and b.held is True and a.held is False
    b.release()


def test_args_and_env(monkeypatch):
    a = rs.parse_args([])
    assert a.stale_s == 375 and a.once is False and a.dir is None
    a = rs.parse_args(["--once", "--dir", "/x", "--stale-s", "10"])
    assert a.once and a.dir == "/x" and a.stale_s == 10
    with pytest.raises(SystemExit):
        rs.parse_args(["--stale-s", "-1"])
    monkeypatch.delenv("DISPATCHER_URL", raising=False)
    monkeypatch.delenv("DISPATCHER_TOKEN", raising=False)
    assert run(rs.amain(rs.parse_args(["--once"]))) == 2


# ------------------------------------------------------------------ ownership with the worker (per-call lock)
def test_worker_write_during_replay_is_preserved_and_not_marked_committed(tmp_path):
    """While the reconciler owns the call (replay in flight), a worker cannot take it over to write into it: its
    start() fails closed for that call, the checkpoint is only the replay's, and the replay commits what it sent."""
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0)
    seen = {}

    class Racing(FakeClient):
        async def event(self, kind, call_id, payload, *, at=None, key=None):
            if kind == "reps_committed" and "start" not in seen:     # a restarted worker during the POST
                w = CompetitionCall("call-1", "line-1", None, FakeClient(), clock=Clock(t0 + 60),
                                    checkpoint_dir=str(tmp_path), hangup_mode="leave_room", alert=lambda *a: None,
                                    liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
                seen["before"] = open(path, "rb").read()
                seen["start"] = await w.start()
                seen["decision"], seen["after"] = w.decision, open(path, "rb").read()
            return await super().event(kind, call_id, payload, at=at, key=key)

    client, alerts = Racing(), []
    out = run(rec(tmp_path, client, Clock(time.time()), alerts=alerts).run_once())
    assert seen["start"] is False and seen["decision"] == "error"            # refused: the reconciler owns it
    assert seen["after"] == seen["before"]                                    # it wrote nothing
    assert out["replayed"][0]["committed"] is True and alerts == []
    d = load(path)
    assert d["committed"] is True and d["late_reps"] == [] and d["reconcile"]["attempts"] == 1
    assert [x["t"] for x in client.events[0]["payload"]["reps"]] == [30.0, 40.0, 50.0]
    assert CallLock.try_acquire(path) is not None                            # released after the write-back


def test_checkpoint_swapped_after_read_is_not_replayed(tmp_path, monkeypatch):
    """A restarted worker takes the call right after the reconciler's first (lock-free) read: the reconciler's lock
    attempt fails, nothing is sent and the worker's version stays untouched."""
    t0 = time.time() - 1000
    _, path, _ = make_call(tmp_path, t0)
    real = rs.read_snapshot
    taken = []

    def read_then_takeover(p):
        snap = real(p)
        if not taken:
            lk = CallLock.try_acquire(p)                       # the new worker owns the call ...
            d = load(p)
            d["worker_pid"] = os.getpid()
            write_json_atomic(p, d)                            # ... and rewrites it
            taken.append((lk, open(p, "rb").read()))
        return snap

    monkeypatch.setattr(rs, "read_snapshot", read_then_takeover)
    client = FakeClient()
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["replayed"] == [] and out["skipped"] == {"call-1": "owner alive"}
    assert client.events == [] and open(path, "rb").read() == taken[0][1]
    taken[0][0].release()


def test_liveness_uses_metadata_of_the_version_it_read(tmp_path, monkeypatch):
    """Owner liveness comes from the lock, never from file metadata or worker_pid: an old mtime and a dead worker_pid
    do not make a held call replayable, and a live worker_pid does not block a free one."""
    t0 = time.time() - 1000
    c, path, _ = make_call(tmp_path, t0, alive=True)
    old = time.time() - 3600
    set_fields(path, worker_pid=dead_pid())
    os.utime(path, (old, old))
    client = FakeClient()
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["skipped"] == {"call-1": "owner alive"} and client.events == []
    c.lock.release()
    set_fields(path, worker_pid=os.getpid())                   # a live pid that no longer owns the call
    out = run(Reconciler(client, str(tmp_path), clock=time.time).run_once())
    assert out["replayed"][0]["committed"] is True and client.kinds() == ["reps_committed", "call_ended"]


def test_checkpoint_lock_excludes_worker_writes(tmp_path):
    """The per-call lock excludes a second owner in another process, and only for that call."""
    p = str(tmp_path / "x.challenge.json")
    q = str(tmp_path / "y.challenge.json")
    code = ("import sys; from challenge.worker.controller import CallLock\n"
            "sys.exit(0 if CallLock.try_acquire(sys.argv[1]) is not None else 3)\n")
    env = {**os.environ, "PYTHONPATH": "src:."}
    lk = CallLock.try_acquire(p)
    assert lk is not None and lk.held
    assert subprocess.run([sys.executable, "-c", code, p], env=env, timeout=30).returncode == 3   # busy: owner alive
    assert subprocess.run([sys.executable, "-c", code, q], env=env, timeout=30).returncode == 0   # other call: free
    lk.release()
    assert not lk.held
    assert subprocess.run([sys.executable, "-c", code, p], env=env, timeout=30).returncode == 0
    assert os.path.exists(p + ".lock") and not os.path.exists(p)              # the lock file only; never deleted


class FakeDB(FakeClient):
    """Dispatcher with the real commit semantics: the FIRST reps_committed of a call is stored; any later one (any idem
    key) answers {ok, already} without changing it, as ch_commit_reps does. `during_commit` runs inside the first
    reps_committed POST (a concurrent actor); `lose` raises after storing (the answer is lost)."""

    def __init__(self, during_commit=None, lose=0):
        super().__init__()
        self.stored = {}
        self.during_commit = during_commit
        self.lose = lose

    async def event(self, kind, call_id, payload, *, at=None, key=None):
        self.events.append({"kind": kind, "call_id": call_id, "payload": payload, "at": at,
                            "idem_key": key or f"{call_id}:{kind}"})
        if kind != "reps_committed":
            return {"ok": True, "duplicate": False}
        if call_id in self.stored:
            return {"ok": True, "duplicate": False, "already": True}
        self.stored[call_id] = payload["reps"]
        if self.during_commit is not None:
            hook, self.during_commit = self.during_commit, None
            await hook()
        if self.lose:
            self.lose -= 1
            raise DispatcherError("POST /calls/event: ReadTimeout (stored, answer lost)")
        return {"ok": True, "duplicate": False, "already": False}


def test_worker_takeover_after_check_cannot_double_commit(tmp_path):
    """A worker redispatched onto the call while the reconciler is committing it must not adopt (the reconciler holds
    the call lock across the whole replay). Otherwise it resumes counting, records a 2nd rep, gets `already` and
    marks committed:true with two reps while the dispatcher stored one."""
    now = time.time()
    t0 = now - 100
    _, path, _ = make_call(tmp_path, t0, rep_ts=(30.0,), outcome="pass", invalid_at=())
    set_fields(path, worker_pid=dead_pid())
    worker = {}

    async def takeover():
        clock = Clock(now)
        c = CompetitionCall("call-1", "line-1", None, db, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda *a: None,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        worker["accepted"] = await c.start()
        if worker["accepted"]:
            clock.t = now + 1
            c.on_rep(valid_rep(), now + 1)
            clock.t = t0 + 195
            await c.end("complete")
        worker["call"] = c

    db = FakeDB(during_commit=takeover)
    out = run(rec(tmp_path, db, Clock(now), stale_s=50).run_once())
    stored = [r["t"] for r in db.stored["call-1"]]
    assert stored == [30.0]
    d = load(path)
    assert [r["t"] for r in d["reps"]] == stored or d["committed"] is False   # never committed:true over other reps
    assert d["committed"] is True and [r["t"] for r in d["reps"]] == stored
    assert worker["accepted"] is False and worker["call"].decision == "error"     # refused: the reconciler owns it
    assert out["replayed"][0]["committed"] is True
    assert CallLock.try_acquire(path) is not None                                # released after the write-back


def test_lock_timeout_then_crash_recovers_every_rep(tmp_path, monkeypatch):
    """Lock contention elsewhere (another call's owner, a reconciler run) never touches a worker's saves: every rep is
    written straight to its checkpoint (no lock per write, no timeout, no side file); the worker then dies and the
    reconciler commits every rep."""
    t0 = time.time() - 1000
    clock = Clock(t0)
    alerts = []
    other = CallLock.try_acquire(checkpoint_path("other-call", str(tmp_path)))
    run_lock = open(tmp_path / rs.LOCK_NAME, "a")
    import fcntl
    fcntl.flock(run_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, FakeClient(), clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda cnd, d: alerts.append(cnd),
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        for t in (30.0, 40.0):
            clock.t = t0 + t
            c.on_rep(valid_rep(), t0 + t)
        return c

    c = run(worker())
    path = checkpoint_path("call-1", str(tmp_path))
    assert [r["t"] for r in load(path)["reps"]] == [30.0, 40.0] and not c.unsaved and alerts == []
    assert not [n for n in os.listdir(tmp_path) if n.endswith((".pending", ".tmp", ".claim"))]
    run_lock.close()
    other.release()
    c.lock.release()                                                  # ... and the worker dies here
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] is True
    assert [r["t"] for r in client.events[0]["payload"]["reps"]] == [30.0, 40.0]
    d = load(path)
    assert d["committed"] is True and [r["t"] for r in d["reps"]] == [30.0, 40.0]


def test_pending_only_checkpoint_is_found(tmp_path, monkeypatch):
    """Only <call>.challenge.json files are checkpoints: stray side files (an old .pending, a tmp file) are never read
    as one, never replayed, and left as they are."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    stray = load(path)
    stray["reps"] = []
    with open(path + ".pending", "w") as f:
        json.dump(stray, f)
    (tmp_path / ".ckpt-x.tmp").write_text("{")
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] is True and os.path.exists(path)
    assert len(client.events[0]["payload"]["reps"]) == 3                   # the checkpoint's reps, not the stray's
    assert load(path + ".pending")["reps"] == [] and (tmp_path / ".ckpt-x.tmp").read_text() == "{"


def test_end_retries_a_failed_save_before_returning(tmp_path, monkeypatch):
    """A failed checkpoint save is never ignored: end() retries it with backoff before returning (and only then
    releases the call lock); if it keeps failing, end() says persisted:false and alerts checkpoint_unsaved."""
    from challenge.worker import controller as ctl
    real = ctl.write_json_atomic
    fail = {"n": 0}

    def flaky(path, data, **kw):                    # the disk fills up when the final (committed) state is saved
        if fail["n"] > 0 and path.endswith(".challenge.json") and data.get("committed"):
            fail["n"] -= 1
            raise OSError(28, "No space left on device")
        return real(path, data, **kw)

    monkeypatch.setattr(ctl, "write_json_atomic", flaky)
    t0 = time.time() - 1000
    clock = Clock(t0)
    sleeps = []

    async def fake_sleep(dt):
        sleeps.append(dt)

    async def worker(call_id, failures, alerts):
        c = CompetitionCall(call_id, "line-1", None, FakeClient(), clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda cnd, d: alerts.append(cnd), sleep=fake_sleep,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        fail["n"] = failures
        res = await c.end("complete")
        return res, c

    alerts = []
    res, c = run(worker("call-1", 3, alerts))     # the final save and 2 retries fail, the 3rd retry lands
    assert res["committed"] is True and res["persisted"] is True and not c.unsaved
    assert sleeps == [0.05, 0.1, 0.2] and alerts.count("checkpoint_write_failed") == 3
    assert load(checkpoint_path("call-1", str(tmp_path)))["committed"] is True
    assert c.lock is None and CallLock.try_acquire(checkpoint_path("call-1", str(tmp_path))) is not None

    sleeps.clear()
    alerts = []
    res, c = run(worker("call-2", 100, alerts))
    assert res["persisted"] is False and "checkpoint_unsaved" in alerts and c.unsaved
    assert len(sleeps) == 6 and load(checkpoint_path("call-2", str(tmp_path)))["committed"] is False   # on disk: older


# ------------------------------------------------------------------ rv-32c regressions (fencing by the per-call lock)
def test_late_rep_during_stalled_publish_is_never_hidden(tmp_path):
    """The worker's own commit stalls (its sealed end() is waiting on the dispatcher) long past any grace period: the
    reconciler cannot run while the worker lives, so a late rep the worker records then is kept, never hidden by a
    replay marking the call committed."""
    t0 = time.time() - 1000
    clock = Clock(t0)
    rclient, rec_out = FakeClient(), {}
    holder = {}

    async def stall():
        rec_out["run"] = await rec(tmp_path, rclient, Clock(time.time() + 3600)).run_once()
        holder["c"].on_rep(valid_rep(), t0 + 100)                    # a late rep arrives while the POST stalls

    db = FakeDB(during_commit=stall)

    async def worker():
        c = CompetitionCall("call-1", "line-1", None, db, clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda *a: None,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        holder["c"] = c
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        return await c.end("complete")

    res = run(worker())
    assert rclient.events == []                                                  # the reconciler sent nothing
    assert rec_out["run"]["skipped"] == {"call-1": "owner alive"} and rec_out["run"]["replayed"] == []
    d = load(checkpoint_path("call-1", str(tmp_path)))
    assert len(d["late_reps"]) == 1 and d["committed"] is False and res["committed"] is False   # kept for review


def test_lost_response_then_already_is_a_conflict(tmp_path):
    """The dispatcher stored a replay's reps but the answer was lost; the retry gets `already`. Nothing proves the
    stored payload is this one (only a 2xx answer is recorded as acked), so it is a conflict, not a success."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    db, alerts = FakeDB(lose=1), []
    now = time.time()
    out = run(rec(tmp_path, db, Clock(now), alerts=alerts).run_once())
    assert out["replayed"][0]["committed"] is False and rs.read_ledger(path) == []        # no ack, no proof
    out = run(rec(tmp_path, db, Clock(now + 3600), alerts=alerts).run_once())
    assert out["replayed"][0]["committed"] is False and out["replayed"][0]["error"] == "conflict"
    d = load(path)
    assert d["committed"] is False and d["sent"]["reps_committed"] is False and d["reconcile"]["conflict"]
    assert os.path.exists(path + rs.CONFLICT_SUFFIX) and "commit_conflict" in [a for a, _ in alerts]
    assert [e["kind"] for e in db.events] == ["reps_committed", "reps_committed"]          # call_ended never sent


def test_paused_reconciler_cannot_be_overtaken_by_adopting_worker(tmp_path, monkeypatch):
    """The reconciler stalls in its replay for hours (no expiry can hand the call over): a worker restarted into the
    call meanwhile refuses to adopt it, because the reconciler still holds the call lock."""
    now = time.time()
    t0 = now - 100
    _, path, _ = make_call(tmp_path, t0, rep_ts=(30.0,), outcome="pass", invalid_at=())
    set_fields(path, worker_pid=dead_pid())
    real_time = time.time
    worker = {}

    async def paused_then_takeover():
        monkeypatch.setattr(time, "time", lambda: real_time() + 6 * 3600)      # the replay is paused for 6 h
        try:
            c = CompetitionCall("call-1", "line-1", None, FakeClient(), clock=Clock(now), checkpoint_dir=str(tmp_path),
                                hangup_mode="leave_room", alert=lambda *a: None,
                                liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
            worker["accepted"], worker["decision"] = await c.start(), c.decision
        finally:
            monkeypatch.setattr(time, "time", real_time)

    db = FakeDB(during_commit=paused_then_takeover)
    out = run(rec(tmp_path, db, Clock(now), stale_s=50).run_once())
    assert worker == {"accepted": False, "decision": "error"}
    assert out["replayed"][0]["committed"] is True and load(path)["committed"] is True
    assert [r["t"] for r in db.stored["call-1"]] == [r["t"] for r in load(path)["reps"]] == [30.0]


def test_concurrent_call_setups_never_rejected_while_reconciling(tmp_path, monkeypatch):
    """60 first-time calls are set up (each in its own thread and loop) while the reconciler is inside a slow
    replay write-back: per-call locks never contend across calls, so no call is rejected."""
    _, dead, _ = make_call(tmp_path, time.time() - 1000, call_id="dead-call")
    set_fields(dead, worker_pid=dead_pid())
    inside, done = threading.Event(), threading.Event()
    real_write = rs.write_json_atomic

    def slow_write(path, data, **kw):
        inside.set()
        time.sleep(1.5)                                                # a slow disk while the reconciler writes
        return real_write(path, data, **kw)

    monkeypatch.setattr(rs, "write_json_atomic", slow_write)
    rec_out = {}

    def reconcile():
        try:
            rec_out["run"] = asyncio.run(rec(tmp_path, FakeClient(), Clock(time.time())).run_once())
        finally:
            done.set()

    t = threading.Thread(target=reconcile)
    t.start()
    assert inside.wait(30)
    results = {}

    def setup(i):
        async def go():
            c = CompetitionCall(f"fresh-{i}", "line-1", None, FakeClient(), clock=Clock(time.time()),
                                checkpoint_dir=str(tmp_path), hangup_mode="leave_room", alert=lambda *a: None,
                                liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
            ok = await c.start()
            results[i] = (ok, c.decision, c.reason)
            if c.lock is not None:
                c.lock.release()
        asyncio.run(go())

    threads = [threading.Thread(target=setup, args=(i,)) for i in range(60)]
    for th in threads:
        th.start()
    for th in threads:
        th.join(60)
    t.join(60)
    assert len(results) == 60 and all(v[0] is True and v[1] == "accept" for v in results.values()), \
        {i: v for i, v in results.items() if v[0] is not True}
    assert rec_out["run"]["replayed"][0]["call_id"] == "dead-call" and load(dead)["committed"] is True


SIGKILL_WORKER = r"""
import asyncio, sys, time
from challenge.worker.controller import CompetitionCall

class Disp:
    async def start_call(self, call_id, line_id, handle=None, *, deadline_s=None):
        return {"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None}
    async def event(self, kind, call_id, payload, *, at=None, key=None):
        return {"ok": True, "duplicate": False}

class Lc:
    started = active = False
    def schedule(self, t0): return t0 + 1e9
    def due(self, t): return False
    def windows(self): return []
    def on_frame(self, f): pass
    def on_rep(self, t): pass
    def finish(self, t): return "fail"

async def main():
    t0 = time.time() - 1000
    c = CompetitionCall("call-k", "line-1", None, Disp(), clock=lambda: t0, checkpoint_dir=sys.argv[1],
                        hangup_mode="leave_room", liveness_factory=lambda rng, thr: Lc())
    assert await c.start()
    c.on_rep({"valid": True, "reject_reasons": [], "metrics": {}}, t0 + 30)
    print("owned", flush=True)
    await asyncio.sleep(3600)

asyncio.run(main())
"""


def test_dead_worker_lock_is_acquirable_after_sigkill(tmp_path):
    """A real worker process owns a call and is killed with SIGKILL mid-call: the kernel releases its lock, and the
    reconciler, refused while it lived, then recovers the call."""
    p = subprocess.Popen([sys.executable, "-c", SIGKILL_WORKER, str(tmp_path)], stdout=subprocess.PIPE,
                         env={**os.environ, "PYTHONPATH": "src:."}, text=True)
    try:
        assert p.stdout.readline().strip() == "owned"
        path = checkpoint_path("call-k", str(tmp_path))
        assert CallLock.try_acquire(path) is None                              # alive: busy
        client = FakeClient()
        out = run(rec(tmp_path, client, Clock(time.time())).run_once())
        assert out["skipped"] == {"call-k": "owner alive"} and client.events == []
        p.send_signal(signal.SIGKILL)
        p.wait(30)
        assert p.returncode == -signal.SIGKILL
        out = run(rec(tmp_path, client, Clock(time.time())).run_once())
        assert out["replayed"][0]["committed"] is True
        assert [r["t"] for r in client.events[0]["payload"]["reps"]] == [30.0]
        assert CallLock.try_acquire(path) is not None                          # free after the replay
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(30)


# ------------------------------------------------------------------ rv-32d: ownership outlives a cancelled replay
def _strip_lock_protocol(path, **kw):
    d = load(path)
    d.pop("lock_protocol", None)
    d["v"] = 1
    d.update(kw)
    with open(path, "w") as f:
        json.dump(d, f)


def test_cancelled_replay_keeps_the_call_lock_until_its_send_stops(tmp_path):
    """The reconciler run is cancelled mid-send and the send does not stop at once (an HTTP write in flight): the
    call lock must stay held until the commit task has really finished, so no other owner (a restarted worker, the
    next reconciler run) can enter while it can still send or write."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    seen = {"cancels": 0}

    class Stubborn(FakeClient):
        async def event(self, kind, call_id, payload, *, at=None, key=None):
            self.events.append({"kind": kind, "call_id": call_id, "payload": payload})
            seen["in_send"].set()
            while not seen["gate"].is_set():
                try:
                    await seen["gate"].wait()
                except asyncio.CancelledError:
                    seen["cancels"] += 1                  # still in flight after the first cancel ...
                    if seen["cancels"] > 1:
                        raise                             # ... but not forever (no hang if this test fails)
            seen.setdefault("finished", []).append(kind)
            return {"ok": True, "duplicate": False}

    async def main():
        seen["in_send"], seen["gate"] = asyncio.Event(), asyncio.Event()
        task = asyncio.ensure_future(rec(tmp_path, Stubborn(), Clock(time.time()), cancel_join_s=0.2).run_once())
        await seen["in_send"].wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seen["cancels"] >= 1 and "finished" not in seen       # the inner send has not finished yet
        assert CallLock.try_acquire(path) is None                     # ... so nobody else can own the call
        probe = CompetitionCall("call-1", "line-1", None, FakeClient(), clock=Clock(time.time()),
                                checkpoint_dir=str(tmp_path), hangup_mode="leave_room", alert=lambda *a: None,
                                liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        assert await probe.start() is False and probe.reason == "call_locked"
        seen["gate"].set()
        lk = None
        for _ in range(200):
            await asyncio.sleep(0.01)
            lk = CallLock.try_acquire(path)
            if lk is not None:
                break
        assert lk is not None and seen["finished"]                    # free once the send/write finished
        lk.release()

    run(main())
    d = load(path)
    assert d["sent"]["reps_committed"] is True                         # its write landed before the lock went


def test_cancelled_replay_cancels_its_commit_task(tmp_path):
    """A cooperative send: cancelling the reconciler cancels the replay's own commit task (it is joined, not left
    running in the background), nothing is marked sent, the lock is free right after, and a later run commits."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    seen = {}

    class Hanging(FakeClient):
        async def event(self, kind, call_id, payload, *, at=None, key=None):
            seen["in_send"].set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                seen["cancelled"] = kind
                raise

    async def main():
        seen["in_send"] = asyncio.Event()
        task = asyncio.ensure_future(rec(tmp_path, Hanging(), Clock(time.time())).run_once())
        await seen["in_send"].wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert seen.get("cancelled") == "reps_committed"
        lk = CallLock.try_acquire(path)
        assert lk is not None
        lk.release()

    run(main())
    d = load(path)
    assert d["committed"] is False and d["sent"] == {"reps_committed": False, "call_ended": False}
    out = run(rec(tmp_path, FakeClient(), Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] is True


def test_worker_releases_the_call_lock_only_after_its_end_task(tmp_path):
    """Worker side: cancelling a caller of end() leaves the shielded commit running and the lock held; cancelling the
    end task itself releases the lock once that task is done."""
    clock = Clock(time.time() - 1000)
    seen = {}

    class Hanging(FakeClient):
        async def event(self, kind, call_id, payload, *, at=None, key=None):
            if kind == "call_started":
                return {"ok": True}
            seen["in_send"].set()
            await asyncio.Event().wait()

    async def main():
        seen["in_send"] = asyncio.Event()
        c = CompetitionCall("call-1", "line-1", None, Hanging(), clock=clock, checkpoint_dir=str(tmp_path),
                            hangup_mode="leave_room", alert=lambda *a: None,
                            liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
        clock.t = time.time()
        assert await c.start()
        c.seal()
        caller = asyncio.ensure_future(c.end("complete"))
        await seen["in_send"].wait()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        await asyncio.sleep(0.01)
        assert not c._end_task.done() and c.lock is not None and c.lock.held
        assert CallLock.try_acquire(c.path) is None
        c._end_task.cancel()
        await asyncio.wait({c._end_task})
        await asyncio.sleep(0)
        assert c.lock is None
        lk = CallLock.try_acquire(c.path)
        assert lk is not None
        lk.release()

    run(main())


# ------------------------------------------------------------------ rv-32d: quarantine and metadata on adoption
def _worker(tmp_path, disp, clock, alerts=None):
    return CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path),
                           hangup_mode="leave_room", alert=(lambda c, d: alerts.append(c)) if alerts is not None
                           else (lambda *a: None), liveness_factory=lambda rng, thr: StubLiveness(rng, thr))


def test_adoption_of_a_quarantined_call_is_refused(tmp_path):
    """A call with <ckpt>.conflict.json is under admin review: a redispatched worker fails closed for it (alert),
    never adopts or rewrites its checkpoint, and lets the lock go."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    out = run(rec(tmp_path, FakeClient({"reps_committed": [{"ok": True, "already": True}]}), Clock(time.time())).run_once())
    assert out["replayed"][0]["error"] == "conflict" and os.path.exists(path + rs.CONFLICT_SUFFIX)
    before = open(path, "rb").read()
    disp, alerts = FakeClient(), []

    async def go():
        c = _worker(tmp_path, disp, Clock(time.time()), alerts)
        return c, await c.start()

    c, ok = run(go())
    assert ok is False and c.decision == "error" and c.reason == "call_conflict" and "call_conflict" in alerts
    assert c.adopted is False and disp.kinds() == [] and open(path, "rb").read() == before
    lk = CallLock.try_acquire(path)
    assert lk is not None
    lk.release()


def test_adoption_keeps_the_reconcile_and_ledger_metadata(tmp_path):
    """A worker adopting a checkpoint the reconciler worked on keeps its reconcile block and the acked ledger."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    out = run(rec(tmp_path, FakeClient({"call_ended": [DispatcherError("down")]}), Clock(time.time())).run_once())
    assert out["replayed"][0]["committed"] is False
    rc, ledger = load(path)["reconcile"], rs.read_ledger(path)
    assert rc["failures"] == 1 and rc["next_try_t"] and [e["acked"] for e in ledger] == [True]
    disp = FakeClient()

    async def go():
        c = _worker(tmp_path, disp, Clock(time.time()))
        ok = await c.start()                              # the call time is over: it resumes the end and leaves
        while c._bg:
            await asyncio.gather(*list(c._bg))
        return c, ok

    c, ok = run(go())
    assert ok is False and c.adopted is True and disp.kinds() == ["call_ended"]
    d = load(path)
    assert d["committed"] is True and d["reconcile"] == rc and d["lock_protocol"] == 1 and d["v"] == 2
    assert rs.read_ledger(path) == ledger                 # nothing resent, nothing dropped


def test_worker_already_without_an_acked_digest_is_a_conflict(tmp_path):
    """The worker's own reps_committed answered already/duplicate with nothing acked for this call: a conflict
    (never committed:true), recorded for admin review; a fresh 2xx is the normal success and records the digest."""
    for i, answer in enumerate(({"ok": True, "duplicate": False, "already": True},
                                {"ok": False, "duplicate": False, "reason": "already"},
                                {"ok": True, "duplicate": True})):
        d = tmp_path / f"r{i}"
        t0 = time.time()
        clock = Clock(t0)
        disp, alerts = FakeClient({"reps_committed": [answer]}), []

        async def go():
            c = _worker(d, disp, clock, alerts)
            assert await c.start()
            clock.t = t0 + 30
            c.on_rep(valid_rep(), t0 + 30)
            clock.t = t0 + 195
            return c, await c.end("complete")

        c, res = run(go())
        path = checkpoint_path("call-1", str(d))
        ck = load(path)
        assert res["committed"] is False and ck["committed"] is False and ck["sent"]["reps_committed"] is False
        assert disp.kinds() == ["reps_committed"] and "commit_conflict" in alerts
        conflict = load(path + rs.CONFLICT_SUFFIX)
        assert conflict["conflict"]["digest"] == rs.payload_digest(disp.events[-1]["payload"])
        assert rs.read_ledger(path) == [] and c.lock is None
    disp = FakeClient()
    t0 = time.time()
    clock = Clock(t0)

    async def fresh():
        c = _worker(tmp_path / "fresh", disp, clock)
        assert await c.start()
        clock.t = t0 + 195
        return await c.end("complete")

    assert run(fresh())["committed"] is True
    path = checkpoint_path("call-1", str(tmp_path / "fresh"))
    assert [e["digest"] for e in rs.read_ledger(path)] == [rs.payload_digest(disp.events[-2]["payload"])]
    assert not os.path.exists(path + rs.CONFLICT_SUFFIX)


def test_worker_acked_payload_then_lost_save_replays_as_already(tmp_path):
    """The worker got a 2xx for its reps (digest acked) and died before saving sent: the replay's `already` is proven
    by the worker's acked digest of the same sealed final payload -> committed, no conflict."""
    t0 = time.time() - 1000
    clock = Clock(t0)
    disp = FakeClient({"call_ended": [DispatcherError("down")]})

    async def go():
        c = _worker(tmp_path, disp, clock)
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 195
        await c.end("complete")

    run(go())
    path = checkpoint_path("call-1", str(tmp_path))
    set_fields(path, sent={"reps_committed": False, "call_ended": False})
    client, alerts = FakeClient({"reps_committed": [{"ok": True, "duplicate": False, "already": True}]}), []
    out = run(rec(tmp_path, client, Clock(time.time()), alerts=alerts).run_once())
    assert out["replayed"][0]["committed"] is True and "commit_conflict" not in [a for a, _ in alerts]
    assert client.events[0]["payload"] == disp.events[1]["payload"]
    assert not os.path.exists(path + rs.CONFLICT_SUFFIX)


# ------------------------------------------------------------------ rv-32d: legacy (pre-lock) checkpoints
def test_legacy_checkpoint_waits_for_grace_and_a_dead_pid(tmp_path):
    """A checkpoint without lock_protocol was written by a worker that never takes the lock: a free lock proves
    nothing. Recent mtime -> skipped; past the grace with its pid alive -> skipped; past the grace with a dead pid ->
    replayed."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    _strip_lock_protocol(path, worker_pid=dead_pid())
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time()), legacy_grace_s=900).run_once())
    assert out["replayed"] == [] and out["skipped"]["call-1"].startswith("legacy checkpoint written")
    assert client.events == [] and CallLock.try_acquire(path) is not None
    old = time.time() - 901
    _strip_lock_protocol(path, worker_pid=os.getpid())                 # a live process (this one)
    os.utime(path, (old, old))
    out = run(rec(tmp_path, client, Clock(time.time()), legacy_grace_s=900).run_once())
    assert out["skipped"] == {"call-1": "legacy owner pid alive"} and client.events == []
    _strip_lock_protocol(path, worker_pid=dead_pid())
    os.utime(path, (old, old))
    out = run(rec(tmp_path, client, Clock(time.time()), legacy_grace_s=900).run_once())
    assert out["replayed"][0]["committed"] is True and client.kinds() == ["reps_committed", "call_ended"]
    assert load(path)["lock_protocol"] == 1


def test_legacy_grace_from_env(tmp_path, monkeypatch):
    monkeypatch.delenv("RECONCILE_LEGACY_GRACE_S", raising=False)
    assert Reconciler(FakeClient(), str(tmp_path)).legacy_grace_s == rs.LEGACY_GRACE_S == 900.0
    monkeypatch.setenv("RECONCILE_LEGACY_GRACE_S", "1200")
    assert Reconciler(FakeClient(), str(tmp_path)).legacy_grace_s == 1200.0
    for bad in ("-1", "nan", "soon"):
        monkeypatch.setenv("RECONCILE_LEGACY_GRACE_S", bad)
        with pytest.raises(ValueError):
            rs.legacy_grace_from_env()
    monkeypatch.setenv("DISPATCHER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DISPATCHER_TOKEN", "t")
    assert run(rs.amain(rs.parse_args(["--once", "--dir", str(tmp_path)]))) == 2


# ------------------------------------------------------------------ rv-32e: ownership outlives a cancelled drain
def _draining_call(tmp_path, clock, alerts, drained):
    async def drain():
        drained["started"].set()
        await asyncio.Event().wait()                       # the perception feed is busy: never drains by itself

    return CompetitionCall("call-1", "line-1", None, FakeClient(), clock=clock, checkpoint_dir=str(tmp_path),
                           hangup_mode="leave_room", alert=lambda c, d: alerts.append(c), drain=drain,
                           liveness_factory=lambda rng, thr: StubLiveness(rng, thr))


def test_end_cancelled_mid_drain_seals_and_saves_before_releasing(tmp_path):
    """end() is cancelled while the drain still waits and reps are queued: the lock is held until the intake is
    sealed and saved; a rep queued before that lands in the checkpoint (as a late rep, kept for review); a rep
    delivered after the release is never written (another owner may hold the call by then)."""
    t0 = time.time() - 1000
    clock, alerts, drained = Clock(t0), [], {}

    async def main():
        drained["started"] = asyncio.Event()
        c = _draining_call(tmp_path, clock, alerts, drained)
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 100
        caller = asyncio.ensure_future(c.end("complete"))
        await drained["started"].wait()
        c.on_rep(valid_rep(), t0 + 60)                    # delivered while draining: a normal rep
        c._end_task.cancel()
        c.on_rep(valid_rep(), t0 + 70)                    # queued: the cancel is not processed yet
        assert CallLock.try_acquire(c.path) is None and c.lock is not None and not c.sealed
        await asyncio.wait({c._end_task})
        await asyncio.sleep(0)
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert c.lock is None and c.sealed and load(c.path)["sealed"] is True    # sealed and saved before the release
        assert not c.unsaved and c.disowned
        saved = open(c.path, "rb").read()
        d = json.loads(saved)
        assert d["sealed"] is True and d["committed"] is False
        assert [r["t"] for r in d["reps"]] == [30.0, 60.0, 70.0]
        lk = CallLock.try_acquire(c.path)                 # another owner may take it now ...
        assert lk is not None
        c.on_rep(valid_rep(), t0 + 80)                    # ... so this late delivery is not written
        assert open(c.path, "rb").read() == saved and "checkpoint_write_refused" in alerts
        assert [r["t"] for r in c.late_reps] == [80.0]
        lk.release()
        c.on_rep(valid_rep(), t0 + 90)                    # nobody owns it now: retaken briefly, late reps added
        d = load(c.path)
        assert [r["t"] for r in d["late_reps"]] == [80.0, 90.0] and [r["t"] for r in d["reps"]] == [30.0, 60.0, 70.0]
        assert d["committed"] is False and CallLock.try_acquire(c.path) is not None

    run(main())
    assert "commit_pending" in alerts
    client = FakeClient()
    out = run(rec(tmp_path, client, Clock(time.time())).run_once())           # sealed: replayable at once
    assert out["replayed"][0]["committed"] is False                           # the late reps keep it for review
    assert [r["t"] for r in client.events[0]["payload"]["reps"]] == [30.0, 60.0, 70.0]


def test_end_cancelled_mid_drain_with_a_failed_save_keeps_the_lock(tmp_path, monkeypatch):
    """The save after a cancelled drain fails: the lock stays held (the process exit drops it), never released over
    an unsaved state."""
    from challenge.worker import controller as ctl
    t0 = time.time() - 1000
    clock, alerts, drained = Clock(t0), [], {}
    real = ctl.write_json_atomic

    async def main():
        drained["started"] = asyncio.Event()
        c = _draining_call(tmp_path, clock, alerts, drained)
        assert await c.start()
        clock.t = t0 + 30
        c.on_rep(valid_rep(), t0 + 30)
        clock.t = t0 + 100
        asyncio.ensure_future(c.end("complete"))
        await drained["started"].wait()

        def broken(path, data):
            raise OSError("disk full")

        monkeypatch.setattr(ctl, "write_json_atomic", broken)
        c._end_task.cancel()
        await asyncio.wait({c._end_task})
        await asyncio.sleep(0)
        assert c.unsaved and c.lock is not None and c.lock.held and not c.disowned
        assert CallLock.try_acquire(c.path) is None and "checkpoint_unsaved" in alerts
        monkeypatch.setattr(ctl, "write_json_atomic", real)
        c.lock.release()                                  # the process exits

    run(main())


def test_adoption_refused_on_reconcile_conflict_without_sidecar(tmp_path):
    """The conflict sidecar write failed but the checkpoint's reconcile.conflict landed: adoption is refused all the
    same (fail closed, alert, nothing sent, checkpoint untouched)."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    out = run(rec(tmp_path, FakeClient({"reps_committed": [{"ok": True, "already": True}]}), Clock(time.time())).run_once())
    assert out["replayed"][0]["error"] == "conflict" and load(path)["reconcile"]["conflict"]
    os.replace(path + rs.CONFLICT_SUFFIX, str(tmp_path / "moved-away.json"))       # as if never written
    before = open(path, "rb").read()
    disp, alerts = FakeClient(), []

    async def go():
        c = _worker(tmp_path, disp, Clock(time.time()), alerts)
        return c, await c.start()

    c, ok = run(go())
    assert ok is False and c.reason == "call_conflict" and "call_conflict" in alerts and c.adopted is False
    assert disp.kinds() == [] and open(path, "rb").read() == before and c.lock is None
    assert run(rec(tmp_path, FakeClient(), Clock(time.time() + 7200)).run_once())["skipped"] == \
        {"call-1": "payload conflict (admin review)"}


DEADLINE_RUN = r"""
import asyncio, sys
from scripts import reconcile_sessions as rs

class Stuck:
    async def event(self, kind, call_id, payload, *, at=None, key=None):
        print("in_send", flush=True)
        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass                                       # never lets a cancellation through

rs.arm_deadline(float(sys.argv[2]), rs.log_alert)
asyncio.run(rs.Reconciler(Stuck(), sys.argv[1], cancel_join_s=0.1).run_once())
print("returned", flush=True)
"""


def test_once_deadline_exits_and_drops_the_call_lock(tmp_path):
    """A send that never finishes and swallows every cancellation: the --once watchdog ends the process with exit 3
    after RECONCILE_MAX_RUN_S, and the kernel drops the call lock it held."""
    _, path, _ = make_call(tmp_path, time.time() - 1000)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(["src", "."]))
    p = subprocess.Popen([sys.executable, "-c", DEADLINE_RUN, str(tmp_path), "1.5"], env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "in_send"
        assert CallLock.try_acquire(path) is None                       # the stuck run owns the call
        out, err = p.communicate(timeout=30)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
    assert p.returncode == rs.EXIT_DEADLINE == 3 and "returned" not in out
    assert "RECONCILE_MAX_RUN_S" in err and "reconciler_deadline" in err
    lk = CallLock.try_acquire(path)
    assert lk is not None
    lk.release()
    assert load(path)["committed"] is False


def test_amain_once_arms_and_disarms_the_deadline(tmp_path, monkeypatch):
    armed = []

    class Timer:
        cancelled = False

        def cancel(self):
            self.cancelled = True

    class Client:
        async def aclose(self):
            pass

    def arm(seconds, alert):
        armed.append(seconds)
        armed.append(Timer())
        return armed[-1]

    monkeypatch.setattr(rs, "arm_deadline", arm)
    monkeypatch.setattr(rs.DispatcherClient, "from_env", classmethod(lambda cls: Client()))
    monkeypatch.setenv("DISPATCHER_URL", "http://127.0.0.1:9")
    monkeypatch.setenv("DISPATCHER_TOKEN", "t")
    monkeypatch.delenv("RECONCILE_MAX_RUN_S", raising=False)
    monkeypatch.delenv("RECONCILE_LEGACY_GRACE_S", raising=False)
    assert run(rs.amain(rs.parse_args(["--once", "--dir", str(tmp_path)]))) == 0
    assert armed[0] == rs.MAX_RUN_S == 50.0 and armed[1].cancelled
    monkeypatch.setenv("RECONCILE_MAX_RUN_S", "20")
    assert run(rs.amain(rs.parse_args(["--once", "--dir", str(tmp_path)]))) == 0 and armed[2] == 20.0
    for bad in ("0", "-5", "inf", "soon"):
        monkeypatch.setenv("RECONCILE_MAX_RUN_S", bad)
        assert run(rs.amain(rs.parse_args(["--once", "--dir", str(tmp_path)]))) == 2
    assert len(armed) == 4


@pytest.mark.parametrize("ckpt,live_cfg,want", [
    ({"liveness_enabled": True, "judge_version": "j3"}, None, True),           # ran with the challenge on
    ({"liveness_enabled": False, "judge_version": "j3"}, {"liveness_enabled": True}, False),  # ran with it off
    ({"judge_version": "j2"}, None, True),                                     # pre-flag checkpoint: challenge was on
    ({"judge_version": "j3"}, None, False),                                    # j3 without the key: today's default
])
def test_adopted_call_keeps_the_liveness_setting_it_ran_with(tmp_path, ckpt, live_cfg, want):
    # A recovery must not void (or un-void) a call's reps by today's liveness config (merge of task 32 with j3).
    c = CompetitionCall("call-1", "line-1", None, FakeClient(), judge_cfg=live_cfg, clock=Clock(time.time()),
                        checkpoint_dir=str(tmp_path), hangup_mode="leave_room")
    c._adopt({"call_id": "call-1", "line_id": "line-1", "t0": time.time() - 100, "reps": [], **ckpt})
    assert c.liveness_enabled() is want


# ------------------------------------------------------------------ rv-39: early commit (REVEAL_MODE=video)
def _early_worker(tmp_path, disp, clock):
    async def hook(seconds, wait):
        await wait()
    c = CompetitionCall("call-1", "line-1", None, disp, clock=clock, checkpoint_dir=str(tmp_path), hangup_mode="leave_room",
                        reveal_mode="video", reveal=hook, alert=lambda *a: None,
                        liveness_factory=lambda rng, thr: StubLiveness(rng, thr))
    return c


async def _early_commit(tmp_path, disp, t0):
    clock = Clock(t0)
    c = _early_worker(tmp_path, disp, clock)
    assert await c.start()
    clock.t = t0 + 30
    c.on_rep(valid_rep(), t0 + 30)
    clock.t = t0 + 181
    c.liveness_result = "pass"
    c.tick()
    for _ in range(100):
        await asyncio.sleep(0)
    assert c.sent["reps_committed"] and c.ended_at is None
    return c, clock


def test_early_commit_checkpoint_keeps_the_intake_sealed_across_a_restart(tmp_path):
    t0 = time.time() - 100
    disp = FakeClient()

    async def go():
        c, clock = await _early_commit(tmp_path, disp, t0)
        d = load(checkpoint_path("call-1", str(tmp_path)))
        assert d["sealed"] is True and d["final"] is False and d["commit_t"] == t0 + c.count_s
        c._release_lock()                                  # the first process is gone
        c2 = _early_worker(tmp_path, disp, Clock(t0 + 185))
        assert await c2.start() and c2.adopted and c2.sealed and c2.sent["reps_committed"]
        c2.on_rep(valid_rep(), t0 + 100)                   # a delayed in-window rep after the restart
        assert len(c2.late_reps) == 1 and c2.committed is False
        await c2.end("complete")
        return c2
    c2 = run(go())
    assert c2.committed is False and len(c2.late_reps) == 1 and c2.sent == {"reps_committed": True, "call_ended": True}
    assert [e["kind"] for e in disp.events].count("reps_committed") == 1


def test_early_commit_crash_between_ack_and_saved_sent_replays_the_same_payload(tmp_path):
    t0 = time.time() - 1000
    disp = FakeClient()

    async def go():
        c, _ = await _early_commit(tmp_path, disp, t0)
        c._release_lock()
    run(go())
    path = checkpoint_path("call-1", str(tmp_path))
    set_fields(path, sent={"reps_committed": False, "call_ended": False})      # the ack was never saved
    client, alerts = FakeClient({"reps_committed": [{"ok": True, "duplicate": False, "already": True}]}), []
    out = run(rec(tmp_path, client, Clock(time.time()), alerts=alerts).run_once())
    assert out["replayed"][0]["committed"] is True and "commit_conflict" not in [a for a, _ in alerts]
    first = next(e for e in disp.events if e["kind"] == "reps_committed")
    assert client.events[0]["payload"] == first["payload"]                      # byte-identical: same ended_at
    assert client.kinds() == ["reps_committed", "call_ended"]
    assert not os.path.exists(path + rs.CONFLICT_SUFFIX)
    assert load(path)["sent"] == {"reps_committed": True, "call_ended": True}
