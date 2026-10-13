"""j4 launch leniency (docs/challenge/CALIBRATION.md "j4"): rep counting at the live 4-10 fps, off-angle cameras, the
world-landmark readings of the hip line / knee / lockout, the bent-leg hip skip, and the cue choice."""
import dataclasses

import numpy as np
import pytest

from challenge.judge import DEFAULT_THRESHOLDS, RepMetrics, judge_rep
from challenge.judge.gates import merged_thresholds
from challenge.judge.metrics import _agree, _straighter, world_hip_dev_deg
from challenge.judge.synth import accumulate_clip, synth_pushups
from facetime.pipeline import FramePipeline

D = DEFAULT_THRESHOLDS


def run(frames, judge_thr=None, **kw):
    """Feed synth frames through FramePipeline.process_landmarks; returns (pipe, [verdict fields])."""
    pipe = FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none', judge=True, judge_thr=judge_thr,
                         **kw)
    out = []
    for f in frames:
        r = pipe.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=f.persons,
                                   t_ms=round(f.t * 1000), aspect=f.aspect)
        out += list(r.get('judge', {}).values())
    return pipe, out


# ---- counting at the live frame rate (EC2 processes 4-8 fps; the counter's clock is FramePipeline.FPS = 10) ----

@pytest.mark.parametrize("fps", [4.0, 6.0, 10.0])
@pytest.mark.parametrize("rep_s", [0.9, 1.5, 3.0])
def test_every_rep_counted_and_accepted_at_low_fps(fps, rep_s):
    # before j4 a 0.9 s rep at 4 fps counted 1 of 8: the counter's 10 fps clock saw each rep as 0.36 s
    clip = synth_pushups(n_reps=8, rep_s=rep_s, lead_in_s=2.0, fps=fps, noise=0.004, seed=3)
    pipe, reps = run(clip.frames)
    assert pipe.coach.rc.count == 8 and len(reps) == 8, (fps, rep_s, pipe.coach.rc.count)
    assert all(v['valid'] for v in reps), [v['reject_reasons'] for v in reps]
    assert (pipe.n_interp > 0) == (fps < 10.0)


@pytest.mark.parametrize("fps", [4.0, 6.0, 10.0])
def test_shallow_and_knee_reps_still_rejected_at_low_fps(fps):
    pipe, reps = run(synth_pushups(n_reps=5, lead_in_s=2.0, fps=fps, depth=140.0, seed=2).frames)
    assert pipe.coach.rc.count == 5 and all(not v['valid'] and 'too_shallow' in v['reject_reasons'] for v in reps)
    pipe, reps = run(synth_pushups(n_reps=5, lead_in_s=2.0, fps=fps, knees_down=True, seed=2).frames,
                     judge_thr={'knee_min_deg': 150})
    assert pipe.coach.rc.count == 5 and all(not v['valid'] and v['reject_reasons'][0] == 'knees_down' for v in reps)


def test_irregular_frame_gaps_counted():
    # a 10 fps clip with ~half the frames dropped at random (live jitter: 3-10 fps in one set)
    clip = synth_pushups(n_reps=8, rep_s=1.1, lead_in_s=2.0, noise=0.004, seed=5)
    keep = np.random.default_rng(7).random(len(clip.frames)) < 0.5
    pipe, reps = run([f for f, k in zip(clip.frames, keep) if k])
    assert pipe.coach.rc.count == 8 and sum(v['valid'] for v in reps) == 8


def test_resampling_skips_long_gaps_and_can_be_disabled():
    clip = synth_pushups(n_reps=3, lead_in_s=2.0, fps=4.0, seed=1)
    frames = [dataclasses.replace(f, t=f.t + (5.0 if f.t >= 1.0 else 0.0)) for f in clip.frames]   # a 5.25 s stall
    pipe, _ = run(frames[:4])
    n0 = pipe.n_interp
    assert 3 * 1 <= n0 <= 3 * 2                        # 3 gaps of 0.25 s -> 10 fps ticks: 1-2 invented frames each
    f = frames[4]
    assert f.t - frames[3].t > 5.0
    pipe.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=1, t_ms=round(f.t * 1000),
                           aspect=f.aspect)
    assert pipe.n_interp == n0                         # nothing invented across a gap longer than RESAMPLE_MAX_GAP_S
    pipe, _ = run(clip.frames, resample=False)
    assert pipe.n_interp == 0


# ---- off-angle cameras (most callers will not prop the phone at floor level, side on) ----

@pytest.mark.parametrize("camera", [(0, 35), (0, 50), (45, 20), (45, 50), (90, 35), (90, 50), (30, 0)])
@pytest.mark.parametrize("fps", [4.0, 10.0])
def test_clean_reps_accepted_from_high_diagonal_and_front_cameras(camera, fps):
    clip = synth_pushups(n_reps=6, rep_s=1.2, lead_in_s=2.0, noise=0.004, seed=1, camera=camera, fps=fps)
    pipe, reps = run(clip.frames)
    assert pipe.coach.rc.count == 6 and sum(v['valid'] for v in reps) == 6, [v['reject_reasons'] for v in reps]


@pytest.mark.parametrize("camera", [None, (0, 20), (0, 35), (45, 0), (45, 20)])
def test_half_reps_rejected_from_side_and_raised_cameras(camera):
    clip = synth_pushups(n_reps=6, rep_s=1.2, lead_in_s=2.0, noise=0.004, seed=1, depth=140.0, camera=camera)
    pipe, reps = run(clip.frames)
    assert pipe.coach.rc.count == 6 and not any(v['valid'] for v in reps), [v['reject_reasons'] for v in reps]


@pytest.mark.parametrize("camera", [None, (0, 35), (45, 20)])
def test_pike_rejected_from_side_and_raised_cameras(camera):
    clip = synth_pushups(n_reps=4, rep_s=1.2, lead_in_s=2.0, seed=1, hip_offset=-0.3, camera=camera)
    pipe, reps = run(clip.frames)
    assert reps and all(v['reject_reasons'] == ['hips_pike'] for v in reps), [v['reject_reasons'] for v in reps]


def test_synth_camera_validation_and_world_is_view_independent():
    with pytest.raises(ValueError):
        synth_pushups(camera=(120, 0))
    with pytest.raises(ValueError):
        synth_pushups(camera=(0, 85))
    side = synth_pushups(n_reps=1, seed=0, noise=0.0)
    for cam in [(0, 0), (45, 35), (90, 50)]:
        c = synth_pushups(n_reps=1, seed=0, noise=0.0, camera=cam)
        for f0, f1 in zip(side.frames[::5], c.frames[::5]):
            d0 = np.linalg.norm(f0.world[11] - f0.world[15])       # shoulder-wrist distance: rigid, so view-invariant
            d1 = np.linalg.norm(f1.world[11] - f1.world[15])
            assert abs(d0 - d1) < 1e-6
            assert np.all((f1.img[:, :2] > -0.1) & (f1.img[:, :2] < 1.1))


# ---- world-landmark readings ----

def test_world_hip_dev_sign_and_agreement():
    s, a = np.array([0.0, 0.0, 0.0]), np.array([1.6, 0.0, 0.0])
    assert world_hip_dev_deg(s, np.array([0.8, 0.1, 0.0]), a) > 10           # y down: hip below the line -> sag (+)
    assert world_hip_dev_deg(s, np.array([0.8, -0.1, 0.3]), a) < -10         # above -> pike (-), any depth
    assert world_hip_dev_deg(s, s, a) is None
    assert _agree(25.0, None) == 25.0                  # no world landmarks: the image alone
    assert _agree(25.0, 10.0) == 10.0 and _agree(-25.0, -40.0) == -25.0
    assert _agree(25.0, -5.0) == 0.0                   # disagree: the image bend is a view artefact
    assert _agree(float('nan'), 5.0) is None


def test_knee_uses_world_only_when_clearly_straighter():
    assert _straighter(120.0, 170.0) == 170.0          # foreshortened straight leg
    assert _straighter(141.0, 150.0) == 141.0          # within KNEE_WORLD_GAP_DEG: pose noise, image kept
    assert _straighter(141.0, 120.0) == 141.0
    assert _straighter(float('nan'), 160.0) == 160.0 and _straighter(150.0, None) == 150.0


def _shift_hips_image_only(clip, dy):
    for f in clip.frames:
        f.img[[23, 24], 1] += dy                          # hips lower in the image only; world stays a straight plank
        f.img[[25, 26], 1] += dy / 2


def test_image_only_hip_bend_is_a_view_artefact_but_a_real_sag_is_not():
    thr = merged_thresholds({'hip_line_max_dev_deg': 17.5})
    clip = synth_pushups(n_reps=2, seed=1)
    _shift_hips_image_only(clip, 0.12)
    ms = accumulate_clip(clip, thr)
    assert all(judge_rep(m, thr)[0] for m in ms), [judge_rep(m, thr) for m in ms]
    ms = accumulate_clip(synth_pushups(n_reps=2, seed=1, hip_offset=0.2), thr)   # sag in the body: image and world
    assert ms and all('hips_sag' in judge_rep(m, thr)[1] for m in ms)


def test_lockout_uses_the_straighter_of_image_and_world_top():
    clip = synth_pushups(n_reps=2, seed=1, lockout=176.0)
    for f in clip.frames:                               # foreshortened forearm in the image only: top reads ~120 deg
        for e, w in ((13, 15), (14, 16)):
            f.img[w, :2] = f.img[e, :2] + (f.img[w, :2] - f.img[e, :2]) * np.array([0.0, 1.0])
    for m in accumulate_clip(clip, D):
        assert m.top_elbow_deg is not None and m.top_elbow_deg >= D['lockout_min_deg']
    for m in accumulate_clip(synth_pushups(n_reps=2, seed=1, lockout=110.0), D):   # bent at the top in the body
        assert 'no_lockout' in judge_rep(m, D)[1]


# ---- gates ----

def _m(**over):
    base = dict(min_elbow_deg_l=70.0, min_elbow_deg_r=72.0, top_elbow_deg=176.0, max_hip_line_dev_deg=2.0,
                min_knee_deg=175.0, knee_floor_contact=False, shoulder_wrist_drop=0.4, min_keypoint_conf=0.9,
                frame_conf_frac=1.0, persons_in_frame=1, rep_duration_s=2.0, torso_ok=True, side="left",
                classifier_labels=[], shoulder_elbow_gap=-0.1, cadence_rpm=None)
    base.update(over)
    return RepMetrics(**base)


def test_hip_gates_skipped_with_clearly_bent_legs():
    assert judge_rep(_m(max_hip_line_dev_deg=-90.0, min_knee_deg=175.0), D) == (False, ['hips_pike'])
    assert judge_rep(_m(max_hip_line_dev_deg=-90.0, min_knee_deg=119.0), D) == (True, [])
    assert judge_rep(_m(max_hip_line_dev_deg=-90.0, min_knee_deg=120.0), D) == (False, ['hips_pike'])
    assert judge_rep(_m(max_hip_line_dev_deg=45.0, min_knee_deg=None), D) == (False, ['hips_sag'])
    # a knee push-up is still knees_down (contact + bent knee), the hip skip does not let it through
    assert judge_rep(_m(max_hip_line_dev_deg=-50.0, min_knee_deg=100.0, knee_floor_contact=True), D) == \
        (False, ['knees_down'])
    assert judge_rep(_m(max_hip_line_dev_deg=-50.0, min_knee_deg=110.0),
                     {**D, 'hip_knee_min_deg': 100}) == (False, ['hips_pike'])


def test_j4_leniency_bounds():
    assert judge_rep(_m(top_elbow_deg=131.0), D)[0] and not judge_rep(_m(top_elbow_deg=129.0), D)[0]
    assert judge_rep(_m(min_knee_deg=146.0, knee_floor_contact=True), D)[0]
    assert judge_rep(_m(min_knee_deg=144.0, knee_floor_contact=True), D) == (False, ['knees_down'])
    shallow = dict(min_elbow_deg_l=130.0, min_elbow_deg_r=135.0, shoulder_wrist_drop=0.9)
    assert judge_rep(_m(**shallow), D) == (False, ['too_shallow'])


@pytest.mark.parametrize("fps", [4.0, 6.0, 10.0])
def test_perception_rep_events_keep_turning_time_at_low_fps(fps):
    # resampled counter ticks have no frame of their own: Perception spreads their times so turning_t / lag_s stay set
    from facetime.perception import Config, Perception
    pipe = FramePipeline(None, exercise='pushups', pose_variant=None, trigger='none', judge=True)
    p = Perception(Config(exercise='pushups', announce=False), pipe=pipe, clip_s={}, t0=0)
    emitted = []
    p.on_event(emitted.append)
    clip = synth_pushups(n_reps=5, rep_s=1.2, lead_in_s=2.0, fps=fps, noise=0.004, seed=3)
    for f in clip.frames:
        p.process_landmarks(f.img.astype(np.float32), f.world.astype(np.float32), persons=f.persons, t_recv=f.t,
                            t_ms=round(f.t * 1000), aspect=f.aspect)
    reps = [e for e in emitted if e['type'] == 'rep']
    assert [e['n'] for e in reps] == [1, 2, 3, 4, 5] and all(e['valid'] for e in reps)
    assert all(e['turning_t'] is not None and 0 < e['lag_s'] < 2.0 for e in reps), reps
    p.close()
