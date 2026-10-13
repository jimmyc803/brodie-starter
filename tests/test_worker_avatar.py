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
