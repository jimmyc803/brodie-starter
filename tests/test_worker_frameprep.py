"""The worker's frame prep wiring (facetime/worker.py prep_frame / check_orientation / _mirror_frame's newer frame)."""
from types import SimpleNamespace

import numpy as np

from facetime import worker
from facetime.frameprep import FramePrep, rotate


def _job():
    job = worker.CoachJob.__new__(worker.CoachJob)            # like the other worker tests: no __init__
    job.pipe = SimpleNamespace(pose_variant='full')
    return job


def _bridge_frame(content):
    out = np.zeros((720, 1280, 3), np.uint8); h, w = content.shape[:2]; x0 = (1280 - w) // 2
    out[:h, x0:x0 + w] = content
    return out


def test_prep_frame_crops_the_bridge_letterbox():
    job = _job(); raw = _bridge_frame(np.full((274, 486, 3), 90, np.uint8))
    up = job.prep_frame(raw, 1.0)
    assert abs(up.shape[0] - 274) <= 4 and abs(up.shape[1] - 486) <= 4 and up.min() == 90
    assert isinstance(job.prep, FramePrep)


def test_prep_frame_failure_falls_back_to_the_raw_frame(capsys):
    job = _job()

    class Broken:
        def __call__(self, rgb, now): raise RuntimeError('boom')
    job.prep = Broken(); raw = np.zeros((720, 1280, 3), np.uint8)
    for _ in range(3): assert job.prep_frame(raw, 1.0) is raw
    assert job.prep_fails == 3
    assert capsys.readouterr().out.count('frame prep failed') == 1      # logged once, not per frame


def test_check_orientation_logs_a_turn_and_survives_a_probe_failure(capsys):
    job = _job()
    job.check_orientation(np.zeros((4, 4, 3), np.uint8), None)          # no prep yet: nothing to do
    calls = []

    class Prep:
        rotation = 0
        def observe(self, raw, lm, now):
            calls.append(now)
            if len(calls) == 1: raise RuntimeError('probe died')
            return (0, 90)
        def diag(self): return 'rot 90'
    job.prep = Prep()
    job.check_orientation(None, None, 5.0)
    assert job.orient_fails == 1
    job.check_orientation(None, None, 6.0)
    out = capsys.readouterr().out
    assert calls == [5.0, 6.0] and 'orientation check failed' in out and 'turned 0 -> 90' in out


class _Renderer:
    def __init__(self): self.got = None
    def render(self, rgb, lm, thr, st, now=None, seq=None, landscape=False, layout=None):
        self.got = rgb; return np.zeros((1280, 720, 3), np.uint8)


def test_mirror_frame_shows_the_newer_caller_frame_through_the_same_crop(monkeypatch):
    job = _job(); job.mirror_thresholds = lambda: None
    content = np.full((360, 640, 3), 100, np.uint8); content[:40, :40] = (255, 0, 0)
    side = rotate(content, 270)
    job.prep = FramePrep(probe=lambda img: None); job.prep.rotation = 90
    pose_rgb = job.prep(_bridge_frame(side), 0.0)                        # what the pose saw: upright, 640 wide
    assert pose_rgb.shape[:2] == (360, 640)
    newer_raw = _bridge_frame(side); newer_raw[newer_raw > 0] = 120
    monkeypatch.setattr(worker, 'frame_to_rgb', lambda f: f)
    r = _Renderer(); fails, stats = [0, 0], dict(n=0, ms=0.0)
    out = job._mirror_frame(r, None, (pose_rgb, None, 1, 0.0), SimpleNamespace(speaking=False), 0.0, fails, stats, newer=newer_raw)
    assert out is not None and fails == [0, 0]
    assert r.got.shape == pose_rgb.shape and r.got.max() == 120             # the newer picture, cropped + turned
    r2 = _Renderer()                                                       # another frame size (a resize mid-call): the pose's frame
    job._mirror_frame(r2, None, (pose_rgb, None, 1, 0.0), SimpleNamespace(speaking=False), 0.0, fails, stats,
                      newer=np.zeros((480, 640, 3), np.uint8))
    assert r2.got is pose_rgb
