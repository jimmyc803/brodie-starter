"""Synthetic kinematics test behavior, not device accuracy."""
import numpy as np
import pytest

from rtcoach.coach import make_counter
from rtcoach.curl_counter import CURL_NAMES, CurlCounter


def pose(angle=170, right=170, left_vis=0.99, right_vis=0.8):
    img = np.full((33, 5), 0.5)
    world = np.zeros((33, 3))
    for ids, degrees, vis in [((11, 13, 15), angle, left_vis), ((12, 14, 16), right, right_vis)]:
        img[list(ids), 3:5] = vis
        shoulder, elbow, wrist = ids
        world[shoulder] = [0, -1, 0]
        world[elbow] = [0, 0, 0]
        world[wrist] = [np.sin(np.radians(degrees)), -np.cos(np.radians(degrees)), 0]
    return img, world


def feed(counter, angles, **kwargs):
    return [n for a in angles if (n := counter.update(*pose(a, **kwargs), True)) is not None]


CYCLE = [170] * 4 + [140, 120, 95, 75, 60, 50, 50, 60, 85, 110, 130, 155, 170, 170]


def test_complete_cycles_and_turning_clock():
    rc = CurlCounter()
    assert feed(rc, CYCLE * 3) == [1, 2, 3]
    assert len(rc.events) == len(rc.turning) == 3
    assert all(t < e for t, e in zip(rc.turning, rc.events))


@pytest.mark.parametrize('angles', [
    [170] * 10 + [145, 130, 100, 80, 100, 140, 170] * 4,
    [50] * 10 + [80, 120, 170, 170],
    [170] * 10 + [64, 66] * 20 + [170] * 10,
    [170] * 10 + [50] * 2 + [170] * 2,
])
def test_incomplete_jitter_and_too_fast_do_not_count(angles):
    assert feed(CurlCounter(), angles) == []


def test_hold_at_top_does_not_repeat():
    rc = CurlCounter()
    assert feed(rc, CYCLE[:10] + [50] * 50) == []
    assert feed(rc, [80, 120, 155, 170, 170]) == [1]
    assert feed(rc, [170] * 50) == []


@pytest.mark.parametrize('loss', ['missing', 'occluded', 'nan', 'degenerate'])
def test_tracking_loss_discards_partial_rep(loss):
    rc = CurlCounter()
    feed(rc, CYCLE[:11])
    img, world = pose(50)
    if loss == 'occluded': img[13, 3] = 0.1
    if loss == 'nan': world[13] = np.nan
    if loss == 'degenerate': world[13] = world[11]
    rc.update(img if loss != 'missing' else None, world, loss != 'missing')
    assert feed(rc, [50, 90, 130, 170, 170]) == []
    assert feed(rc, CYCLE) == [1]


def test_no_switch_to_opposite_arm_mid_rep():
    rc = CurlCounter()
    feed(rc, CYCLE[:11])
    assert feed(rc, [50] * 10, right=170, left_vis=0.7, right_vis=0.99) == []
    assert feed(rc, CYCLE[11:]) == [1]
    rc.resettle()
    assert rc.count == 1
    assert feed(rc, [170] * len(CYCLE), right=170, left_vis=0.2) == []
    for angle in CYCLE:
        rc.update(*pose(170, right=angle, left_vis=0.2), True)
    assert rc.count == 2


def test_factory_aliases():
    from facetime.pipeline import map_exercise, spoken_name
    for name in CURL_NAMES:
        assert isinstance(make_counter({'v2': True}, name), CurlCounter)
        assert map_exercise(name) == 'bicep curls'
        assert spoken_name(map_exercise(name)) == 'bicep curls'


def test_live_pipeline_emits_contract_rep_and_resets_sets(monkeypatch):
    from facetime import pipeline
    from facetime.perception import Perception, Config

    class PoseInput:
        value = pose()
        def __init__(self, *args, **kwargs): pass
        def __call__(self, *args): return self.value
        def close(self): pass

    monkeypatch.setattr(pipeline, 'Pose', PoseInput)  # only the camera/pose input is substituted
    pipe = pipeline.FramePipeline(None, trigger='none')
    p = Perception(Config(exercise='bicep_curl', announce=False), pipe=pipe, clip_s={}, t0=0)
    emitted = []
    p.on_event(emitted.append)
    for i, angle in enumerate(CYCLE * 2):
        PoseInput.value = pose(angle)
        p.process_frame(np.zeros((288, 288, 3), dtype=np.uint8), t_recv=i / 10, t_ms=i * 100)
    reps = [e for e in emitted if e['type'] == 'rep']
    assert [e['n'] for e in reps] == [1, 2]
    assert all(e['exercise'] == 'bicep curls' and e['exercise_key'] == 'bicep_curl' for e in reps)
    assert all(e['turning_t'] < e['t'] and e['lag_s'] > 0 for e in reps)
    assert not [e for e in emitted if e['type'] == 'fault']
    pipe.set_exercise('bicep curls')
    assert pipe.coach.rc.count == 0
    assert pipe.coach.clf is None and pipe.coach.trig is None
    p.close()


def test_assignment_plan_warmup_preserves_first_curl(monkeypatch):
    from facetime import pipeline
    from facetime.perception import Config, Perception

    class PoseInput:
        value = pose()
        def __init__(self, *args, **kwargs): pass
        def __call__(self, *args): return self.value
        def close(self): pass

    monkeypatch.setattr(pipeline, 'Pose', PoseInput)
    pipe = pipeline.FramePipeline(None, trigger='none')
    p = Perception(Config(plan='bicep curls:2', announce=False), pipe=pipe, clip_s={}, t0=0)
    events = []
    p.on_event(events.append)
    for i, angle in enumerate([170] * 3 + CYCLE * 2 + [170] * 70):
        PoseInput.value = pose(angle)
        p.process_frame(np.zeros((288, 288, 3), dtype=np.uint8), t_recv=i / 10, t_ms=i * 100)
    assert [e['n'] for e in events if e['type'] == 'rep'] == [1, 2]
    assert p.session.done
    p.close()
