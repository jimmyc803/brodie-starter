"""Task 37: a real Chert call routed into a prewarmed (chert_warm) room, driven through CoachJob end to end: warm start ->
chert-bridge-* participant publishes -> start_competition -> /calls/start -> reps -> commit -> leave. Guards the live bug
fixed in 9da2781 (a bridge caller in a warm job was ignored, so the competition never started). The room, participants and
dispatcher are fakes; CoachJob, CompetitionCall and DispatcherClient are the real ones."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from challenge.judge.gates import JUDGE_VERSION
from challenge.worker.client import DispatcherClient
from tests.challenge.test_worker_controller import T0, Clock, Dispatcher, _job, rep_ev


class Harness:
    def __init__(self, monkeypatch, tmp_path, md):
        monkeypatch.setenv("CHALLENGE_SESSIONS_DIR", str(tmp_path / "sessions"))
        monkeypatch.setenv("LINE_ID", "line-7")
        monkeypatch.setenv("CALLER_ID_SOURCE", "claim_window")
        self.worker, self.job = _job(monkeypatch, tmp_path, md)
        self.clock = Clock()
        self.disp = Dispatcher(start={"decision": "accept", "user_id": "u1", "reason": "ok", "cue": None})
        self.job.clock, self.job.sleep = self.clock, self.clock.sleep
        self.job.per_wall0 = T0
        self.disconnects = []

        async def disconnect():
            self.disconnects.append(self.clock.t - T0)
        self.job.room.disconnect = disconnect
        self.job.room_connected = lambda: True
        clock, disp = self.clock, self.disp
        self.made = []

        def from_env(env=None, **kw):
            c = DispatcherClient("http://dispatcher", "tok", timeout=3, retries=3, backoff_s=0.5,
                                 transport=httpx.MockTransport(disp), sleep=clock.sleep, monotonic=clock)
            self.made.append(c)
            return c
        monkeypatch.setattr(DispatcherClient, "from_env", staticmethod(from_env))

    def calls(self, path):
        return [b for p, b, _ in self.disp.requests if p == path]

    def events(self, kind):
        return [b for b in self.calls("/calls/event") if b["kind"] == kind]

    def bind(self, identity):
        self.job.bind(SimpleNamespace(identity=identity), "video 'cam' 640x480")

    async def settle(self, n=5):
        for _ in range(n):
            await asyncio.sleep(0)


def make(monkeypatch, tmp_path, warm=True):
    return Harness(monkeypatch, tmp_path, {"chert_warm": True} if warm else {})


def test_warm_room_bridge_call_runs_the_full_competition(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)
    job = h.job
    assert job.warm is True and job.competition is True

    async def go():
        job.loop = asyncio.get_running_loop()
        # the warm start: joined, nobody published yet -> nothing asked of the dispatcher
        await h.settle()
        before = list(h.disp.requests)
        h.bind("chert-bridge-call-42")
        await h.settle()
        started = list(h.calls("/calls/start"))
        # a second video track from the same bridge caller must not start a second competition
        h.bind("chert-bridge-call-42")
        await h.settle()
        comp = job.comp
        assert comp.decision == "accept"
        # reps arrive on the perception event clock (seconds since per.t0)
        for i, t in enumerate((20.0, 25.0, 31.0), 1):
            h.clock.t = T0 + t
            job._deliver({**rep_ev(n=i), "exercise": "pushups", "t": t})
        await h.settle()
        # run the controller clock to count_s + reveal_s: the controller leaves through job.end
        for _ in range(2000):
            if job.done.is_set():
                break
            await h.clock.sleep(0.5)
        assert job.done.is_set(), "the worker must end the job at count + reveal"
        left_at = h.clock.t - T0
        await job.close_competition()
        await h.settle()
        return before, started, comp, left_at

    before, started, comp, left_at = asyncio.run(go())
    assert [p for p, _, _ in before if p == "/calls/start"] == []
    assert len(started) == 1 and len(h.made) == 1
    assert started[0]["call_id"] == "call-42" and started[0]["line_id"] == "line-7"
    assert len(h.calls("/calls/start")) == 1                      # exactly one competition
    assert job.call_id == "call-42" and comp.call_id == "call-42"
    assert [k for k, _ in h.disp.events()] == ["call_started", "reps_committed", "call_ended"]
    committed = h.events("reps_committed")
    assert len(committed) == 1 and committed[0]["call_id"] == "call-42"
    payload = committed[0]["payload"]
    assert payload["judge_version"] == JUDGE_VERSION
    assert len(payload["reps"]) == 3
    assert h.events("call_ended")[0]["payload"]["rep_count"] == 3
    assert job.end_reason == "call complete" and h.disconnects, "the worker left the room"
    assert left_at >= comp.count_s + comp.reveal_s - 1
    assert comp.committed is True
    assert comp.path.startswith(str(tmp_path / "sessions")) and "call-42" in comp.path


def test_repeated_commit_is_not_resent(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-5")
        await h.settle()
        h.clock.t = T0 + 10
        h.job._deliver({**rep_ev(), "exercise": "pushups", "t": 10.0})
        h.clock.t = T0 + 30
        await h.job.comp.end("x")
        await h.job.comp.end("again")
        await h.job.close_competition()
    asyncio.run(go())
    assert [k for k, _ in h.disp.events()] == ["call_started", "reps_committed", "call_ended"]
    assert len(h.events("reps_committed")) == 1


@pytest.mark.parametrize("identity", ["doctor-probe", "caller-1", "chert-bridge"])
def test_warm_room_non_bridge_participant_starts_no_competition(tmp_path, monkeypatch, identity):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind(identity)
        await h.settle()
        await h.job.close_competition()
    asyncio.run(go())
    assert h.job.comp is None and h.job.comp_task is None and h.made == []
    assert h.disp.requests == []


def test_warm_room_nobody_joins_ends_cleanly_without_start(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        await h.settle()
        h.job.end("warm room timed out")                          # the framework closes an unused warm room
        await h.job.close_competition()
        await h.settle()
    asyncio.run(go())
    assert h.job.comp is None and h.made == [] and h.disp.requests == []
    assert h.job.done.is_set() and h.job.end_reason == "warm room timed out"


def test_warm_room_chert_api_hangup_uses_bridge_call_id(tmp_path, monkeypatch):
    # Real calls land in chert_warm rooms whose job metadata has no chert_call, so HANGUP_MODE=chert_api must end the
    # call by the bridge identity's suffix (chert-bridge-<chert call id>; matched Chert's id on the first live call).
    from challenge.worker.chert import ChertEndClient

    monkeypatch.setenv("HANGUP_MODE", "chert_api")
    monkeypatch.setenv("CHERT_FACETIME_TOKEN", "ftk_test")
    monkeypatch.setenv("CHERT_PROJECT_ID", "proj-test")
    ended = []

    async def end_call(self, call_id, sleep):
        ended.append(call_id)
        return True
    monkeypatch.setattr(ChertEndClient, "end_call", end_call)
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-b4986152")
        await h.settle()
        comp = h.job.comp
        assert comp.chert_call_id == "b4986152"
        for _ in range(2000):
            if h.job.done.is_set():
                break
            await h.clock.sleep(0.5)
        await h.job.close_competition()
        return comp
    comp = asyncio.run(go())
    assert ended == ["b4986152"]
    assert comp.chert_hangup == "acknowledged"
