"""Competition call controller (task 30, CONTRACTS C6/C7): fake dispatcher (httpx MockTransport), fake clock, fake say,
a scripted LivenessChallenge stand-in (the controller only uses its schedule/due/start/poll/finish/on_frame/windows
interface), and one full simulated call through the worker path with a no-media-on-disk guard."""
from __future__ import annotations

import asyncio
import builtins
import json
import os
import random
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import numpy as np
import pytest

from challenge.judge.cues import CUES
from challenge.judge.gates import JUDGE_VERSION
from challenge.judge.metrics import FrameObs
from challenge.worker import controller as ctl
from challenge.worker.client import DispatcherClient, DispatcherError
from challenge.worker.controller import CompetitionCall, UnsupportedMode

T0 = 1_760_000_000.0          # fake wall clock start (epoch seconds)


# ------------------------------------------------------------------ fakes
class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    async def sleep(self, dt):
        self.t += max(0.0, dt)
        await asyncio.sleep(0)


class Dispatcher:
    """MockTransport handler: records every request; `start` is the /calls/start response, `down` makes paths fail."""

    def __init__(self, start=None, down=(), fail_status=None, refuse=()):
        self.start = start or {"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None}
        self.down = set(down)               # paths that raise a connect error
        self.fail_status = dict(fail_status or {})   # path -> list of statuses to return before succeeding
        self.refuse = set(refuse)           # event kinds answered {ok: false}
        self.requests = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content or b"{}")
        self.requests.append((req.url.path, body, dict(req.headers)))
        if req.url.path in self.down:
            raise httpx.ConnectError("dispatcher down", request=req)
        if self.fail_status.get(req.url.path):
            return httpx.Response(self.fail_status[req.url.path].pop(0))
        if req.url.path == "/calls/heartbeat":
            return httpx.Response(200, json={"ok": True})
        if req.url.path == "/calls/start":
            return httpx.Response(200, json=self.start)
        if req.url.path == "/calls/event":
            if body["kind"] in self.refuse:
                return httpx.Response(200, json={"ok": False, "duplicate": False, "reason": "not_accepted"})
            return httpx.Response(200, json={"ok": True, "duplicate": False})
        return httpx.Response(404)

    def events(self):
        return [(b["kind"], b["idem_key"]) for p, b, _ in self.requests if p == "/calls/event"]

    def paths(self):
        return [p for p, _, _ in self.requests]


class FakeLiveness:
    """Scripted stand-in: fires at `fire` (call clock, clamped into the window it was given), cue `cue`, resolves
    `outcome` ('pass'|'fail'|'skipped') `after` seconds after the cue; 'skipped' turns 'fail' once a rep was earned
    (on_rep), as C7.l. `go`: a FREEZE-like go cue that many seconds after the cue, shrinking the deadline to go + 2.
    Records frames, reps and the window it got."""
    made: list = []

    def __init__(self, rng, thr, outcomes, fire=None, cue="challenge_lift_hold", after=2.0, timeout=4.0, go=None,
                 go_cue="challenge_go", frame_error=None):
        self.thr, self.outcomes, self.fire_req, self.cue, self.after, self.timeout = thr, outcomes, fire, cue, after, timeout
        self.go, self.go_said, self.go_cue, self.frame_error = go, False, go_cue, frame_error
        self.fire_t = None
        self.attempts = []
        self.result = None
        self.frames = []
        self.reps = []
        self.finished_at = None
        FakeLiveness.made.append(self)

    def on_rep(self, t):
        self.reps.append(t)

    def _no_pass(self):
        return "fail" if self.reps else "skipped"

    def schedule(self, call_t0):
        lo, hi = self.thr["liveness_window_s"]
        off = lo if self.fire_req is None else min(max(self.fire_req - call_t0, lo), hi)
        self.fire_t = call_t0 + off
        return self.fire_t

    def due(self, t):
        return not self.attempts and self.result is None and t >= self.fire_t

    @property
    def started(self):
        return bool(self.attempts)

    @property
    def active(self):
        return bool(self.attempts) and self.result is None

    def start(self, t):
        self.attempts.append((t, t + self.timeout))
        return self.cue

    def poll(self, t):
        if self.result is not None:
            return self.result, None
        start = self.attempts[-1][0]
        if self.go is not None and not self.go_said and t >= start + self.go:
            self.go_said = True
            self.attempts[-1] = (start, t + 2.0)
            return "go", self.go_cue
        if t < start + self.after:
            return "pending", None
        self.result = self.outcomes if self.outcomes != "skipped" else self._no_pass()
        return self.result, {"pass": "challenge_passed", "fail": "challenge_failed", "skipped": None}[self.result]

    def finish(self, t_end):
        self.finished_at = t_end
        if self.result is None:
            self.result = self._no_pass()
        return self.result

    def on_frame(self, f):
        if self.frame_error is not None and len(self.frames) >= 1:
            raise self.frame_error
        self.frames.append(f)

    def windows(self):
        return list(self.attempts)


def factory(*outcomes, fire=None, **kw):
    """Liveness factory: the k-th challenge made in a call resolves with outcomes[k] (last one repeats)."""
    seq = list(outcomes)
    n = {"i": 0}

    def make(rng, thr):
        o = seq[min(n["i"], len(seq) - 1)]
        n["i"] += 1
        return FakeLiveness(rng, thr, o, fire=fire if n["i"] == 1 else None, **kw)
    return make


class Rig:
    def __init__(self, tmp_path, disp=None, liveness=None, hangup="unverified", reveal="audio_only", start=None,
                 judge_cfg=None, **kw):
        self.clock = Clock()
        self.disp = disp or Dispatcher(start=start)
        self.client = DispatcherClient("http://dispatcher", "tok", timeout=3, retries=3, backoff_s=0.5,
                                       transport=httpx.MockTransport(self.disp), sleep=self.clock.sleep, monotonic=self.clock)
        self.said, self.left, self.windows, self.alerts = [], [], [], []
        self.dir = str(tmp_path / "sessions")
        # the liveness challenge is off by default since j3 (thresholds liveness_enabled); these rigs test it ON
        cfg = {"liveness_enabled": True} if judge_cfg is None else judge_cfg
        self.call = CompetitionCall("call-1", "line-1", "+15550001", self.client, cfg, clock=self.clock,
                                    say=lambda k, text, urgent: self.said.append((round(self.clock.t - T0, 2), k, urgent)),
                                    leave=lambda why: self.left.append((round(self.clock.t - T0, 2), why)),
                                    update_challenge_window=lambda a, b: self.windows.append((a - T0, b - T0)),
                                    hangup_mode=hangup, reveal_mode=reveal, checkpoint_dir=self.dir,
                                    rng=random.Random(7), liveness_factory=liveness or factory("pass", fire=60.0),
                                    alert=lambda c, d: self.alerts.append(c), sleep=self.clock.sleep, **kw)

    def keys(self):
        return [k for _, k, _ in self.said]

    def ckpt(self):
        with open(self.call.path) as f:
            return json.load(f)

    async def advance(self, to_rel, step=0.25):
        """Tick every `step` up to call time to_rel; returns True if the call became due to end."""
        while self.clock.t - T0 < to_rel - 1e-9:
            self.clock.t = min(self.clock.t + step, T0 + to_rel)
            if self.call.tick():
                return True
            await asyncio.sleep(0)
        return False


def rep_ev(valid=True, cue=None, reasons=None, in_challenge=False, n=1):
    return {"type": "rep", "n": n, "valid": valid, "reject_reasons": reasons if reasons is not None else ([] if valid else ["too_shallow"]),
            "metrics": {"min_elbow_deg_l": 80.0, "min_elbow_deg_r": None, "top_elbow_deg": float("nan"),
                        "persons_in_frame": np.int64(1), "torso_ok": np.bool_(True), "side": "left",
                        "classifier_labels": [], "cadence_rpm": 30.0},
            "judge_version": "j1", "cue": cue, "in_challenge": in_challenge}


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ gatekeeper
def test_reject_path_cue_leave_and_nothing_recorded(tmp_path):
    async def go():
        r = Rig(tmp_path, start={"decision": "reject", "user_id": None, "reason": "not_your_turn", "cue": "not_your_turn"})
        ok = await r.call.start()
        r.call.on_rep(rep_ev(), t=T0 + 1)
        assert r.call.tick(T0 + 200) is False
        out = await r.call.end("caller left")
        return r, ok, out
    r, ok, out = run(go())
    assert ok is False and r.call.decision == "reject"
    assert r.keys() == ["not_your_turn"]
    assert len(r.left) == 1 and r.left[0][0] <= 5.0
    assert r.disp.paths() == ["/calls/start"]
    assert r.disp.requests[0][1] == {"call_id": "call-1", "line_id": "line-1", "handle": "+15550001"}
    assert r.disp.requests[0][2]["x-brodie-token"] == "tok"
    assert out["recorded"] is False and not os.path.exists(r.call.path) and not os.path.exists(r.dir)


def test_dispatcher_down_at_start_fails_closed(tmp_path):
    async def go():
        r = Rig(tmp_path, disp=Dispatcher(down={"/calls/start"}))
        ok = await r.call.start()
        await r.call.end("x")
        return r, ok
    r, ok = run(go())
    assert ok is False and r.call.decision == "error"
    assert r.alerts == ["dispatcher_unreachable"]
    # P1-2: the short try_again cue instead of silence (never a misleading not_your_turn), then the hang-up
    assert r.keys() == ["try_again"] and "not_your_turn" not in r.keys()
    assert r.said[0][0] >= ctl.START_DEADLINE_S - 0.5                # retried for the whole widened deadline first
    assert len(r.left) == 1 and r.left[0][0] <= ctl.START_DEADLINE_S + ctl.FAIL_CUE_S + ctl.FAIL_ENDED_S + 0.5
    starts = [p for p in r.disp.paths() if p == "/calls/start"]
    assert len(starts) >= 4                                          # retried within the deadline (same call id)
    assert {b["call_id"] for p, b, _ in r.disp.requests if p == "/calls/start"} == {"call-1"}
    # a best-effort call_ended (0 reps) before the leave, so a dispatcher that did commit in_call frees the line
    assert r.disp.events() == [("call_ended", "call-1:call_ended")]
    ended = [b for p, b, _ in r.disp.requests if p == "/calls/event"][0]["payload"]
    assert ended["rep_count"] == 0 and ended["ended_at"] == ended["count_end_at"]
    assert r.disp.paths()[-1] == "/calls/event"
    assert not os.path.exists(r.call.path)


def test_start_retries_503_with_same_call_id(tmp_path):
    async def go():
        d = Dispatcher(fail_status={"/calls/start": [503, 502]})
        r = Rig(tmp_path, disp=d)
        return r, await r.call.start()
    r, ok = run(go())
    assert ok is True and r.disp.paths() == ["/calls/start"] * 3 + ["/calls/event"]
    assert {b["call_id"] for p, b, _ in r.disp.requests if p == "/calls/start"} == {"call-1"}


def test_unsupported_modes(monkeypatch):
    # chert_api is refused without credentials; keep this hermetic if a dev shell exports them
    monkeypatch.delenv("CHERT_FACETIME_TOKEN", raising=False)
    monkeypatch.delenv("CHERT_PROJECT_ID", raising=False)
    with pytest.raises(UnsupportedMode, match="chert_api"):
        CompetitionCall("c", "l", None, None, hangup_mode="chert_api")
    with pytest.raises(UnsupportedMode):
        CompetitionCall("c", "l", None, None, reveal_mode="hologram")
    assert any("FALLBACK" in n for n in ctl.check_modes("leave_room", "video"))


# ------------------------------------------------------------------ accepted call timeline
def test_accept_timeline_cues_and_commit(tmp_path):
    async def go():
        r = Rig(tmp_path, start={"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None, "power_hour_active": True,
                                 "config": {"call_count_s": 180, "call_reveal_s": 15}})
        assert await r.call.start() is True
        ck0 = r.ckpt()
        due = await r.advance(200)
        assert due
        res = await r.call.end("complete")
        return r, ck0, res
    r, ck0, res = run(go())
    t = {k: s for s, k, _ in r.said}
    assert r.keys() == ["welcome", "power_hour", "challenge_lift_hold", "challenge_passed", "thirty_left", "time_up",
                        "check_texts", "hang_up"]
    assert t["welcome"] == 0 and t["power_hour"] == 4 and t["challenge_lift_hold"] == 60 and t["thirty_left"] == 150
    assert t["time_up"] == 180 and t["check_texts"] == 181.5 and t["hang_up"] == 191
    assert r.windows == [(60.0, 64.0)]
    assert ck0["committed"] is False and ck0["user_id"] == "u1" and ck0["reps"] == []
    assert r.disp.events() == [("call_started", "call-1:call_started"), ("reps_committed", "call-1:reps_committed"),
                               ("call_ended", "call-1:call_ended")]
    assert res["committed"] is True and r.ckpt()["committed"] is True and r.ckpt()["liveness_result"] == "pass"
    ended = [b for p, b, _ in r.disp.requests if p == "/calls/event" and b["kind"] == "call_ended"][0]["payload"]
    assert ended["rep_count"] == 0
    assert datetime.fromisoformat(ended["count_end_at"]) == datetime.fromtimestamp(T0 + 180, tz=timezone.utc)


def test_run_ends_and_leaves_at_count_plus_reveal(tmp_path):
    async def go():
        r = Rig(tmp_path, hangup="leave_room")
        assert await r.call.start()
        await r.call.run(interval=0.5)
        left_before_commit = list(r.left)
        await r.call.end("x")
        return r, left_before_commit
    r, left_before_commit = run(go())
    assert left_before_commit == [(195.0, "call complete")]
    assert "hang_up" not in r.keys() and r.keys()[-2:] == ["time_up", "check_texts"]
    assert r.left == [(195.0, "call complete")]
    assert r.call.committed is True


def test_reps_after_count_end_ignored_and_checkpoint_per_rep(tmp_path):
    async def go():
        r = Rig(tmp_path)
        await r.call.start()
        sizes = []
        for i, rel in enumerate([10.0, 20.0, 179.5]):
            await r.advance(rel)
            r.call.on_rep(rep_ev(n=i + 1), t=T0 + rel)
            sizes.append(len(r.ckpt()["reps"]))
        await r.advance(180.5)
        assert r.call.on_rep(rep_ev(n=4), t=T0 + 180.2) is None   # fired after 3:00
        assert r.call.on_rep(rep_ev(n=5), t=T0 + 190.0) is None
        await r.advance(196)
        await r.call.end("complete")
        return r, sizes
    r, sizes = run(go())
    assert sizes == [1, 2, 3]
    assert not [f for f in os.listdir(r.dir) if f.endswith(".tmp")]          # atomic writes leave no temp files
    payload = [b for p, b, _ in r.disp.requests if p == "/calls/event" and b["kind"] == "reps_committed"][0]["payload"]
    assert [x["t"] for x in payload["reps"]] == [10.0, 20.0, 179.5] and r.call.ignored_reps == 2
    rep = payload["reps"][0]
    assert rep["n"] == 1 and rep["valid"] is True and rep["top_elbow_deg"] is None and rep["persons_in_frame"] == 1
    assert rep["torso_ok"] is True and "cadence_rpm" not in rep
    assert datetime.fromisoformat(rep["at"]) == datetime.fromtimestamp(T0 + 10, tz=timezone.utc)
    assert payload["liveness_result"] == "pass" and payload["judge_version"] == JUDGE_VERSION


def test_judge_cues_rate_limited_and_silent_in_challenge(tmp_path):
    async def go():
        r = Rig(tmp_path)
        await r.call.start()
        await r.advance(10)
        r.call.on_rep(rep_ev(False, cue="too_shallow"), t=T0 + 10)
        await r.advance(12)
        r.call.on_rep(rep_ev(False, cue="knees_down"), t=T0 + 12)     # inside cue_min_gap_s
        await r.advance(15)
        r.call.on_rep(rep_ev(False, cue="no_lockout"), t=T0 + 15)
        r.call.on_rep(rep_ev(False, cue="welcome"), t=T0 + 30)        # not a corrective cue
        await r.advance(61)                                            # challenge open 60..64
        r.call.on_rep(rep_ev(False, cue="hips"), t=T0 + 61)
        return r
    r = run(go())
    judge = [(s, k, u) for s, k, u in r.said if k in ctl.JUDGE_CUE_KEYS]
    assert judge == [(10, "too_shallow", False), (15, "no_lockout", False)]
    assert r.call.reps[-1]["in_challenge"] is True


# ------------------------------------------------------------------ liveness
def test_liveness_fail_voids_call(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("fail", fire=50.0))
        await r.call.start()
        await r.advance(20)
        r.call.on_rep(rep_ev(), t=T0 + 20)
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    assert "challenge_failed" in r.keys()
    payload = [b for p, b, _ in r.disp.requests if p == "/calls/event" and b["kind"] == "reps_committed"][0]["payload"]
    assert payload["liveness_result"] == "fail" and r.ckpt()["liveness_result"] == "fail"


def test_liveness_skipped_reschedules_once_and_needs_no_reps(tmp_path):
    """C7.l: 'skipped' only when no rep was earned and nobody was in frame: one reschedule, then skipped, nothing to mark."""
    FakeLiveness.made = []

    async def go():
        r = Rig(tmp_path, liveness=factory("skipped", "skipped", fire=60.0))
        await r.call.start()
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    assert len(FakeLiveness.made) == 2                                       # one reschedule, not more
    second = FakeLiveness.made[1]
    assert second.fire_t + 2 * r.call._attempt_max() <= 180                  # both attempts fit before the count ends
    payload = _payload(r.disp)
    assert payload["liveness_result"] == "skipped" and payload["reps"] == []


def test_reps_earned_turn_a_skip_into_fail_and_are_marked(tmp_path):
    FakeLiveness.made = []

    async def go():
        r = Rig(tmp_path, liveness=factory("skipped", fire=60.0))
        await r.call.start()
        for rel, ok in [(30, True), (62, True), (100, False), (170, True)]:
            await r.advance(rel)
            r.call.on_rep(rep_ev(ok), t=T0 + rel)
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    assert FakeLiveness.made[0].reps == [30.0]       # recorded reps reach lc.on_rep until it settles (fail at 62)
    assert len(FakeLiveness.made) == 1 and "challenge_failed" in r.keys()
    payload = _payload(r.disp)
    assert payload["liveness_result"] == "fail"
    by_t = {x["t"]: x for x in payload["reps"]}
    assert all(x["valid"] is False for x in payload["reps"])
    for t in (30.0, 62.0, 170.0):
        assert "liveness_fail" in by_t[t]["reject_reasons"]
    assert by_t[62.0]["in_challenge"] is True and by_t[100.0]["reject_reasons"] == ["too_shallow"]
    assert r.ckpt()["reps"] == payload["reps"]


def test_reps_after_a_fail_are_liveness_fail(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("fail", fire=50.0))
        await r.call.start()
        for rel in (20, 120):
            await r.advance(rel)
            r.call.on_rep(rep_ev(), t=T0 + rel)
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    reps = _payload(r.disp)["reps"]
    assert [x["t"] for x in reps] == [20.0, 120.0]
    assert all(x["valid"] is False and "liveness_fail" in x["reject_reasons"] for x in reps)


def test_rescheduled_challenge_knows_reps_already_earned(tmp_path):
    FakeLiveness.made = []

    async def go():
        r = Rig(tmp_path, liveness=factory("skipped", "pass", fire=60.0))
        await r.call.start()
        await r.advance(63)                                     # skipped at 62 with no reps: rescheduled
        r.call.on_rep(rep_ev(), t=T0 + 63)
        return r
    r = run(go())
    assert len(FakeLiveness.made) == 2 and FakeLiveness.made[1].reps == [63.0] and FakeLiveness.made[0].reps == []


def _no_liveness(rng, thr):
    raise AssertionError("liveness challenge built while liveness_enabled is off")


@pytest.mark.parametrize("judge_cfg,start_cfg", [
    ({}, {}),                                                            # j3 default: off
    ({"liveness_enabled": True}, {"judge_thresholds": {"liveness_enabled": False}}),   # live config turns it off
])
def test_liveness_off_every_judged_rep_counts_and_no_challenge(tmp_path, judge_cfg, start_cfg):
    async def go():
        r = Rig(tmp_path, liveness=_no_liveness, judge_cfg=judge_cfg,
                start={"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None, "config": start_cfg})
        assert await r.call.start() is True
        r.call.judge_applied()
        for i, rel in enumerate((20, 61, 62, 120)):
            await r.advance(rel)
            r.call.on_rep(rep_ev(valid=(rel != 62), n=i + 1), t=T0 + rel)
        await r.advance(196)
        res = await r.call.end("complete")
        return r, res
    r, res = run(go())
    assert r.call.liveness_enabled() is False and r.call.lc is None
    assert not [k for k in r.keys() if k.startswith("challenge_")] and r.windows == []
    assert "time_up" in r.keys() and res["committed"] is True
    body = _payload(r.disp)
    reps = body["reps"]
    assert [x["t"] for x in reps] == [20.0, 61.0, 62.0, 120.0]
    assert [x["valid"] for x in reps] == [True, True, False, True]
    assert reps[2]["reject_reasons"] == ["too_shallow"]
    assert not [x for x in reps if "liveness_fail" in x["reject_reasons"]]
    assert body["liveness_result"] == "skipped" and r.ckpt()["liveness_result"] == "skipped"


def test_go_cue_played_and_shrunk_deadline_pushed(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("pass", fire=60.0, cue="challenge_freeze", go=1.0, after=2.5, timeout=10.0))
        await r.call.start()
        await r.advance(60)
        ck_start = r.ckpt()["liveness"]["windows_s"]
        await r.advance(61)
        ck_go = r.ckpt()["liveness"]["windows_s"]
        await r.advance(63)
        return r, ck_start, ck_go
    r, ck_start, ck_go = run(go())
    t = {k: s for s, k, _ in r.said}
    assert t["challenge_freeze"] == 60 and t["challenge_go"] == 61 and "challenge_passed" in t
    assert r.windows == [(60.0, 70.0), (60.0, 63.0)]                         # same start: the judge replaces the window
    assert ck_start == [[60.0, 70.0]] and ck_go == [[60.0, 63.0]]
    assert r.call.windows() == [(60.0, 63.0)]


def test_liveness_skipped_then_pass_keeps_reps(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("skipped", "pass", fire=60.0))
        await r.call.start()
        await r.advance(150)
        r.call.on_rep(rep_ev(), t=T0 + 150)
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    assert r.call.liveness_result == "pass" and r.call.final_reps()[0]["valid"] is True
    assert r.keys().count("challenge_lift_hold") == 2 and "challenge_passed" in r.keys()


def test_liveness_window_clamped_before_count_end(tmp_path):
    FakeLiveness.made = []

    async def go():
        r = Rig(tmp_path, liveness=factory("pass"), start={"decision": "accept", "user_id": "u1", "reason": "ok",
                                                          "config": {"call_count_s": 100, "judge_thresholds": {"liveness_window_s": [95, 99]}}})
        await r.call.start()
        return r
    r = run(go())
    lo, hi = FakeLiveness.made[0].thr["liveness_window_s"]
    assert hi <= 100 - 2 * 4 and lo <= hi
    assert r.call.count_s == 100


def test_liveness_frames_on_call_clock_and_unmirrored(tmp_path):
    FakeLiveness.made = []

    async def go():
        r = Rig(tmp_path)
        img = np.zeros((33, 5), np.float32)
        img[11, 0] = 0.25
        r.call.on_frame(FrameObs(t=T0 + 1, img=img, world=None, persons=1))      # before accept: ignored
        await r.call.start()
        r.call.on_frame(FrameObs(t=T0 + 2, img=img, world=None, persons=1))
        return r
    r = run(go())
    frames = FakeLiveness.made[0].frames
    assert len(frames) == 1 and frames[0].t == 2 and frames[0].img[11, 0] == np.float32(0.25)


# ------------------------------------------------------------------ dispatcher failures at end
def test_dispatcher_down_at_end_keeps_checkpoint_uncommitted(tmp_path):
    async def go():
        r = Rig(tmp_path)
        await r.call.start()
        r.disp.down = {"/calls/event"}
        await r.advance(30)
        r.call.on_rep(rep_ev(), t=T0 + 30)
        await r.advance(196)
        res = await r.call.end("complete")
        again = await r.call.end("again")
        return r, res, again
    r, res, again = run(go())
    ck = r.ckpt()
    assert res["committed"] is False and again == res
    assert ck["committed"] is False and ck["sent"] == {"reps_committed": False, "call_ended": False}
    assert [k for k, _ in r.disp.events()].count("call_ended") == 0          # never before reps_committed is acked
    assert ck["final"] is True and len(ck["reps"]) == 1 and ck["ended_at"] is not None
    assert ck["idem_keys"] == {"reps_committed": "call-1:reps_committed", "call_ended": "call-1:call_ended"}
    assert "commit_pending" in r.alerts
    sent = [b["idem_key"] for p, b, _ in r.disp.requests if p == "/calls/event" and b["kind"] == "reps_committed"]
    assert len(sent) == 4 and set(sent) == {"call-1:reps_committed"}            # 1 + 3 retries, one idem key


def test_partial_commit_records_what_was_sent(tmp_path):
    async def go():
        r = Rig(tmp_path, disp=Dispatcher(fail_status={"/calls/event": [503]}, refuse={"call_ended"}))
        await r.call.start()
        await r.advance(196)
        return r, await r.call.end("complete")
    r, res = run(go())
    ck = r.ckpt()
    assert res["committed"] is False and ck["sent"] == {"reps_committed": True, "call_ended": False}
    assert "refused" in ck["last_error"]


def test_concurrent_end_runs_once(tmp_path):
    async def go():
        r = Rig(tmp_path)
        await r.call.start()
        a, b = await asyncio.gather(r.call.end("x"), r.call.end("y"))
        return r, a, b
    r, a, b = run(go())
    assert a == b and [k for k, _ in r.disp.events()].count("reps_committed") == 1 and r.call.end_reason == "x"


def test_checkpoint_path_is_safe(tmp_path):
    p = ctl.checkpoint_path("../../etc/passwd", str(tmp_path))
    assert os.path.dirname(p) == str(tmp_path) and os.path.basename(p) == "_.._etc_passwd.challenge.json"


# ------------------------------------------------------------------ worker routing
def test_worker_competition_mode_routing(monkeypatch):
    from facetime import worker
    monkeypatch.setenv("CHALLENGE_MODE", "competition")
    monkeypatch.setenv("DEMO_CLIENT_ID", "c1")
    monkeypatch.delenv("PLAN", raising=False)
    import facetime.plan_loader as pl
    monkeypatch.setattr(pl, "load_assignment", lambda *_: pytest.fail("competition must not load a client assignment"))
    a = worker.load_args()
    assert a.exercise == "pushups" and a.plan is None
    monkeypatch.setenv("DISPATCHER_URL", "http://d")
    monkeypatch.setenv("DISPATCHER_TOKEN", "t")
    monkeypatch.setenv("HANGUP_MODE", "chert_api")
    monkeypatch.delenv("CHERT_FACETIME_TOKEN", raising=False)
    monkeypatch.delenv("CHERT_PROJECT_ID", raising=False)
    assert "chert_api" in worker.check_competition(a)
    monkeypatch.setenv("HANGUP_MODE", "leave_room")
    monkeypatch.delenv("DISPATCHER_TOKEN")
    assert "DISPATCHER_TOKEN" in worker.check_competition(a)
    monkeypatch.setenv("CHALLENGE_MODE", "demo")
    assert worker.check_competition(a) is None
    monkeypatch.setenv("CHALLENGE_MODE", "bogus")
    assert "unknown" in worker.check_competition(a)


def test_caller_handle_keys():
    from facetime.worker import caller_handle
    assert caller_handle({"from": " +1555 ", "email": "x@y"}) == "+1555"
    assert caller_handle({"caller": {"phone": "+1666"}}) == "+1666"
    assert caller_handle({"id": "c1"}) is None and caller_handle(None) is None


def test_dispatcher_client_rejects_non_retryable(tmp_path):
    async def go():
        clock = Clock()
        calls = []

        def h(req):
            calls.append(req)
            return httpx.Response(401)
        c = DispatcherClient("http://d", "t", transport=httpx.MockTransport(h), sleep=clock.sleep, monotonic=clock)
        with pytest.raises(DispatcherError) as e:
            await c.event("call_ended", "c1", {})
        return calls, e.value
    calls, err = run(go())
    assert len(calls) == 1 and err.status == 401 and err.retryable is False


# ------------------------------------------------------------------ privacy: a full simulated call through the worker path
MEDIA_EXT = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".mp4", ".mov", ".avi", ".mkv",
             ".webm", ".h264", ".yuv", ".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".pcm", ".raw", ".npy", ".npz")


def _files(root, recursive=True):
    out = set()
    if not os.path.isdir(root):
        return out
    if not recursive:
        return {os.path.join(root, f) for f in os.listdir(root)}
    for d, _, fs in os.walk(root):
        out |= {os.path.join(d, f) for f in fs}
    return out


def test_privacy_full_call_writes_no_media(tmp_path, monkeypatch):
    from facetime import worker
    from facetime.perception import Config, Perception
    from facetime.pipeline import FramePipeline
    from challenge.judge.synth import synth_pushups

    sess = tmp_path / "sessions"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHALLENGE_MODE", "competition")
    monkeypatch.setenv("CHALLENGE_SESSIONS_DIR", str(sess))
    monkeypatch.setenv("WORKER_HEALTH_DIR", str(tmp_path / "health"))
    monkeypatch.setenv("CALLER_ID_SOURCE", "chert_meta")
    monkeypatch.setenv("HANGUP_MODE", "leave_room")
    monkeypatch.setenv("DISPATCHER_URL", "http://dispatcher")
    monkeypatch.setenv("DISPATCHER_TOKEN", "tok")
    disp = Dispatcher(start={"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None, "power_hour_active": False,
                             "config": {"judge_thresholds": {"cue_min_gap_s": 6, "liveness_enabled": True}}})
    clock = Clock()

    async def yield_sleep(dt):
        await asyncio.sleep(0)
    monkeypatch.setattr(DispatcherClient, "from_env", classmethod(
        lambda cls, env=None, **kw: cls("http://dispatcher", "tok", transport=httpx.MockTransport(disp), sleep=yield_sleep, monotonic=clock)))
    monkeypatch.setattr(ctl, "default_liveness_factory", factory("pass", fire=60.0))

    # media guards: any image/video/audio write fails the test
    real_open = builtins.open
    violations = []

    def guarded_open(file, mode="r", *a, **kw):
        if any(m in mode for m in "wax+") and str(file).lower().endswith(MEDIA_EXT):
            violations.append(str(file))
            raise AssertionError(f"media written to disk: {file}")
        return real_open(file, mode, *a, **kw)
    monkeypatch.setattr(builtins, "open", guarded_open)
    try:
        import cv2
        monkeypatch.setattr(cv2, "imwrite", lambda *a, **k: pytest.fail("cv2.imwrite called"))
        monkeypatch.setattr(cv2, "VideoWriter", lambda *a, **k: pytest.fail("cv2.VideoWriter created"))
    except ImportError:
        pass
    data_tmp = os.path.join(os.environ.get("RTCOACH_DATA", os.path.join(ctl.ROOT, "data")), "tmp")
    roots = [(str(tmp_path), True), (tempfile.gettempdir(), False), (data_tmp, True)]
    before = {r: _files(r, rec) for r, rec in roots}

    clip = synth_pushups(n_reps=97, rep_s=2.0, lead_in_s=3.0, tail_s=0.5)
    left = []

    async def go():
        room = SimpleNamespace(name="room-1", connection_state=None, local_participant=SimpleNamespace(identity="agent"))
        ctx = SimpleNamespace(room=room, job=SimpleNamespace(id="j1"), shutdown=lambda reason=None: left.append(reason))
        a = worker.load_args()
        a.publish_data = False
        job = worker.CoachJob(ctx, a, None, None, None, {"chert_call": {"from": "+15550001", "id": "x"}})
        job.loop = asyncio.get_running_loop()
        job.clock, job.sleep = clock, yield_sleep
        job.per = Perception(Config(exercise="pushups", announce=False, judge=True),
                             pipe=FramePipeline(None, exercise="pushups", pose_variant=None, trigger="none", judge=True),
                             clip_s=lambda _t: None, t0=0)
        job.per.on_event(job.on_event)
        job.per_wall0 = T0
        job.bind(SimpleNamespace(identity="chert-bridge-call-77"), "test")
        assert job.competition and job.comp is not None and job.comp.handle == "+15550001"
        for _ in range(5):
            await asyncio.sleep(0)
        assert job.comp.decision == "accept" and job.comp.judge_ready is False   # waits for the pipeline judge
        for f in clip.frames:
            clock.t = T0 + f.t
            if job.pending_windows:
                job.before_frame()
            job.per.process_landmarks(f.img, f.world, f.persons, t_recv=f.t, t_ms=round(f.t * 1000), aspect=f.aspect)
            job.after_frame(T0 + f.t, (1920, 1080))
            for _ in range(3):
                await asyncio.sleep(0)
        while not job.done.is_set() and clock.t < T0 + 200:
            clock.t += 0.25
            for _ in range(3):
                await asyncio.sleep(0)
        assert job.done.is_set() and job.end_reason == "call complete"
        assert job.comp.judge_ready and job.per.pipe.judge.thr["cue_min_gap_s"] == 6 and job.per.pipe.judge_thr["cue_min_gap_s"] == 6
        await job.aclose()
        return job
    job = run(go())

    assert not violations
    after = {r: _files(r, rec) for r, rec in roots}
    new = set().union(*(after[r] - before[r] for r, _ in roots))
    assert not [p for p in new if p.lower().endswith(MEDIA_EXT)]
    assert {p for p in new if p.startswith(str(tmp_path))} == {str(sess / "call-77.challenge.json"),
                                                               str(sess / "call-77.challenge.json.lock"),   # ownership flock (empty)
                                                               str(sess / "call-77.challenge.json.sent.json"),  # acked digest
                                                               str(tmp_path / "health" / "line-1.json")}
    assert os.path.getsize(sess / "call-77.challenge.json.lock") == 0
    sent = json.loads((sess / "call-77.challenge.json.sent.json").read_text())
    assert set(sent) == {"call_id", "entries"} and [set(e) for e in sent["entries"]] == [{"digest", "acked", "rep_count", "at_t"}]
    assert "+15550001" not in json.dumps(sent)
    assert json.loads((tmp_path / "health" / "line-1.json").read_text())["active"] is False
    ck = json.loads((sess / "call-77.challenge.json").read_text())
    assert ck["committed"] is True and ck["call_id"] == "call-77" and ck["liveness_result"] == "pass"
    assert "handle" not in json.dumps(ck) and "+15550001" not in json.dumps(ck)
    reps = ck["reps"]
    assert len(reps) >= 80 and all(r["t"] < 180 for r in reps) and job.comp.ignored_reps >= 5
    assert sum(r["valid"] for r in reps) >= 0.9 * len(reps) - 2                # clean synthetic push-ups are counted
    assert any(r["in_challenge"] for r in reps)                                # the challenge window reached the judge path
    start = [b for p, b, _ in disp.requests if p == "/calls/start"][0]
    assert start == {"call_id": "call-77", "line_id": "line-1", "handle": "+15550001"}
    assert [k for k, _ in disp.events()] == ["call_started", "reps_committed", "call_ended"]


# ------------------------------------------------------------------ dispatcher additions (/calls/start extras, /calls/heartbeat)
def test_dispatcher_start_extras_and_heartbeat(db, conn):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    from fastapi.testclient import TestClient

    from challenge.dispatcher.app import create_app
    from challenge.dispatcher.flags import Flags
    from challenge.store import PgStore

    t0 = datetime(2026, 10, 13, 15, 10, tzinfo=ZoneInfo("America/New_York"))
    conn.execute("truncate clients, calls, power_hours, heartbeats restart identity cascade")
    conn.execute("update line_state set state='idle', user_id=null, call_id=null, claimed_until=null,"
                 " offline_until=null, in_call_since=null")
    conn.execute("insert into power_hours (date_et, starts_at, ends_at) values (%s, %s, %s)",
                 (t0.date(), t0 - timedelta(minutes=10), t0 + timedelta(minutes=50)))
    outbox = SimpleNamespace(enqueue=lambda **kw: {"duplicate": False})
    c = TestClient(create_app(PgStore(db), outbox, clock=lambda: t0, flags=Flags(CALLER_ID_SOURCE="chert_meta"), token="tok"))
    h = {"X-Brodie-Token": "tok"}
    coach = conn.execute("select (value #>> '{}')::uuid from competition_config where key='challenge_coach_id'").fetchone()[0]
    uid = conn.execute("insert into clients (coach_id, name, display_name, joined_at) values (%s,'worker_tester','worker_tester',%s) returning id",
                       (coach, t0 - timedelta(days=1))).fetchone()[0]
    handle = "+16660009999"
    conn.execute("insert into client_handles (handle, client_id, kind, linked_via) values (%s,%s,'phone','join')", (handle, uid))
    j = c.post("/calls/start", headers=h, json={"call_id": "w-1", "line_id": "line-1", "handle": handle}).json()
    assert j["decision"] == "accept" and j["power_hour_active"] is True
    assert j["config"]["call_count_s"] == 180 and j["config"]["call_reveal_s"] == 15
    assert j["config"]["judge_thresholds"]["liveness_timeout_s"] == 4
    rej = c.post("/calls/start", headers=h, json={"call_id": "w-2", "line_id": "line-1", "handle": "+19990000001"}).json()
    assert rej["decision"] == "reject" and "config" not in rej and "power_hour_active" not in rej
    hb = lambda body: c.post("/calls/heartbeat", headers=h, json=body)
    assert c.post("/calls/heartbeat", json={"line_id": "line-1"}).status_code == 401
    assert hb({"line_id": "line-1", "detail": {"pid": 1}}).json() == {"ok": True, "healthy": True}
    rows = dict(conn.execute("select component, detail from heartbeats").fetchall())
    assert set(rows) == {"worker", "worker:line-1"}
    assert rows["worker:line-1"] == {"pid": 1, "line_id": "line-1", "scope": "supervisor", "healthy": True}
    assert hb({"line_id": "line-1", "detail": {"x": "y" * 3000}}).status_code == 413
    assert hb({"line_id": "line-9"}).status_code == 404
    assert hb({"line_id": "../x"}).status_code == 422
    conn.execute("update heartbeats set at = at - interval '1 hour' where component = 'worker'")
    old = conn.execute("select at from heartbeats where component='worker'").fetchone()[0]
    assert hb({"line_id": "line-1", "scope": "job", "healthy": False, "detail": {"counting": True}}).json()["healthy"] is False
    rows = {k: (a, d) for k, a, d in conn.execute("select component, at, detail from heartbeats").fetchall()}
    assert rows["worker"][0] == old                           # a wedged job does not refresh the aggregate the alerts read
    assert rows["worker:line-1:job"][1]["healthy"] is False


# ------------------------------------------------------------------ fix round: restart, fail-closed, races, worker plumbing
def _payload(disp, kind="reps_committed"):
    return [b for p, b, _ in disp.requests if p == "/calls/event" and b["kind"] == kind][-1]["payload"]


def test_restart_adopts_checkpoint_and_never_clobbers_reps(tmp_path):
    async def go():
        r1 = Rig(tmp_path)
        await r1.call.start()
        for rel in (10.0, 20.0):
            await r1.advance(rel)
            r1.call.on_rep(rep_ev(), t=T0 + rel)
        await r1.advance(61)                                   # the challenge started at 60
        ck1 = r1.ckpt()
        # while the first worker lives it owns the call (per-call lock): a second controller may not adopt it
        probe = Rig(tmp_path)
        probe.clock.t = T0 + 65
        assert await probe.call.start() is False and probe.call.decision == "error"
        assert r1.ckpt() == ck1                                # untouched by the refused controller
        r1.call.lock.release()                                 # the first worker dies: the kernel drops its lock
        # the worker restarts (redispatch) 9 s later: a new controller for the same call id
        r2 = Rig(tmp_path, liveness=factory("pass"))
        r2.clock.t = T0 + 70
        assert await r2.call.start() is True
        ck2 = r2.ckpt()
        await r2.advance(100)
        r2.call.on_rep(rep_ev(), t=T0 + 100)
        await r2.advance(196)
        await r2.call.end("complete")
        return r1, r2, ck1, ck2
    r1, r2, ck1, ck2 = run(go())
    assert ck1["liveness"]["windows_s"] == [[60.0, 64.0]] and ck1["liveness"]["fires_s"] == [60.0]
    assert ck2["t0"] == T0 and len(ck2["reps"]) == 2 and ck2["reps"] == ck1["reps"]
    assert [60.0, 64.0] in ck2["liveness"]["windows_s"] and ck2["liveness"]["rescheduled"] is True
    assert "welcome" not in r2.keys() and r2.disp.events()[0][0] == "reps_committed"     # call_started is not resent
    sent = _payload(r2.disp)
    assert [x["t"] for x in sent["reps"]] == [10.0, 20.0, 100.0] and sent["started_at"] == utc(T0)


def utc(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def test_restart_of_a_final_uncommitted_call_resends_and_leaves(tmp_path):
    async def go():
        r1 = Rig(tmp_path)
        await r1.call.start()
        r1.disp.down = {"/calls/event"}
        await r1.advance(30)
        r1.call.on_rep(rep_ev(), t=T0 + 30)
        await r1.advance(196)
        assert (await r1.call.end("complete"))["committed"] is False
        r2 = Rig(tmp_path)
        r2.clock.t = T0 + 300
        ok = await r2.call.start()
        res = await r2.call.end("ignored")
        return r2, ok, res
    r2, ok, res = run(go())
    assert ok is False and r2.left == [(300.0, "call already ended")] and r2.keys() == []
    assert res["committed"] is True and r2.ckpt()["committed"] is True and r2.call.end_reason == "complete"
    assert [k for k, _ in r2.disp.events()] == ["reps_committed", "call_ended"] and len(_payload(r2.disp)["reps"]) == 1


def test_unreadable_or_foreign_checkpoint_is_moved_aside(tmp_path):
    async def go():
        out = []
        for content in ("{not json", json.dumps({"call_id": "call-1/other", "t0": 1.0, "reps": [{"n": 1}]})):
            os.makedirs(tmp_path / "sessions", exist_ok=True)
            r = Rig(tmp_path)
            with open(r.call.path, "w") as f:
                f.write(content)
            assert await r.call.start() is True
            assert r.call.lock is not None and r.call.lock.held               # it owns the call while it runs
            r.call.lock.release()                                              # (this worker is gone before the next)
            out.append((r, content))
            for p in os.listdir(r.dir):
                if ".aside-" in p:
                    os.replace(os.path.join(r.dir, p), str(tmp_path / f"kept-{len(out)}"))
            os.remove(r.call.path)
        return out
    for i, (r, content) in enumerate(run(go()), 1):
        assert "checkpoint_conflict" in r.alerts and r.call.adopted is False and r.call.t0 == T0
        assert (tmp_path / f"kept-{i}").read_text() == content            # moved aside, never overwritten


def test_liveness_transitions_checkpointed_immediately(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("pass", fire=60.0))
        await r.call.start()
        snaps = [r.ckpt()["liveness"]]
        await r.advance(60)
        snaps.append(r.ckpt()["liveness"])
        await r.advance(62.25)
        snaps.append(r.ckpt()["liveness"])
        return snaps
    s0, s_start, s_pass = run(go())
    assert s0["fires_s"] == [60.0] and s0["windows_s"] == [] and s0["result"] is None
    assert s_start["windows_s"] == [[60.0, 64.0]] and s_start["result"] is None
    assert s_pass["result"] == "pass"


def test_live_thresholds_wait_for_the_pipeline_judge(tmp_path):
    async def go():
        cfgs = []
        r = Rig(tmp_path, on_config=cfgs.append, judge_cfg={},
                start={"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None,
                       "config": {"judge_thresholds": {"cue_min_gap_s": 9}}})
        await r.call.start()
        await r.advance(5)
        before = r.call.on_rep(rep_ev(), t=T0 + 5)
        r.call.judge_applied()
        after = r.call.on_rep(rep_ev(), t=T0 + 5.5)
        return r, cfgs, before, after
    r, cfgs, before, after = run(go())
    assert cfgs == [{"cue_min_gap_s": 9}] and r.call.thr["cue_min_gap_s"] == 9
    assert before is None and after is not None and r.call.ignored_reps == 1 and len(r.ckpt()["reps"]) == 1


def test_liveness_schedule_or_poll_error_fails_closed(tmp_path):
    def broken(rng, thr):
        raise RuntimeError("no liveness")

    class PollBoom(FakeLiveness):
        def poll(self, t):
            raise RuntimeError("poll boom")

    async def go():
        a = Rig(tmp_path / "a", liveness=broken)
        await a.call.start()
        ck_a = a.ckpt()
        a.call.on_rep(rep_ev(), t=T0 + 1)
        await a.advance(196)
        await a.call.end("complete")
        b = Rig(tmp_path / "b", liveness=lambda rng, thr: PollBoom(rng, thr, "pass", fire=60.0))
        await b.call.start()
        await b.advance(61)
        ck_b = b.ckpt()
        return a, ck_a, b, ck_b
    a, ck_a, b, ck_b = run(go())
    assert ck_a["liveness_result"] == "fail" and "liveness_error" in a.alerts       # persisted before any rep
    assert _payload(a.disp)["liveness_result"] == "fail"                           # the DB voids the call
    assert ck_b["liveness_result"] == "fail" and "liveness_error" in b.alerts


def test_rep_fired_before_count_end_counts_when_delivered_late(tmp_path):
    async def go():
        r = Rig(tmp_path)
        await r.call.start()
        await r.advance(181)                                    # tick(count_s) already ran
        late = r.call.on_rep(rep_ev(), t=T0 + 179.9)
        after = r.call.on_rep(rep_ev(), t=T0 + 180.1)
        await r.advance(196)
        await r.call.end("complete")
        return r, late, after
    r, late, after = run(go())
    assert late is not None and after is None and [x["t"] for x in _payload(r.disp)["reps"]] == [179.9]


def test_rep_racing_end_is_committed_or_leaves_committed_false(tmp_path):
    async def go():
        # (a) delivered while end() drains the pipeline: in the committed payload
        holder = {}

        async def drain():
            holder["r"].call.on_rep(rep_ev(), t=T0 + 150)
            await asyncio.sleep(0)
            return True
        a = Rig(tmp_path / "a", drain=drain)
        holder["r"] = a
        await a.call.start()
        await a.advance(160)
        res_a = await a.call.end("caller left")
        # (b) delivered after the payload was built (while reps_committed is in flight): late_reps, committed false
        disp = Dispatcher()
        b = Rig(tmp_path / "b", disp=disp)
        orig = disp.__call__

        def racing(req):
            if req.url.path == "/calls/event" and json.loads(req.content)["kind"] == "reps_committed":
                b.call.on_rep(rep_ev(), t=T0 + 155)
            return orig(req)
        b.client._client._transport = httpx.MockTransport(racing)
        await b.call.start()
        await b.advance(160)
        res_b = await b.call.end("caller left")
        return a, res_a, b, res_b
    a, res_a, b, res_b = run(go())
    assert res_a["committed"] is True and [x["t"] for x in _payload(a.disp)["reps"]] == [150.0]
    ck = b.ckpt()
    assert res_b["committed"] is False and ck["committed"] is False and _payload(b.disp)["reps"] == []
    assert [x["t"] for x in ck["late_reps"]] == [155.0] and "late_rep" in b.alerts and "commit_pending" in b.alerts


class HangingEvents:
    """The dispatcher accepts /calls/start, then never answers an event."""

    def __init__(self, inner, exc=None):
        self.inner, self.exc, self.kinds = inner, exc, []

    async def start_call(self, *a, **kw):
        return await self.inner.start_call(*a, **kw)

    async def event(self, kind, *a, **kw):
        self.kinds.append(kind)
        if self.exc is not None:
            raise self.exc
        await asyncio.Event().wait()


def test_leaves_on_time_when_the_dispatcher_hangs_at_commit(tmp_path):
    async def go():
        r = Rig(tmp_path, hangup="leave_room", commit_deadline_s=0.2)
        r.call.dispatcher = HangingEvents(r.client)
        await r.call.start()
        await r.call.run(interval=0.5)
        left = list(r.left)
        res = await r.call.end("x")
        return r, left, res
    r, left, res = run(go())
    assert left == [(195.0, "call complete")]
    assert res["committed"] is False and r.call.dispatcher.kinds == ["call_started", "reps_committed"]   # no call_ended
    ck = r.ckpt()
    assert ck["committed"] is False and ck["sent"] == {"reps_committed": False, "call_ended": False}
    assert "deadline" in ck["last_error"] and "commit_pending" in r.alerts


def test_unexpected_send_error_keeps_checkpoint_and_alerts(tmp_path):
    async def go():
        r = Rig(tmp_path)
        r.call.dispatcher = HangingEvents(r.client, exc=RuntimeError("boom"))
        await r.call.start()
        await r.advance(196)
        return r, await r.call.end("complete")
    r, res = run(go())
    assert res["committed"] is False and "commit_pending" in r.alerts and "boom" in r.ckpt()["last_error"]


def test_accept_without_user_or_setup_error_fails_closed(tmp_path):
    async def go():
        a = Rig(tmp_path / "a", start={"decision": "accept", "user_id": "", "reason": "ok", "cue": None})
        ok_a = await a.call.start()
        b = Rig(tmp_path / "b")

        def boom(rel=0.0):
            raise RuntimeError("timeline")
        b.call._schedule_timeline = boom
        ok_b = await b.call.start()
        res_b = await b.call.end("x")
        return a, ok_a, b, ok_b, res_b
    a, ok_a, b, ok_b, res_b = run(go())
    # P1-2: the fail cue plays, then the leave (FAIL_CUE_S later); a best-effort call_ended (0 reps) frees the line
    assert ok_a is False and a.call.decision == "error" and a.left == [(ctl.FAIL_CUE_S, "accept_without_user")]
    assert ok_b is False and b.call.decision == "error" and b.left == [(ctl.FAIL_CUE_S, "call_setup_failed")]
    assert a.keys() == ["try_again"] and b.keys() == ["try_again"]
    assert res_b == {"recorded": False, "committed": False, "decision": "error"}
    assert a.call.on_rep(rep_ev(), t=T0 + 1) is None
    for r in (a, b):
        assert r.disp.events() == [("call_ended", "call-1:call_ended")]
        assert [b_["payload"]["rep_count"] for p, b_, _ in r.disp.requests if p == "/calls/event"] == [0]


# ------------------------------------------------------------------ worker plumbing
def _job(monkeypatch, tmp_path, md=None):
    from facetime import worker
    monkeypatch.setenv("CHALLENGE_MODE", "competition")
    monkeypatch.setenv("WORKER_HEALTH_DIR", str(tmp_path / "health"))
    room = SimpleNamespace(name="room-1", connection_state=None, local_participant=SimpleNamespace(identity="agent"),
                           remote_participants={})
    ctx = SimpleNamespace(room=room, job=SimpleNamespace(id="j1"), shutdown=lambda reason=None: None)
    a = worker.load_args()
    a.publish_data = False
    return worker, worker.CoachJob(ctx, a, None, None, None, md or {})


def test_worker_rep_events_reach_the_controller_on_the_loop_thread(tmp_path, monkeypatch):
    import threading
    worker, job = _job(monkeypatch, tmp_path)
    seen = []
    job.comp = SimpleNamespace(on_rep=lambda ev, t: seen.append((threading.get_ident(), ev["n"], t)))

    async def go():
        job.loop = asyncio.get_running_loop()
        job.per_wall0 = T0
        ev = {"type": "rep", "exercise": "pushups", "n": 1, "t": 12.5, "confidence": {}}
        th = threading.Thread(target=job.on_event, args=(ev,))
        th.start()
        th.join()
        for _ in range(3):
            await asyncio.sleep(0)
        return threading.get_ident()
    loop_thread = run(go())
    assert seen == [(loop_thread, 1, T0 + 12.5)]


def test_close_competition_keeps_client_open_while_commit_runs(tmp_path, monkeypatch):
    worker, job = _job(monkeypatch, tmp_path)
    monkeypatch.setattr(worker, "COMMIT_WAIT_S", 0.05)
    closed = []

    async def go():
        job.loop = asyncio.get_running_loop()
        gate = asyncio.Event()
        comp = SimpleNamespace(path="p", decision="accept", ended_at=None, reps=[], last_tick_wall=None, _end_task=None,
                               commit_deferred=False)

        async def _end():
            await gate.wait()
            return {"committed": True}

        async def end(reason):
            if comp._end_task is None:
                comp._end_task = asyncio.ensure_future(_end())
            return await asyncio.shield(comp._end_task)
        comp.end = end
        job.comp = comp
        job.comp_client = SimpleNamespace(aclose=lambda: _rec(closed))
        comp.ending = True
        await job.close_competition()
        during = list(closed)
        comp.ending = False
        gate.set()
        for _ in range(5):
            await asyncio.sleep(0)
        return during
    during = run(go())
    assert during == [] and closed == ["closed"]
    assert json.loads((tmp_path / "health" / "line-1.json").read_text())["active"] is False


async def _rec(out):
    out.append("closed")


def test_supervisor_health_reflects_the_job(tmp_path, monkeypatch):
    from facetime import worker
    from challenge.worker.controller import write_json_atomic
    monkeypatch.setenv("WORKER_HEALTH_DIR", str(tmp_path))
    p = worker.health_path()
    assert worker.supervisor_health(1000.0) == (True, {"job": None})
    write_json_atomic(p, {"t": 1000.0, "active": True, "healthy": True, "pid": os.getpid(), "call_id": "c"})
    assert worker.supervisor_health(1010.0)[0] is True
    assert worker.supervisor_health(1000.0 + worker.JOB_STALE_S + 1)[0] is False        # wedged job: stale file
    write_json_atomic(p, {"t": 1000.0, "active": True, "healthy": False, "pid": os.getpid()})
    assert worker.supervisor_health(1001.0)[0] is False
    write_json_atomic(p, {"t": 1000.0, "active": False, "healthy": False})
    assert worker.supervisor_health(5000.0) == (True, {"job": "idle"})
    with open(p, "w") as f:
        f.write("{")
    assert worker.supervisor_health(1000.0)[0] is False


def test_job_health_flags_a_stalled_controller(tmp_path, monkeypatch):
    import time as _time
    worker, job = _job(monkeypatch, tmp_path)
    job.comp = SimpleNamespace(decision="accept", ended_at=None, reps=[1, 2], last_tick_wall=_time.time())
    ok, detail = job.job_health()
    assert ok and detail["counting"] and detail["reps"] == 2
    job.comp.last_tick_wall = _time.time() - worker.JOB_STALL_S - 5
    assert job.job_health()[0] is False


def test_competition_startup_log_redacts_the_caller(tmp_path, monkeypatch, capsys):
    from facetime.perception import Config
    from facetime.pipeline import FramePipeline
    md = {"chert_call": {"from": "+15550001", "email": "a@b.example", "id": "x"}}
    worker, job = _job(monkeypatch, tmp_path, md)
    monkeypatch.setenv("DISPATCHER_URL", "http://dispatcher")
    monkeypatch.setenv("DISPATCHER_TOKEN", "tok")
    job.a.events_only = True
    job.a.event_log = str(tmp_path / "events.jsonl")
    job.cfg = Config(exercise="pushups", announce=False, judge=True)
    job.pipe = FramePipeline(None, exercise="pushups", pose_variant=None, trigger="none", judge=True)
    job.room.on = lambda *a, **k: None

    async def connect(**kw):
        return None
    job.ctx.connect = connect
    job.ctx.add_shutdown_callback = lambda cb: None

    async def go():
        t = asyncio.ensure_future(job.run())
        for _ in range(20):
            await asyncio.sleep(0)
        job.end("test over")
        await asyncio.wait_for(t, 10)
    run(go())
    out = capsys.readouterr().out
    assert "joined room" in out and "chert_call=<keys ['email', 'from', 'id']>" in out
    assert "+15550001" not in out and "a@b.example" not in out


def test_queued_reject_plays_cue_and_leaves_within_5s(tmp_path):
    async def go():
        r = Rig(tmp_path, start={"decision": "reject", "user_id": "u9", "reason": "queued", "cue": "queued", "position": 3})
        ok = await r.call.start()
        r.call.on_rep(rep_ev(), t=T0 + 1)
        res = await r.call.end("x")
        return r, ok, res
    r, ok, res = run(go())
    assert ok is False and r.call.decision == "reject" and r.call.reason == "queued"
    assert r.said == [(0.0, "queued", True)]
    assert len(r.left) == 1 and r.left[0][0] <= 5.0 and r.left[0][1] == "rejected: queued"
    assert res == {"recorded": False, "committed": False, "decision": "reject"}
    assert r.disp.paths() == ["/calls/start"] and not os.path.exists(r.call.path)


def test_perception_update_challenge_window_replaces_on_the_judge_clock():
    from facetime.perception import Perception

    class Judge:
        def __init__(self):
            self.windows = []

        def set_challenge_window(self, a, b):
            self.windows.append((a, b))

        def update_challenge_window(self, a, b):
            for i, (x, _) in enumerate(self.windows):
                if x == a:
                    self.windows[i] = (a, b)
                    return
            self.windows.append((a, b))
    per = Perception.__new__(Perception)
    per.pipe = SimpleNamespace(judge=None)
    per._windows, per._win_judge, per._win_done, per._win_at, per._judge_off = [], None, 0, [], None
    assert per.update_challenge_window(60.0, 70.0) is False                       # queued: no judged frame yet
    assert per.update_challenge_window(60.0, 66.0) is False and per._windows == [(60.0, 66.0)]
    j = Judge()
    per.pipe.judge, per._judge_off = j, 100.0
    per._apply_windows()
    assert j.windows == [(160.0, 166.0)]
    per._judge_off = 100.25                                                       # the offset drifts frame to frame
    assert per.update_challenge_window(60.0, 63.0) is True
    assert j.windows == [(160.0, 163.0)]                                          # replaced at its registered start
    per.update_challenge_window(80.0, 84.0)
    assert j.windows == [(160.0, 163.0), (180.25, 184.25)]
    j2 = Judge()                                                                  # a new judge gets every window
    per.pipe.judge = j2
    per.update_challenge_window(80.0, 82.0)
    assert j2.windows == [(160.25, 163.25), (180.25, 182.25)]


def test_real_liveness_unanswered_challenge_fails_and_marks_reps(tmp_path):
    """The real LivenessChallenge through the controller: reps earned, nobody answers (no frames) -> two attempts,
    then fail; every valid rep is liveness_fail and each window reached update_challenge_window."""
    async def go():
        r = Rig(tmp_path, liveness=ctl.default_liveness_factory)
        await r.call.start()
        for rel in range(10, 178, 3):
            await r.advance(rel)
            r.call.on_rep(rep_ev(), t=T0 + rel)
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    cues = [k for k in r.keys() if k.startswith("challenge_")]
    assert cues[-1] == "challenge_failed" and len(cues) >= 3 and all(k in CUES for k in cues)
    ck = r.ckpt()
    assert ck["liveness_result"] == "fail" and len(ck["liveness"]["windows_s"]) == 2
    assert {a for a, _ in r.windows} == {a for a, _ in ck["liveness"]["windows_s"]}
    assert ck["reps"] and all(x["valid"] is False and "liveness_fail" in x["reject_reasons"] for x in ck["reps"])
    assert _payload(r.disp)["liveness_result"] == "fail"



# ------------------------------------------------------------------ final fix round
def test_rep_delivered_after_aclose_started_still_reaches_the_controller(tmp_path, monkeypatch):
    worker, job = _job(monkeypatch, tmp_path)
    seen = []
    job.comp = SimpleNamespace(on_rep=lambda ev, t: seen.append((ev["n"], t)))
    job.per_wall0 = T0
    job.closed = True                                     # hang-up: aclose() already running
    job._deliver({"type": "rep", "exercise": "pushups", "n": 4, "t": 30.0, "confidence": {}})
    assert seen == [(4, T0 + 30.0)]                       # the controller decides by timestamp, not the worker


def test_drain_feed_seals_intake_after_the_frame_in_flight(tmp_path, monkeypatch):
    import threading
    import time as _time
    worker, job = _job(monkeypatch, tmp_path)
    seen = []
    job.comp = SimpleNamespace(on_rep=lambda ev, t: seen.append(ev["n"]))
    job.per_wall0 = T0
    started = threading.Event()

    async def go():
        job.loop = asyncio.get_running_loop()

        def frame_in_flight():                            # the feed thread mid-frame: its rep event is posted at the end
            with job.feed_lock:
                started.set()
                _time.sleep(0.1)
                job.loop.call_soon_threadsafe(job._deliver, {"type": "rep", "exercise": "pushups", "n": 7, "t": 1.0, "confidence": {}})
        th = threading.Thread(target=frame_in_flight)
        th.start()
        for _ in range(400):
            if started.is_set():
                break
            await asyncio.sleep(0.005)
        assert started.is_set()
        sealed = await asyncio.wait_for(job.drain_feed(), 2)
        th.join()
        return sealed
    assert run(go()) is True and seen == [7] and job.feed_sealed is True


def test_commit_waits_for_a_sealed_intake_and_never_loses_a_rep(tmp_path):
    async def go():
        async def stuck():                                # the feed thread is wedged: intake cannot be sealed
            await asyncio.Event().wait()
        r = Rig(tmp_path, drain=stuck, drain_max_s=0.05)
        await r.call.start()
        await r.advance(30)
        r.call.on_rep(rep_ev(), t=T0 + 30)
        await r.advance(196)
        res1 = await r.call.end("complete")
        ck1 = r.ckpt()
        r.call.on_rep(rep_ev(), t=T0 + 100)               # the wedged frame finally fires its rep (before the end)
        r.call.seal()                                     # the worker: the feed thread has exited
        res2 = await r.call.end("again")
        return r, res1, ck1, res2
    r, res1, ck1, res2 = run(go())
    assert res1["committed"] is False and ck1["sealed"] is False and ck1["sent"]["reps_committed"] is False
    assert "commit_pending" in r.alerts and [k for k, _ in r.disp.events()].count("reps_committed") == 1
    assert res2["committed"] is True and [x["t"] for x in _payload(r.disp)["reps"]] == [30.0, 100.0]
    ck = r.ckpt()
    assert ck["sealed"] is True and ck["committed"] is True and ck["late_reps"] == []


def test_liveness_frame_error_fails_closed_at_once(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("pass", fire=60.0, frame_error=RuntimeError("bad frame")))
        await r.call.start()
        img = np.zeros((33, 5), np.float32)
        r.call.on_frame(FrameObs(t=T0 + 1, img=img, world=None, persons=1))
        r.call.on_frame(FrameObs(t=T0 + 2, img=img, world=None, persons=1))
        ck = r.ckpt()
        await r.advance(70)                               # the challenge would have passed at 62
        return r, ck
    r, ck = run(go())
    assert ck["liveness_result"] == "fail" and "liveness_error" in r.alerts
    assert r.call.liveness_result == "fail" and "challenge_lift_hold" not in r.keys()


def test_in_challenge_recomputed_from_final_windows(tmp_path):
    async def go():
        r = Rig(tmp_path, liveness=factory("pass", fire=60.0, cue="challenge_freeze", go=1.0, after=4.0, timeout=10.0))
        await r.call.start()
        await r.advance(60.5)
        r.call.on_rep(rep_ev(), t=T0 + 60.5)                         # inside both the first and the final window
        await r.advance(62)                                          # go at 61: the window shrinks to 60..63
        r.call.on_rep(rep_ev(in_challenge=True), t=T0 + 66)          # the judge still had 60..70 when it fired
        await r.advance(196)
        await r.call.end("complete")
        return r
    r = run(go())
    assert r.call.windows() == [(60.0, 63.0)]
    by_t = {x["t"]: x for x in _payload(r.disp)["reps"]}
    assert by_t[60.5]["in_challenge"] is True and by_t[66.0]["in_challenge"] is False and by_t[66.0]["valid"] is True


def test_second_cue_of_a_go_status_is_played_as_given(tmp_path, monkeypatch):
    monkeypatch.setitem(CUES, "challenge_down", "And down!")

    async def go():
        r = Rig(tmp_path, liveness=factory("pass", fire=60.0, cue="challenge_lift_hold", go=1.5, go_cue="challenge_down",
                                           after=3.0, timeout=6.0))
        await r.call.start()
        await r.advance(64)
        return r
    r = run(go())
    t = {k: s for s, k, _ in r.said}
    assert t["challenge_lift_hold"] == 60 and t["challenge_down"] == 61.5 and "challenge_go" not in t
    assert r.windows[-1] == (60.0, 63.5) and r.call.liveness_result == "pass"


def test_worker_commits_a_deferred_call_once_the_feed_thread_is_gone(tmp_path, monkeypatch):
    worker, job = _job(monkeypatch, tmp_path)

    async def go():
        async def stuck():
            await asyncio.Event().wait()
        r = Rig(tmp_path, drain=stuck, drain_max_s=0.05)
        job.loop = asyncio.get_running_loop()
        job.comp, job.comp_client = r.call, r.client
        await r.call.start()
        await r.advance(20)
        r.call.on_rep(rep_ev(), t=T0 + 20)
        await r.advance(196)
        await job.close_competition()
        deferred = r.call.commit_deferred
        job.thread = None                                  # the feed thread exited (joined in aclose)
        await job.finish_deferred_commit()
        return r, deferred
    r, deferred = run(go())
    assert deferred is True and r.call.committed is True and r.ckpt()["sealed"] is True
    assert [k for k, _ in r.disp.events()] == ["call_started", "reps_committed", "call_ended"]
    assert r.client._client.is_closed


# ------------------------------------------------------------------ HANGUP_MODE=chert_api (task 35, C7.h)
class FakeChertEnd:
    def __init__(self, ok=True, raises=False):
        self.ok, self.raises, self.calls = ok, raises, []

    async def end_call(self, call_id, sleep):
        self.calls.append(call_id)
        if self.raises:
            raise RuntimeError("boom")
        return self.ok


def _chert_run(tmp_path, monkeypatch, fake, call_id="chert-77"):
    monkeypatch.setenv("CHERT_FACETIME_TOKEN", "ftk_x")
    monkeypatch.setenv("CHERT_PROJECT_ID", "p")

    async def go():
        r = Rig(tmp_path, hangup="chert_api", chert_call_id=call_id, chert_end=fake)
        assert await r.call.start()
        await r.call.run(interval=0.5)
        await r.call.end("complete")
        return r
    return run(go())


def test_chert_api_ends_via_api_then_leaves(tmp_path, monkeypatch):
    fake = FakeChertEnd(ok=True)
    r = _chert_run(tmp_path, monkeypatch, fake)
    assert fake.calls == ["chert-77"] and r.call.chert_hangup == "acknowledged"
    assert len(r.left) == 1 and "hang_up" not in r.keys()


@pytest.mark.parametrize("fake,call_id,state", [(FakeChertEnd(ok=False), "c1", "failed"),
                                                 (FakeChertEnd(raises=True), "c1", "failed"),
                                                 (FakeChertEnd(ok=True), None, "no_call_id")])
def test_chert_api_failure_falls_back_to_leaving(tmp_path, monkeypatch, fake, call_id, state):
    r = _chert_run(tmp_path, monkeypatch, fake, call_id)
    assert r.call.chert_hangup == state and len(r.left) == 1
    assert r.disp.events()[-1][0] == "call_ended"


def test_chert_api_refused_without_env(monkeypatch):
    monkeypatch.delenv("CHERT_FACETIME_TOKEN", raising=False)
    monkeypatch.delenv("CHERT_PROJECT_ID", raising=False)
    with pytest.raises(UnsupportedMode, match="CHERT_FACETIME_TOKEN and CHERT_PROJECT_ID"):
        ctl.check_modes("chert_api", "audio_only")
    monkeypatch.setenv("CHERT_FACETIME_TOKEN", "t")
    monkeypatch.setenv("CHERT_PROJECT_ID", "p")
    assert ctl.check_modes("chert_api", "audio_only") == []
