"""Strict judge in the live path (task 11): JudgeRuntime, the FramePipeline / Perception landmark injection seam, people
counting in rtcoach.pose and the side-view push-up adaptation of RepCounter2. No MediaPipe: synthetic landmarks are fed at
FramePipeline.process_landmarks / Perception.process_landmarks (pose_variant=None builds the pipeline without a pose model)."""
from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from challenge.judge.gates import DEFAULT_THRESHOLDS, JUDGE_VERSION, judge_rep
from challenge.judge.metrics import FrameObs
from challenge.judge.runtime import JudgeRuntime
from challenge.judge.synth import accumulate_clip, synth_pushups
from facetime.perception import Config, Perception
from facetime.pipeline import REP_PARAMS_V2, FramePipeline
from rtcoach.pose import PrimaryTracker, count_persons, is_duplicate, select_primary
from rtcoach.repcount2 import RepCounter2, pose_signals

EVENT_FIELDS = {'valid', 'reject_reasons', 'metrics', 'judge_version', 'cue', 'in_challenge'}
C2_METRICS = {'min_elbow_deg_l', 'min_elbow_deg_r', 'top_elbow_deg', 'max_hip_line_dev_deg', 'min_knee_deg',
              'knee_floor_contact', 'shoulder_wrist_drop', 'shoulder_elbow_gap', 'min_keypoint_conf', 'frame_conf_frac',
              'persons_in_frame', 'rep_duration_s', 'torso_ok', 'side', 'classifier_labels'}
RP = {k: v for k, v in REP_PARAMS_V2.items() if k != 'v2'}


def pipeline(judge=True, **kw):
    return FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none', judge=judge, **kw)


def shifted(clip, dt):
    return [dataclasses.replace(f, t=round(f.t + dt, 6)) for f in clip.frames]


def run_pipeline(clip, judge=True):
    """Feed a synth clip through the seam; returns (pipe, [(n, t, fields)])."""
    pipe = pipeline(judge)
    reps = []
    for f in clip.frames:
        r = pipe.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=f.persons,
                                   t_ms=round(f.t * 1000), aspect=f.aspect)
        assert ('judge' in r) == judge
        for n, fields in r.get('judge', {}).items():
            reps.append((n, f.t, fields))
    return pipe, reps


# ---- FramePipeline-level judge path ----

@pytest.mark.parametrize('side', ['left', 'right'])
def test_clean_side_view_reps_counted_and_valid(side):
    clip = synth_pushups(n_reps=6, lead_in_s=2.0, side=side, noise=0.002, seed=3)
    pipe, reps = run_pipeline(clip)
    assert pipe.coach.rc.count == 6
    assert [n for n, _, _ in reps] == list(range(1, 7))
    for n, t, v in reps:
        assert set(v) == EVENT_FIELDS
        assert v['valid'] is True and v['reject_reasons'] == [] and v['cue'] is None, (n, v)
        assert v['judge_version'] == JUDGE_VERSION and v['in_challenge'] is False
        assert C2_METRICS <= set(v['metrics']) and v['metrics']['side'] == side
    assert pipe.coach.rc.side_i and pipe.coach.rc.side_i[0][1] == side     # the counter used the visible arm


def test_knee_reps_counted_but_invalid():
    clip = synth_pushups(n_reps=5, lead_in_s=2.0, knees_down=True)
    pipe, reps = run_pipeline(clip)
    assert pipe.coach.rc.count == 5 and len(reps) == 5
    assert all(not v['valid'] and v['reject_reasons'][0] == 'knees_down' for _, _, v in reps)
    cues = [v['cue'] for _, _, v in reps]
    assert cues[0] == 'knees_down'
    # rate limited: reps fire 2 s apart and cue_min_gap_s is 4 s -> every other rep gets the cue
    assert cues == ['knees_down', None, 'knees_down', None, 'knees_down']


def test_two_people_counted_but_invalid_multiple_people():
    clip = synth_pushups(n_reps=4, lead_in_s=2.0, extra_person=True)
    pipe, reps = run_pipeline(clip)
    assert pipe.coach.rc.count == 4
    assert all(v['reject_reasons'][0] == 'multiple_people' and v['cue'] in ('multiple_people', None) for _, _, v in reps)
    assert reps[0][2]['metrics']['persons_in_frame'] == 2


def test_shallow_reps_invalid_too_shallow():
    clip = synth_pushups(n_reps=4, lead_in_s=2.0, depth=110)
    _, reps = run_pipeline(clip)
    assert len(reps) == 4 and all(v['reject_reasons'] == ['too_shallow'] for _, _, v in reps)


def test_judge_off_leaves_results_unchanged():
    clip = synth_pushups(n_reps=4, lead_in_s=2.0)
    on, reps = run_pipeline(clip, judge=True)
    off, none = run_pipeline(clip, judge=False)
    assert none == [] and off.judge is None and len(reps) == 4
    assert on.coach.rc.events == off.coach.rc.events
    assert off.num_poses == 1 and on.num_poses == 2


def test_judge_only_for_pushups_and_env_default(monkeypatch):
    p = FramePipeline(None, exercise='squats', pose_variant=None, trigger='none', judge=True)
    assert p.judge is None
    monkeypatch.setenv('CHALLENGE_MODE', 'competition')
    assert FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none').judge is not None
    monkeypatch.setenv('CHALLENGE_MODE', 'off')
    assert FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none').judge is None


def test_process_without_pose_model_raises():
    with pytest.raises(RuntimeError, match='process_landmarks'):
        pipeline().process(np.zeros((288, 512, 3), np.uint8))


# ---- Perception (event schema) through the same seam ----

def test_perception_rep_events_carry_verdicts():
    clip = synth_pushups(n_reps=5, lead_in_s=3.0, knees_down=True)
    per = Perception(Config(exercise='pushups', announce=False, judge=True), pipe=pipeline(), clip_s=lambda _t: None, t0=0)
    events = []
    per.on_event(events.append)
    try:
        for f in clip.frames:
            per.process_landmarks(f.img, f.world, f.persons, t_recv=f.t, t_ms=round(f.t * 1000), aspect=f.aspect)
    finally:
        per.close()
    reps = [e for e in events if e['type'] == 'rep']
    assert [e['n'] for e in reps] == [1, 2, 3, 4, 5]
    assert all(EVENT_FIELDS <= set(e) and e['valid'] is False and 'knees_down' in e['reject_reasons'] for e in reps)


def test_perception_challenge_window_marks_reps():
    clip = synth_pushups(n_reps=5, lead_in_s=3.0)
    per = Perception(Config(exercise='pushups', announce=False, judge=True), pipe=pipeline(), clip_s=lambda _t: None, t0=0)
    events = []
    per.on_event(events.append)
    try:
        for f in clip.frames:
            if abs(f.t - 1.0) < 1e-9:
                assert per.set_challenge_window(5.5, 8.5) is True
            per.process_landmarks(f.img, f.world, f.persons, t_recv=f.t, t_ms=round(f.t * 1000), aspect=f.aspect)
    finally:
        per.close()
    reps = [e for e in events if e['type'] == 'rep']
    assert [e['in_challenge'] for e in reps] == [5.5 <= e['t'] <= 8.5 for e in reps]
    assert any(e['in_challenge'] for e in reps) and not all(e['in_challenge'] for e in reps)


# ---- JudgeRuntime ----

def _feed(j, clip):
    out = []
    pending = list(clip.fire_times)
    for f in clip.frames:
        j.on_frame(f)
        while pending and f.t >= pending[0] - 1e-9:
            t = pending.pop(0)
            out.append(j.on_rep({'t': t, 'n': len(out) + 1}))
    return out


def test_runtime_labels_window_and_classifier_veto():
    clip = synth_pushups(n_reps=3, lead_in_s=1.0)
    j = JudgeRuntime()
    j.on_label(0.5, 'pushups - shallow')        # before rep 1 fires (3.0): belongs to rep 1
    j.on_label(3.5, 'pushups - good form?')     # rep 2 window, not a veto label
    v = _feed(j, clip)
    assert v[0].reasons == ['classifier:pushups - shallow'] and v[0].cue_key == 'too_shallow'
    assert v[1].valid and v[1].labels == ['pushups - good form?']
    assert v[2].valid and v[2].labels == []


def test_runtime_most_important_reason_wins_cue():
    clip = synth_pushups(n_reps=2, lead_in_s=1.0, knees_down=True, extra_person=True)
    v = _feed(JudgeRuntime(), clip)
    assert v[0].reasons[:2] == ['multiple_people', 'knees_down'] and v[0].cue_key == 'multiple_people'


def test_runtime_cue_gap_from_thresholds_and_bad_window():
    clip = synth_pushups(n_reps=4, lead_in_s=1.0, depth=110)
    v = _feed(JudgeRuntime({'cue_min_gap_s': 0}), clip)
    assert [x.cue_key for x in v] == ['too_shallow'] * 4
    with pytest.raises(ValueError):
        JudgeRuntime().set_challenge_window(3, 2)


def test_runtime_frame_without_pose_is_not_in_frame():
    j = JudgeRuntime()
    for k in range(20):
        j.on_frame(FrameObs(t=k / 10, img=None, world=None, persons=0))
    v = j.on_rep({'t': 1.9})
    assert not v.valid and v.reasons[0] == 'not_in_frame' and v.cue_key == 'not_in_frame'


# ---- rtcoach.pose people counting (pure helpers, no MediaPipe) ----

def _body(cx, cy, w=0.3, h=0.3, vis=0.95):
    a = np.zeros((33, 5), np.float32)
    rng = np.random.default_rng(int(cx * 100 + cy * 10))
    a[:, 0] = cx + rng.uniform(-w / 2, w / 2, 33)
    a[:, 1] = cy + rng.uniform(-h / 2, h / 2, 33)
    a[[0, 1], 0] = cx - w / 2, cx + w / 2
    a[[0, 1], 1] = cy - h / 2, cy + h / 2
    a[:, 3] = vis
    a[:, 4] = 0.99
    return a


def test_count_persons_two_people_duplicates_and_ghosts():
    p1, p2 = _body(0.3, 0.5), _body(0.75, 0.5)
    assert count_persons([p1]) == 1
    assert count_persons([p1, p2]) == 2
    dup = p1.copy()
    dup[:, :2] = p1[:, :2] * 0.9 + np.array([0.03, 0.05])           # a partial copy of the same body inside its bbox
    assert count_persons([p1, dup]) == 1
    assert count_persons([p1, _body(0.75, 0.5, vis=0.3)]) == 1      # low torso visibility: not a person


def test_select_primary_largest_then_nearest_centroid():
    small, big = _body(0.2, 0.5, w=0.1, h=0.1), _body(0.7, 0.5, w=0.4, h=0.4)
    assert select_primary([small, big]) == 1
    prev = np.nanmean(small[[11, 12, 23, 24], :2], axis=0)
    assert select_primary([small, big], prev) == 0                 # stays on the tracked person


# ---- RepCounter2 side-view adaptation ----

def _front(clip):
    """Both arms clearly visible (a front-view visibility profile) for every frame of a clip."""
    out = []
    for f in clip.frames:
        img = f.img.copy()
        img[:, 3] = np.maximum(img[:, 3], 0.95)
        out.append((img, f.world))
    return out


@pytest.mark.parametrize('ex', ['pushups', 'squats'])
def test_front_view_counter_output_unchanged(ex):
    """Front view (both arms visible): the side-view rule never engages and the counter is identical to side_view=False,
    which is the pre-change code path (bilateral elbow sum)."""
    frames = _front(synth_pushups(n_reps=6, lead_in_s=2.0, noise=0.003, seed=1))
    on = RepCounter2(fps=10, exercise=ex, side_view=True, **RP)
    off = RepCounter2(fps=10, exercise=ex, side_view=False, **RP)
    outs = [(on.update(a, w, True), off.update(a, w, True)) for a, w in frames]
    assert all(x == y for x, y in outs)
    assert on.events == off.events and on.turning == off.turning and on.side_i == []
    if ex == 'pushups':
        assert on.count == 6


def test_side_view_default_only_for_pushups():
    assert RepCounter2(fps=10, exercise='pushups', **RP).side_view is True
    assert RepCounter2(fps=10, exercise='squats', **RP).side_view is False


def test_side_view_elbow_signal_keeps_scale_with_hidden_arm():
    """Hidden arm frozen (MediaPipe's guess does not follow the rep): the bilateral sum swings half as much, the
    side-view signal (2 x visible arm / 90) keeps the full two-arm scale."""
    clip = synth_pushups(n_reps=2, lead_in_s=1.0)
    frozen = clip.frames[0].img.copy()
    bil, side = [], []
    for f in clip.frames:
        img = f.img.copy()
        img[[12, 14, 16], :2] = frozen[[12, 14, 16], :2]
        bil.append(pose_signals(img, f.world, 0.2, 0.5)['elbow'])
        side.append(pose_signals(img, f.world, 0.2, 0.5, arm_side='left')['elbow'])
    sw_b, sw_s = np.ptp(bil), np.ptp(side)
    assert sw_s == pytest.approx(2 * sw_b, rel=0.02)
    clean = [pose_signals(f.img, f.world, 0.2, 0.5)['elbow'] for f in clip.frames]
    assert sw_s == pytest.approx(np.ptp(clean), rel=0.1)


def test_overlapping_distinct_people_counted_as_two():
    """Two people whose boxes overlap by more than half (one doing push-ups just behind the other) are not a duplicate:
    the boxes are not nested and the landmarks do not match."""
    p1 = _body(0.40, 0.55, w=0.40, h=0.20)
    p2 = _body(0.50, 0.50, w=0.40, h=0.20)
    p2[:, :2] += np.random.default_rng(7).normal(0, 0.03, (33, 2)).astype(np.float32)
    assert not is_duplicate(p1, p2)
    assert count_persons([p1, p2]) == 2 and count_persons([p2, p1]) == 2
    standing = _body(0.45, 0.45, w=0.10, h=0.60)                    # someone standing over the plank
    assert count_persons([p1, standing]) == 2


def test_primary_tracker_flags_switch_and_keeps_track_through_dropouts():
    a, b = _body(0.25, 0.5), _body(0.75, 0.5)
    tr = PrimaryTracker()
    assert tr.update([a]) == (0, False)
    assert tr.update([]) == (None, False)                          # dropout: the tracked centroid is kept
    assert tr.update([b, a]) == (1, False)                         # still the same person, in either order
    assert tr.update([b]) == (0, True)                             # only someone else is left: a switch
    assert tr.update([b]) == (0, False)


# ---- fix round: person switch, held reps, prewarmed challenge windows ----

def test_person_switch_restarts_partial_rep_and_judge_window():
    a = synth_pushups(n_reps=3, lead_in_s=2.0, tail_s=0.0, knees_down=True)
    first = [f for f in a.frames if f.t <= a.frames[-1].t - 1.0]     # person A leaves mid-rep 3
    b = synth_pushups(n_reps=3, lead_in_s=1.0, body='tall')         # person B, clean
    later = shifted(b, first[-1].t + 0.1)

    def run(flag):
        pipe = pipeline()
        out = []
        for k, f in enumerate(first + later):
            r = pipe.process_landmarks(f.img, f.world, f.persons, round(f.t * 1000), f.aspect,
                                       switched=flag and k == len(first))
            out += [(n, v) for n, v in r.get('judge', {}).items()]
        return pipe, out

    pipe, out = run(True)
    assert pipe.n_switch == 1 and pipe.coach.rc.n_restart == 1
    assert [n for n, _ in out] == [1, 2, 3, 4, 5]                   # A's partial rep dropped, B's 3 reps counted
    assert [v['valid'] for _, v in out] == [False, False, True, True, True]
    _, mixed = run(False)                                           # without the switch a rep spans both people
    assert [v['valid'] for _, v in mixed][:3] == [False, False, False] and len(mixed) == 6


def test_two_reps_confirmed_on_one_frame_keep_their_own_windows():
    """Gap gate: a rep after a long pause is held until the next rep confirms it, then both count on one frame. Each is
    judged on its own window and fire time (the held one does not swallow the other's frames)."""
    a = synth_pushups(n_reps=4, lead_in_s=2.0, tail_s=0.0)
    b = synth_pushups(n_reps=3, lead_in_s=4.0)
    frames = a.frames + shifted(b, a.frames[-1].t + 0.1)
    pipe = pipeline(rep_params=dict(REP_PARAMS_V2, gap_gate=1.5))
    by_frame = []
    for f in frames:
        r = pipe.process_landmarks(f.img, f.world, f.persons, round(f.t * 1000), f.aspect)
        if r.get('judge'):
            by_frame.append(r['judge'])
    rc = pipe.coach.rc
    assert rc.deferred, 'the scenario must exercise the held-rep path'
    double = next(d for d in by_frame if len(d) == 2)
    (n1, v1), (n2, v2) = sorted(double.items())
    assert v1['valid'] and v2['valid'], (v1['reject_reasons'], v2['reject_reasons'])
    assert v1['metrics']['rep_duration_s'] > 4.0 and v2['metrics']['rep_duration_s'] == pytest.approx(2.0, abs=0.15)
    assert rc.fire_i[n1 - 1] < rc.events[n1 - 1] == rc.fire_i[n2 - 1]


def test_challenge_window_set_before_first_frame_on_prewarmed_pipeline():
    """Prewarmed pipeline (no exercise yet) and an event clock 100 s off the pipeline clock: a window set before any
    frame is queued and applied once the judge clock offset is known."""
    clip = synth_pushups(n_reps=5, lead_in_s=3.0)
    pipe = FramePipeline(None, pose_variant=None, trigger='none', judge=True)
    assert pipe.judge is None
    per = Perception(Config(exercise='pushups', announce=False, judge=True), pipe=pipe, clip_s=lambda _t: None, t0=0)
    events = []
    per.on_event(events.append)
    try:
        assert per.set_challenge_window(105.5, 108.5) is False      # queued
        for f in clip.frames:
            per.process_landmarks(f.img, f.world, f.persons, t_recv=f.t + 100.0, t_ms=round(f.t * 1000), aspect=f.aspect)
    finally:
        per.close()
    reps = [e for e in events if e['type'] == 'rep']
    assert len(reps) == 5
    assert [e['in_challenge'] for e in reps] == [105.5 <= e['t'] <= 108.5 for e in reps]
    assert any(e['in_challenge'] for e in reps) and not all(e['in_challenge'] for e in reps)


# ---- translation invariance ----

def _translated(clip, dx, dy):
    out = dataclasses.replace(clip, frames=[dataclasses.replace(f, img=f.img.copy()) for f in clip.frames])
    for f in out.frames:
        f.img[:, 0] += dx
        f.img[:, 1] += dy
    return out


@pytest.mark.parametrize('seed', range(3))
@pytest.mark.parametrize('kw', [dict(hip_offset=0.05, depth=90.0), dict(depth=100.0), dict(hip_offset=-0.05)])
def test_verdicts_invariant_to_body_placement_in_frame(kw, seed):
    """Moving the whole body in the frame must not change any verdict, on the accumulator and the RepCounter2 path.
    Shifts keep every landmark inside the frame (synth y spans ~0.39-0.94, so up to 0.3 up and 0.05 down); a landmark
    leaving the frame legitimately changes the verdict (not_in_frame)."""
    clip = synth_pushups(noise=0.02, seed=seed, **kw)
    D = DEFAULT_THRESHOLDS
    base_acc = [judge_rep(m, D) for m in accumulate_clip(clip, D)]
    base_pipe = [(f['valid'], f['reject_reasons']) for _, _, f in run_pipeline(clip)[1]]
    assert base_pipe
    for dx, dy in ((0.0, -0.3), (0.0, -0.15), (0.0, 0.05), (-0.09, 0.0), (0.15, -0.2)):
        moved = _translated(clip, dx, dy)
        assert [judge_rep(m, D) for m in accumulate_clip(moved, D)] == base_acc, (dx, dy)
        assert [(f['valid'], f['reject_reasons']) for _, _, f in run_pipeline(moved)[1]] == base_pipe, (dx, dy)
