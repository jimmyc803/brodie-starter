"""j5 front-on cameras (docs/challenge/CALIBRATION.md "j5"): a phone standing in front of the lifter instead of
side-on. Clean reps must count and be accepted from every front angle, and half reps must never be accepted from any
of them -- before j5 a raised front phone accepted 5 of 6 half reps, because perspective shrinks the shoulder's image
travel until the shoulder_wrist_drop crutch reads deep (D-45)."""
import numpy as np
import pytest

from challenge.judge import DEFAULT_THRESHOLDS, RepMetrics, judge_rep
from challenge.judge.metrics import ELBOW_WORLD_GAP_DEG, _straighter
from challenge.judge.synth import synth_pushups
from facetime.pipeline import FramePipeline

D = DEFAULT_THRESHOLDS

# yaw 90 = the phone straight in front of the lifter (head toward it), 75/60 = angled in front, -90 = behind the feet.
# Pitch is how high it is propped. Raised rear views (-90 with pitch >= 20) are left out: the realtime counter does not
# count reps there at all (pre-existing, CALIBRATION.md "j5").
FRONT = [(90, 0), (90, 10), (90, 20), (90, 35), (90, 50), (75, 0), (75, 10), (75, 20), (60, 0), (60, 10), (-90, 0),
         (-90, 10)]


def run(frames, judge_thr=None):
    pipe = FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none', judge=True, judge_thr=judge_thr)
    out = []
    for f in frames:
        r = pipe.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=f.persons,
                                   t_ms=round(f.t * 1000), aspect=f.aspect)
        out += list(r.get('judge', {}).values())
    return pipe, out


def clip(camera, depth=75.0, fps=10.0):
    return synth_pushups(n_reps=6, rep_s=1.2, lead_in_s=2.0, fps=fps, noise=0.004, seed=1, depth=depth,
                         camera=camera).frames


@pytest.mark.parametrize("camera", FRONT)
def test_clean_reps_counted_and_accepted_from_a_phone_in_front(camera):
    pipe, reps = run(clip(camera))
    assert pipe.coach.rc.count == 6 and len(reps) == 6, (camera, pipe.coach.rc.count, len(reps))
    assert all(v['valid'] for v in reps), (camera, [v['reject_reasons'] for v in reps])


@pytest.mark.parametrize("camera", [(90, 0), (90, 35), (75, 10), (-90, 0)])
@pytest.mark.parametrize("fps", [4.0, 6.0])
def test_front_view_still_works_at_the_live_frame_rate(camera, fps):
    pipe, reps = run(clip(camera, fps=fps))
    assert pipe.coach.rc.count == 6 and sum(v['valid'] for v in reps) == 6, \
        (camera, fps, pipe.coach.rc.count, [v['reject_reasons'] for v in reps])


@pytest.mark.parametrize("camera", FRONT)
def test_half_reps_never_accepted_from_a_phone_in_front(camera):
    # the counter does not fire on every half rep from some front angles; whatever it does count must be rejected
    pipe, reps = run(clip(camera, depth=140.0))
    assert not any(v['valid'] for v in reps), (camera, [v['reject_reasons'] for v in reps])
    assert all('too_shallow' in v['reject_reasons'] for v in reps), (camera, [v['reject_reasons'] for v in reps])


@pytest.mark.parametrize("camera", [(90, 35), (90, 50)])
def test_the_veto_is_what_rejects_a_raised_front_view_half_rep(camera):
    """The metric, not just the verdict: every judged half rep stores a straight arm, and without the veto the drop
    passes some of them -- the leak this closes (5 of 6 accepted at (90, 35) before j5)."""
    _, reps = run(clip(camera, depth=140.0))
    assert reps and not any(v['valid'] for v in reps)
    for v in reps:
        m = v['metrics']
        elbows = [e for e in (m['min_elbow_deg_l'], m['min_elbow_deg_r']) if e is not None]
        assert elbows and min(elbows) > D['depth_elbow_max_deg'] + D['depth_elbow_veto_deg'], (camera, m)
    _, lenient = run(clip(camera, depth=140.0), judge_thr={'depth_elbow_veto_deg': 1000})
    assert any(v['valid'] for v in lenient), (camera, [v['metrics']['shoulder_wrist_drop'] for v in lenient])


# ---- the gate and the fold, in isolation ----

def _m(**over):
    base = dict(min_elbow_deg_l=70.0, min_elbow_deg_r=72.0, top_elbow_deg=176.0, max_hip_line_dev_deg=2.0,
                min_knee_deg=175.0, knee_floor_contact=False, shoulder_wrist_drop=0.4, min_keypoint_conf=0.9,
                frame_conf_frac=1.0, persons_in_frame=1, rep_duration_s=2.0, torso_ok=True, side="left",
                classifier_labels=[], shoulder_elbow_gap=-0.1, cadence_rpm=None)
    base.update(over)
    return RepMetrics(**base)


def test_a_straight_arm_cannot_be_passed_by_the_drop():
    deep_drop = dict(shoulder_wrist_drop=0.4)                      # a drop well inside the limit
    assert judge_rep(_m(min_elbow_deg_l=142.0, min_elbow_deg_r=None, **deep_drop), D) == (False, ['too_shallow'])
    # the veto band only: a near-miss elbow is still rescued by the drop, as it was before j5 (foreshortening is real)
    assert judge_rep(_m(min_elbow_deg_l=130.0, min_elbow_deg_r=None, **deep_drop), D) == (True, [])
    assert judge_rep(_m(min_elbow_deg_l=135.0, min_elbow_deg_r=None, **deep_drop), D) == (True, [])
    assert judge_rep(_m(min_elbow_deg_l=135.1, min_elbow_deg_r=None, **deep_drop), D) == (False, ['too_shallow'])
    # a genuinely deep elbow passes whatever the drop says, and the better side is the one that counts
    assert judge_rep(_m(min_elbow_deg_l=142.0, min_elbow_deg_r=90.0, **deep_drop), D) == (True, [])
    assert judge_rep(_m(min_elbow_deg_l=90.0, shoulder_wrist_drop=0.99), D) == (True, [])
    # the veto is a threshold, so an owner can widen or disable it
    assert judge_rep(_m(min_elbow_deg_l=142.0, min_elbow_deg_r=None, **deep_drop),
                     {'depth_elbow_veto_deg': 100}) == (True, [])


def test_the_depth_elbow_takes_the_world_angle_only_when_clearly_straighter():
    assert _straighter(8.0, 142.0, ELBOW_WORLD_GAP_DEG) == 142.0      # front view: a straight arm looks bent
    assert _straighter(80.0, 82.0, ELBOW_WORLD_GAP_DEG) == 80.0       # agreement within noise keeps the image angle
    assert _straighter(80.0, 60.0, ELBOW_WORLD_GAP_DEG) == 80.0       # never deepened by the world angle
    assert _straighter(80.0, None, ELBOW_WORLD_GAP_DEG) == 80.0       # no world landmarks: the image angle alone
    assert _straighter(None, 142.0, ELBOW_WORLD_GAP_DEG) == 142.0
    assert _straighter(None, None, ELBOW_WORLD_GAP_DEG) is None
