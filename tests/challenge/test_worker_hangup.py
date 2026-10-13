"""Launch fixes on the worker side (audit 2026-10-13): HANGUP_MODE=delete_room (P0-2), bridge callers without video (P0-3),
the widened /calls/start deadline with a fail-closed cue and best-effort call_ended (P1-2), the guarded cue-track publish
(P1-3) and the job-count load function (P1-5). The LiveKit room service, the room, the participants and the dispatcher
are fakes; CoachJob, CompetitionCall and DispatcherClient are the real ones."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from challenge.worker import controller as ctl
from challenge.worker.client import DispatcherClient, DispatcherError
from tests.challenge.test_worker_controller import T0, Clock, Dispatcher, Rig, rep_ev, run
from tests.challenge.test_worker_warm_room_e2e import Harness

LK_ENV = {"LIVEKIT_URL": "wss://lk.example", "LIVEKIT_API_KEY": "k", "LIVEKIT_API_SECRET": "s"}


class FakeLiveKit:
    """livekit.api.LiveKitAPI stand-in: .room.delete_room(DeleteRoomRequest) and aclose(); `fail` deletes raise first."""

    def __init__(self, h, fail=0):
        self.h, self.fail = h, fail
        self.deleted, self.closed, self.made = [], 0, 0

    def __call__(self):
        self.made += 1
        return SimpleNamespace(room=SimpleNamespace(delete_room=self._delete), aclose=self._aclose)

    async def _delete(self, req):
        # what the dispatcher had received when the room went away (the commit must come first)
        self.deleted.append((req.room, [k for k, _ in self.h.disp.events()], round(self.h.clock.t - T0, 2)))
        if self.fail:
            self.fail -= 1
            raise RuntimeError("twirp error: unavailable")

    async def _aclose(self):
        self.closed += 1


def hangup_env(monkeypatch, mode="delete_room"):
    for k, v in LK_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("HANGUP_MODE", mode)


def make(monkeypatch, tmp_path, start=None, fail=0, mode="delete_room"):
    hangup_env(monkeypatch, mode)
    h = Harness(monkeypatch, tmp_path, {"chert_warm": True})
    if start is not None:
        h.disp.start = start
    h.lk = FakeLiveKit(h, fail=fail)
    h.job.lk_api = h.lk
    h.job.room.name = "warm-room-1"
    return h


async def run_to_end(h, limit=4000):
    for _ in range(limit):
        if h.job.done.is_set():
            break
        await h.clock.sleep(0.5)
    assert h.job.done.is_set()
    await h.job.close_competition()
    await h.settle()


# ------------------------------------------------------------------ P0-2 flags
def test_delete_room_mode_validated_and_reported(monkeypatch):
    for k in LK_ENV:
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ctl.UnsupportedMode, match="delete_room needs LIVEKIT_URL"):
        ctl.check_modes("delete_room", "audio_only")
    for k, v in LK_ENV.items():
        monkeypatch.setenv(k, v)
    notes = ctl.check_modes("delete_room", "audio_only")
    assert any("HANGUP_MODE=delete_room" in n and "falls back to leaving" in n for n in notes)
    for mode in ("leave_room", "unverified"):           # the old modes keep working
        ctl.check_modes(mode, "audio_only")
    from challenge.dispatcher.flags import Flags
    assert Flags.from_env({"HANGUP_MODE": "delete_room"}).HANGUP_MODE == "delete_room"


def test_worker_startup_log_reports_delete_room(tmp_path, monkeypatch, capsys):
    from facetime import worker
    hangup_env(monkeypatch)
    monkeypatch.setenv("CHALLENGE_MODE", "competition")
    monkeypatch.setenv("DISPATCHER_URL", "http://dispatcher")
    monkeypatch.setenv("DISPATCHER_TOKEN", "tok")
    assert worker.check_competition(worker.load_args()) is None
    out = capsys.readouterr().out
    assert "HANGUP_MODE delete_room" in out and "HANGUP_MODE=delete_room" in out
    monkeypatch.delenv("LIVEKIT_API_SECRET")
    assert "LIVEKIT_API_SECRET" in worker.check_competition(worker.load_args())


def test_delete_room_controller_timeline_has_no_hang_up_cue(tmp_path, monkeypatch):
    hangup_env(monkeypatch)

    async def go():
        r = Rig(tmp_path, hangup="delete_room")
        await r.call.start()
        await r.call.run()
        return r
    r = run(go())
    assert "hang_up" not in r.keys() and "check_texts" in r.keys()
    assert r.left and r.left[0][1] == "call complete"


# ------------------------------------------------------------------ P0-2 worker: delete after the commit
def test_full_call_deletes_the_room_after_the_commit(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-42")
        await h.settle()
        h.clock.t = T0 + 20
        h.job._deliver({**rep_ev(), "exercise": "pushups", "t": 20.0})
        await run_to_end(h)
    run(go())
    assert h.job.end_reason == "call complete"
    assert len(h.lk.deleted) == 1
    room, events_then, _ = h.lk.deleted[0]
    assert room == "warm-room-1"
    assert events_then == ["call_started", "reps_committed", "call_ended"]     # nothing left to send after the delete
    assert h.job.room_deleted is True and h.disconnects == []                  # deleted: no separate leave
    assert h.lk.closed == h.lk.made == 1


def test_delete_failure_falls_back_to_leaving_and_never_raises(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path, fail=5)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-43")
        await h.settle()
        await run_to_end(h)
    run(go())
    assert len(h.lk.deleted) == 2 and h.lk.closed == 2                         # two attempts, each client closed
    assert h.job.room_deleted is False and len(h.disconnects) == 1             # left the room instead
    assert [k for k, _ in h.disp.events()] == ["call_started", "reps_committed", "call_ended"]


def test_delete_retry_succeeds_on_second_attempt(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path, fail=1)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-44")
        await h.settle()
        await run_to_end(h)
    run(go())
    assert len(h.lk.deleted) == 2 and h.job.room_deleted is True and h.disconnects == []


def test_delete_without_livekit_credentials_falls_back(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)
    h.job.lk_api = None                                    # the real livekit.api.LiveKitAPI ...

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-45")
        await h.settle()
        monkeypatch.delenv("LIVEKIT_URL")                  # ... cannot be built: ValueError -> logged, leave
        await run_to_end(h)
    run(go())
    assert h.job.room_deleted is False and len(h.disconnects) == 1


@pytest.mark.parametrize("identity", [None, "doctor-probe"])
def test_empty_or_doctor_warm_room_is_never_deleted(tmp_path, monkeypatch, identity):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        if identity:
            h.bind(identity)
        await h.settle()
        h.job.end("warm room timed out")
        await h.job.close_competition()
    run(go())
    assert h.lk.made == 0 and h.lk.deleted == [] and h.job.room_deleted is None


def test_room_already_gone_is_not_deleted(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-46")
        await h.settle()
        h.job.end("room disconnected (ROOM_DELETED)")
        await h.job.close_competition()
    run(go())
    assert h.lk.deleted == [] and h.disconnects                     # a plain leave (a no-op on a gone room)


def test_rejected_call_hangs_up_after_its_cue(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path, start={"decision": "reject", "user_id": None, "reason": "not_your_turn",
                                           "cue": "not_your_turn"})
    said = []
    h.job.say_cue = lambda key, text, urgent: said.append((round(h.clock.t - T0, 2), key))

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-47")
        await h.settle()
        await run_to_end(h)
    run(go())
    assert [k for _, k in said] == ["not_your_turn"]
    assert h.job.end_reason == "rejected: not_your_turn"
    assert len(h.lk.deleted) == 1 and h.lk.deleted[0][1] == []      # nothing recorded for a reject
    assert h.lk.deleted[0][2] >= said[0][0]                         # after the cue started (the worker waits it out)


def test_fail_closed_sends_call_ended_before_the_delete(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)
    h.disp.down = {"/calls/start"}
    said = []
    h.job.say_cue = lambda key, text, urgent: said.append(key)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-48")
        await h.settle()
        await run_to_end(h)
    run(go())
    assert said == ["try_again"] and h.job.end_reason == "dispatcher_unreachable"
    assert len(h.lk.deleted) == 1 and h.lk.deleted[0][1] == ["call_ended"]
    assert h.events("call_ended")[0]["payload"]["rep_count"] == 0


def test_close_competition_waits_for_the_last_cue_before_deleting(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)
    state = {"left": 3}

    class Player:
        pending = None
        urgent = None

        @property
        def playing(self):
            state["left"] -= 1
            return {"text": "x"} if state["left"] > 0 else None
    h.job.player = Player()

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.bind("chert-bridge-call-49")
        await h.settle()
        await run_to_end(h)
    run(go())
    assert state["left"] <= 0 and len(h.lk.deleted) == 1


# ------------------------------------------------------------------ P0-3 no-video callers
def bridge(h, identity):
    p = SimpleNamespace(identity=identity, kind=0)
    h.job.room.remote_participants[identity] = p
    return p


def test_no_video_caller_is_started_cued_then_ended_and_hung_up(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)
    said = []
    h.job.say_cue = lambda key, text, urgent: said.append((round(h.clock.t - T0, 2), key))

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.job.on_participant_connected(bridge(h, "chert-bridge-call-50"))
        for _ in range(4000):
            if h.job.done.is_set():
                break
            await h.clock.sleep(0.1)
        starts_at = h.disp.requests and h.clock.t
        await h.job.close_competition()
        await h.settle()
        return starts_at
    run(go())
    assert len(h.calls("/calls/start")) == 1 and h.calls("/calls/start")[0]["call_id"] == "call-50"
    keys = [k for _, k in said]
    assert keys[:2] == ["welcome", ctl.NO_VIDEO_CUE]
    assert said[0][0] >= 8.0 - 0.01                                # /calls/start only after the 8 s grace
    assert h.job.end_reason == "no video" and h.job.comp.end_reason == "no video"
    committed = h.events("reps_committed")
    assert len(committed) == 1 and committed[0]["payload"]["reps"] == []
    assert h.events("call_ended")[0]["payload"]["rep_count"] == 0
    assert len(h.lk.deleted) == 1 and h.lk.deleted[0][1] == ["call_started", "reps_committed", "call_ended"]
    assert h.job.comp.committed is True


def test_no_video_caller_whose_video_arrives_later_continues(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.job.on_participant_connected(bridge(h, "chert-bridge-call-51"))
        while not h.calls("/calls/start"):
            await h.clock.sleep(0.1)
        await h.settle(20)
        h.job.video_task = asyncio.get_running_loop().create_future()   # the camera came on: a bound video track
        t_video = h.clock.t
        while h.clock.t - t_video < 30:
            await h.clock.sleep(0.25)
        done = h.job.done.is_set()
        task_done = h.job.novideo_task.done()
        h.job.video_task.cancel()
        h.job.video_task = None
        h.job.end("test over")
        await h.job.close_competition()
        return done, task_done
    done, task_done = run(go())
    assert done is False and task_done is True and h.job.comp.decision == "accept"
    assert len(h.calls("/calls/start")) == 1


def test_video_within_grace_needs_no_watch_start(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        p = bridge(h, "chert-bridge-call-52")
        h.job.on_participant_connected(p)
        await h.clock.sleep(2)
        h.bind("chert-bridge-call-52")                    # video arrived: the normal bind starts the call
        await h.settle(10)
        h.job.video_task = asyncio.get_running_loop().create_future()
        for _ in range(200):
            await h.clock.sleep(0.25)
        assert h.job.novideo_task.done()
        h.job.video_task.cancel()
        h.job.video_task = None
        h.job.end("test over")
        await h.job.close_competition()
    run(go())
    assert len(h.calls("/calls/start")) == 1


def test_no_video_caller_rejected_gets_no_camera_cue(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path, start={"decision": "reject", "user_id": None, "reason": "not_your_turn",
                                           "cue": "not_your_turn"})
    said = []
    h.job.say_cue = lambda key, text, urgent: said.append(key)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.job.on_participant_connected(bridge(h, "chert-bridge-call-53"))
        for _ in range(4000):
            if h.job.done.is_set():
                break
            await h.clock.sleep(0.1)
        await h.job.close_competition()
    run(go())
    assert said == ["not_your_turn"] and h.job.end_reason == "rejected: not_your_turn"
    assert len(h.lk.deleted) == 1


def test_bridge_that_leaves_before_the_grace_starts_nothing(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.job.on_participant_connected(bridge(h, "chert-bridge-call-54"))
        await h.clock.sleep(3)
        del h.job.room.remote_participants["chert-bridge-call-54"]
        for _ in range(100):
            await h.clock.sleep(0.25)
        assert h.job.novideo_task.done()
        h.job.end("caller left")
        await h.job.close_competition()
    run(go())
    assert h.disp.requests == [] and h.lk.deleted == []


def test_non_bridge_participant_starts_no_watch(tmp_path, monkeypatch):
    h = make(monkeypatch, tmp_path)

    async def go():
        h.job.loop = asyncio.get_running_loop()
        h.job.on_participant_connected(bridge(h, "doctor-probe"))
        await h.settle()
    run(go())
    assert h.job.novideo_task is None


# ------------------------------------------------------------------ P1-2 /calls/start deadline
def test_start_call_retries_until_the_widened_deadline():
    clock = Clock()
    disp = Dispatcher(down={"/calls/start"})

    async def go():
        c = DispatcherClient("http://dispatcher", "tok", timeout=3, retries=3, backoff_s=0.5,
                             transport=httpx.MockTransport(disp), sleep=clock.sleep, monotonic=clock)
        with pytest.raises(DispatcherError):
            await c.start_call("call-1", "line-1", deadline_s=ctl.START_DEADLINE_S)
        await c.aclose()
    run(go())
    assert ctl.START_DEADLINE_S >= 6
    assert len(disp.requests) > 4                                  # more than the default 1 + 3 attempts
    assert clock.t - T0 <= ctl.START_DEADLINE_S + 1e-6
    assert {b["call_id"] for _, b, _ in disp.requests} == {"call-1"}


def test_slow_dispatcher_answer_within_eight_seconds_is_accepted(tmp_path):
    async def go():
        d = Dispatcher(fail_status={"/calls/start": [503, 503, 503, 503]})
        r = Rig(tmp_path, disp=d)
        return r, await r.call.start()
    r, ok = run(go())
    assert ok is True and r.call.decision == "accept"
    assert [p for p in r.disp.paths() if p == "/calls/start"] == ["/calls/start"] * 5


def test_fail_closed_call_ended_happens_before_the_leave(tmp_path):
    seen = []

    async def go():
        r = Rig(tmp_path, disp=Dispatcher(down={"/calls/start"}))
        r.call._leave_fn = lambda why: seen.append((why, list(r.disp.events())))
        await r.call.start()
        return r
    run(go())
    assert seen == [("dispatcher_unreachable", [("call_ended", "call-1:call_ended")])]


def test_fail_closed_ended_is_best_effort(tmp_path):
    async def go():
        r = Rig(tmp_path, disp=Dispatcher(down={"/calls/start", "/calls/event"}))
        ok = await r.call.start()
        return r, ok
    r, ok = run(go())
    assert ok is False and len(r.left) == 1 and r.keys() == ["try_again"]


def test_call_locked_fail_closed_sends_no_end(tmp_path):
    async def go():
        r = Rig(tmp_path)
        lk = ctl.CallLock.try_acquire(r.call.path)          # the reconciler owns this call
        try:
            ok = await r.call.start()
        finally:
            lk.release()
        return r, ok
    r, ok = run(go())
    assert ok is False and r.call.reason == "call_locked" and r.keys() == ["try_again"]
    assert r.disp.events() == [] and len(r.left) == 1


# ------------------------------------------------------------------ P1-3 audio publish
def _audio_job(monkeypatch, tmp_path, fails):
    from tests.challenge.test_worker_controller import _job
    worker, job = _job(monkeypatch, tmp_path)
    attempts = []

    async def publish_track(track, opts):
        attempts.append(track)
        if len(attempts) <= fails:
            raise RuntimeError("engine: publish timed out")
    job.room.local_participant.publish_track = publish_track
    job.player = SimpleNamespace(track="cue-track")
    return worker, job, attempts


@pytest.mark.parametrize("fails,ok,n", [(0, True, 1), (1, True, 2), (2, False, 2)])
def test_audio_publish_retries_once(tmp_path, monkeypatch, fails, ok, n):
    worker, job, attempts = _audio_job(monkeypatch, tmp_path, fails)
    assert run(job.publish_audio()) is ok and len(attempts) == n


def test_audio_publish_failure_ends_the_job_cleanly(tmp_path, monkeypatch, capsys):
    from facetime import audio_out
    worker, job, attempts = _audio_job(monkeypatch, tmp_path, 5)
    job.a.cue_log = str(tmp_path / "cues.jsonl")
    job.a.avatar = False
    shut = []
    job.ctx.add_shutdown_callback = lambda cb: None

    async def connect(auto_subscribe=None):
        return None
    job.ctx.connect = connect
    job.ctx.shutdown = lambda reason=None: shut.append(reason)
    job.room.on = lambda *a, **k: None

    class StubPlayer:
        def __init__(self, **kw):
            self.track, self.playing, self.pending, self.stopped = "cue-track", None, None, False

        def stop(self):
            self.stopped = True
    monkeypatch.setattr(audio_out, "CuePlayer", StubPlayer)
    run(asyncio.wait_for(job.run(), 10))
    assert len(attempts) == 2 and job.end_reason == "audio publish failed" and shut == ["audio publish failed"]
    assert job.closed and job.player.stopped and job.thread is None
    assert "could not publish the cue audio track" in capsys.readouterr().out


# ------------------------------------------------------------------ P1-5 load
def test_load_counts_jobs_not_cpu(monkeypatch):
    from facetime import worker
    monkeypatch.delenv("WORKER_MAX_JOBS", raising=False)
    w = SimpleNamespace(active_jobs=[1])
    assert worker.job_count_load(w) == pytest.approx(1 / worker.WORKER_MAX_JOBS)
    assert worker.job_count_load(w) < 1.0                                                # one call: still available
    w.active_jobs = [1, 2]                                                               # call + replacement warm room
    assert worker.job_count_load(w) < 1.0
    w.active_jobs = list(range(worker.WORKER_MAX_JOBS))
    assert worker.job_count_load(w) == 1.0
    monkeypatch.setenv("WORKER_MAX_JOBS", "2")
    assert worker.job_count_load(SimpleNamespace(active_jobs=[1])) == 0.5
    assert worker.job_count_load(SimpleNamespace()) == 0.0
    a = worker.load_args(load_client=False)
    opts = worker.worker_options(a)
    assert opts.load_fnc is worker.job_count_load and opts.load_threshold == 1.0
