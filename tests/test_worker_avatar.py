import asyncio
from types import SimpleNamespace

import pytest

from facetime import worker


@pytest.mark.parametrize('argv, env, on', [([], None, True), (['--no-avatar'], None, False), ([], '0', False), ([], '1', True)])
def test_avatar_flag(argv, env, on, monkeypatch):
    if env is None: monkeypatch.delenv('AVATAR', raising=False)
    else: monkeypatch.setenv('AVATAR', env)
    a, _ = worker.build_parser().parse_known_args(argv)
    assert a.avatar is on


def test_avatar_loop_publishes_coach_video_and_streams_frames(monkeypatch):
    published, captured = [], []
    class Source:
        def __init__(self, w, h): self.size = (w, h)
        def capture_frame(self, f): captured.append(f)
    monkeypatch.setattr(worker.rtc, 'VideoSource', Source)
    monkeypatch.setattr(worker.rtc.LocalVideoTrack, 'create_video_track', staticmethod(lambda name, src: SimpleNamespace(name=name)))
    async def publish_track(track, opts): published.append(track.name)
    job = worker.CoachJob.__new__(worker.CoachJob)
    job.a = SimpleNamespace(avatar_fps=50.0); job.player = SimpleNamespace(playing=object())
    job.room = SimpleNamespace(local_participant=SimpleNamespace(publish_track=publish_track))
    job.stop = worker.threading.Event()
    async def go():
        t = asyncio.create_task(job.avatar_loop())
        for _ in range(300):
            if len(captured) >= 3 or t.done(): break
            await asyncio.sleep(0.01)
        job.stop.set(); await asyncio.wait_for(t, 2)
    asyncio.run(go())
    assert published == ['coach-video'] and len(captured) >= 3


def _mirror_job(monkeypatch, published, captured, sizes):
    class Source:
        def __init__(self, w, h): sizes.append((w, h))
        def capture_frame(self, f): captured.append((f.width, f.height))
    monkeypatch.setattr(worker.rtc, 'VideoSource', Source)
    monkeypatch.setattr(worker.rtc.LocalVideoTrack, 'create_video_track', staticmethod(lambda name, src: SimpleNamespace(name=name)))
    async def publish_track(track, opts): published.append((track.name, opts.video_encoding.max_bitrate))
    job = worker.CoachJob.__new__(worker.CoachJob)
    job.a = SimpleNamespace(avatar_fps=50.0, mirror=True); job.player = SimpleNamespace(playing=None)
    job.room = SimpleNamespace(local_participant=SimpleNamespace(publish_track=publish_track))
    job.stop = worker.threading.Event(); job.mirror_in = None; job.mirror_live = False; job.mirror_state = None
    return job


def _run(job, until):
    async def go():
        t = asyncio.create_task(job.avatar_loop())
        for _ in range(800):
            if until() or t.done(): break
            await asyncio.sleep(0.01)
        job.stop.set(); await asyncio.wait_for(t, 5)
    asyncio.run(go())


def test_mirror_loop_publishes_720x1280_and_renders_the_newest_frame(monkeypatch):
    import numpy as np, time
    published, captured, sizes = [], [], []
    job = _mirror_job(monkeypatch, published, captured, sizes)
    seen = []
    from facetime import pushup_mirror
    orig = pushup_mirror.PushupMirror.render
    def spy(self, rgb, lm, thr=None, state=None, now=None, seq=None):
        seen.append((None if rgb is None else rgb.shape, seq, state.count))
        return orig(self, rgb, lm, thr, state, now, seq)
    monkeypatch.setattr(pushup_mirror.PushupMirror, 'render', spy)
    def feed_once():
        if job.mirror_live and job.mirror_in is None and not any(s[0] for s in seen):
            job.mirror_in = (np.full((720, 1280, 3), 90, np.uint8), None, 7, time.monotonic())
            job.mirror_rep(True, [], False); job.mirror_rep(False, ['too_shallow'], False); job.mirror_rep(True, [], True)
        return any(s[0] == (720, 1280, 3) for s in seen) and len(captured) >= 3
    _run(job, feed_once)
    assert published == [('coach-video', 1_500_000)] and sizes == [(720, 1280)]
    assert set(captured) == {(720, 1280)}
    assert seen[0][0] is None                                     # idle card before the first frame
    assert any(s[0] == (720, 1280, 3) and s[1] == 7 and s[2] == 1 for s in seen)   # valid, not in a challenge: counted once
    assert job.mirror_live is False and job.mirror_in is None     # nothing kept after the loop


def test_mirror_render_failures_fall_back_to_the_plain_face(monkeypatch):
    published, captured, sizes = [], [], []
    job = _mirror_job(monkeypatch, published, captured, sizes)
    from facetime import pushup_mirror
    def boom(self, *a, **k): raise RuntimeError('render broke')
    monkeypatch.setattr(pushup_mirror.PushupMirror, 'render', boom)
    _run(job, lambda: len(captured) >= 14)
    assert len(captured) >= 14 and set(captured) == {(720, 1280)}  # every tick still sends a frame, same size


@pytest.mark.parametrize('stored, count, flashed', [
    ({'valid': True, 'reject_reasons': [], 'in_challenge': False}, 1, True),
    ({'valid': False, 'reject_reasons': ['hips_sag'], 'in_challenge': False}, 0, True),
    ({'valid': True, 'reject_reasons': [], 'in_challenge': True}, 0, False),
    (None, 0, False),                                              # outside the count window: not recorded, not shown
])
def test_competition_reps_on_screen_follow_what_the_controller_records(stored, count, flashed):
    job = worker.CoachJob.__new__(worker.CoachJob)
    job.events = asyncio.Queue(); job.recap = None; job.closed = False; job.a = SimpleNamespace(publish_data=False)
    job.comp = SimpleNamespace(on_rep=lambda ev, t=None: stored); job.per_wall0 = 0.0; job.clock = lambda: 0.0
    job.mirror_live = True; job.mirror_state = None
    job._deliver({'type': 'rep', 't': 1.0, 'n': 1, 'exercise': 'pushups', 'valid': True})
    st = job.mirror_state
    assert (st.count if st else 0) == count and ((st is not None and st.verdict_ok is not None) == flashed)
