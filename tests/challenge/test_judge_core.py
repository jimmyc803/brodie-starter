"""Strict judge core: metrics accumulation, deterministic gates, synthetic cheat coverage (CONTRACTS C5, SPEC §6)."""
import copy
import dataclasses

import numpy as np
import pytest

from challenge.judge import DEFAULT_THRESHOLDS, JUDGE_VERSION, FrameObs, RepMetrics, RepMetricsAccumulator, judge_rep
from challenge.judge.metrics import angle_deg, hip_line_dev_deg
from challenge.judge.synth import BODIES, accumulate_clip, synth_pushups

D = DEFAULT_THRESHOLDS
BODY_NAMES = tuple(BODIES)
SIDES = ("left", "right")
GRID = [(b, s) for b in BODY_NAMES for s in SIDES]


def verdicts(clip, thr=None, **kw):
    return [judge_rep(m, thr if thr is not None else D) for m in accumulate_clip(clip, thr or D, **kw)]


def sag_offset(body):
    return 0.22 * BODIES[body]["torso"]          # ~20 deg hip-line deviation for every body


CHEATS = {
    "knees": (dict(knees_down=True), "knees_down"),
    "half_rep": (dict(depth=125.0), "too_shallow"),
    "pike": (dict(hip_offset=-0.15), "hips_pike"),
    "no_lockout": (dict(lockout=140.0), "no_lockout"),
    "fast": (dict(rep_s=0.6, lead_in_s=0.0), "too_fast"),
    "out_of_frame": (dict(occlude_lower_body=True), "not_in_frame"),
    "two_people": (dict(extra_person=True), "multiple_people"),
}


def _metrics(**over):
    base = dict(min_elbow_deg_l=70.0, min_elbow_deg_r=72.0, top_elbow_deg=176.0, max_hip_line_dev_deg=2.0,
                min_knee_deg=175.0, knee_floor_contact=False, shoulder_wrist_drop=0.4, min_keypoint_conf=0.9,
                frame_conf_frac=1.0, persons_in_frame=1, rep_duration_s=2.0, torso_ok=True, side="left",
                classifier_labels=[], shoulder_elbow_gap=-0.1, cadence_rpm=None)
    base.update(over)
    return RepMetrics(**base)


# ---------------------------------------------------------------- clean acceptance

def test_contract_constants():
    assert JUDGE_VERSION == "j1"
    assert D["knee_min_deg"] == 160 and D["depth_elbow_max_deg"] == 90 and D["lockout_min_deg"] == 160
    assert D["classifier_veto_substrings"] == ["knee", "sag"]


def test_clean_reps_accepted_with_noise_across_bodies_and_sides():
    total = ok = 0
    for body, side in GRID:
        for seed in range(3):
            for valid, reasons in verdicts(synth_pushups(body=body, side=side, noise=0.01, seed=seed, n_reps=5)):
                total += 1
                ok += valid
    assert total == 90
    assert ok / total >= 0.95, f"{ok}/{total} clean reps accepted"


@pytest.mark.parametrize("body,side", GRID)
def test_exact_90_degree_rep_passes(body, side):
    ms = accumulate_clip(synth_pushups(body=body, side=side, depth=90.0, n_reps=3), D)
    for m in ms:
        el = m.min_elbow_deg_l if side == "left" else m.min_elbow_deg_r
        assert el <= 90.0 and m.shoulder_elbow_gap <= D["depth_margin"]
        assert judge_rep(m, D) == (True, [])


@pytest.mark.parametrize("body,side", GRID)
def test_clean_metrics_are_sane(body, side):
    ms = accumulate_clip(synth_pushups(body=body, side=side, n_reps=3), D)
    for m in ms:
        assert m.side == side
        assert m.persons_in_frame == 1 and m.frame_conf_frac == 1.0 and m.torso_ok
        assert m.top_elbow_deg >= 170 and m.min_knee_deg >= 175 and abs(m.max_hip_line_dev_deg) < 1
        assert m.knee_floor_contact is False and m.shoulder_elbow_gap < 0
        assert m.shoulder_wrist_drop > m.shoulder_elbow_gap      # wrist is below the elbow
    assert [m.rep_duration_s for m in ms] == [3.0, 2.0, 2.0]   # first rep includes the 1 s lead-in hold


# ---------------------------------------------------------------- cheats

@pytest.mark.parametrize("cheat", sorted(CHEATS))
@pytest.mark.parametrize("body,side", GRID)
def test_cheat_primary_reason(cheat, body, side):
    kw, reason = CHEATS[cheat]
    vs = verdicts(synth_pushups(body=body, side=side, noise=0.005, seed=7, **kw))
    assert vs
    for valid, reasons in vs:
        assert not valid and reasons[0] == reason, (cheat, reasons)


@pytest.mark.parametrize("body,side", GRID)
def test_sag_primary_reason(body, side):
    vs = verdicts(synth_pushups(body=body, side=side, hip_offset=sag_offset(body)))
    assert all(not v and r[0] == "hips_sag" for v, r in vs), vs
    # with jitter a sagging rep is always rejected for sag; hips at the floor may additionally put the knees within the
    # floor margin (knees_down outranks hips_sag in C5 order), which is still a correct rejection
    for seed in range(3):
        for v, r in verdicts(synth_pushups(body=body, side=side, hip_offset=sag_offset(body), noise=0.01, seed=seed)):
            assert not v and "hips_sag" in r


@pytest.mark.parametrize("cheat", sorted(CHEATS) + ["sag"])
def test_zero_cheat_reps_accepted_at_high_noise(cheat):
    for body, side in GRID:
        for seed in range(2):
            kw = dict(hip_offset=sag_offset(body)) if cheat == "sag" else CHEATS[cheat][0]
            vs = verdicts(synth_pushups(body=body, side=side, noise=0.01, seed=seed, **kw))
            assert not any(v for v, _ in vs), (cheat, body, side, seed)


def test_fast_reps_after_long_setup_still_flagged_from_second_rep():
    vs = verdicts(synth_pushups(rep_s=0.6, lead_in_s=1.0))
    assert vs[0] == (True, [])                      # first window includes the 1 s plank hold: 1.6 s
    assert all(r[0] == "too_fast" for _, r in vs[1:])


def test_sustained_cadence_flags_too_fast():
    vs = verdicts(synth_pushups(rep_s=0.9, n_reps=7, lead_in_s=0.0))
    # 0.9 s >= min_rep_s, but once 5 reps exist the rolling cadence is 66.7 rpm > 60
    assert [v for v, _ in vs[:4]] == [True] * 4
    assert all(r == ["too_fast"] for _, r in vs[4:])
    ms = accumulate_clip(synth_pushups(rep_s=0.9, n_reps=7, lead_in_s=0.0), D)
    assert ms[3].cadence_rpm is None and ms[4].cadence_rpm == pytest.approx(66.6667, abs=1e-3)


def test_knee_floor_contact_alone_rejects():
    assert judge_rep(_metrics(knee_floor_contact=True), D) == (False, ["knees_down"])
    assert judge_rep(_metrics(min_knee_deg=159.9), D) == (False, ["knees_down"])
    assert judge_rep(_metrics(min_knee_deg=160.0), D) == (True, [])


def test_knee_pushup_metrics():
    m = accumulate_clip(synth_pushups(knees_down=True), D)[1]
    assert m.knee_floor_contact is True and m.min_knee_deg < 160


# ---------------------------------------------------------------- gates (pure)

def test_reason_priority_order_full():
    m = _metrics(persons_in_frame=2, frame_conf_frac=0.5, min_knee_deg=120.0, max_hip_line_dev_deg=30.0,
                 min_elbow_deg_l=120.0, top_elbow_deg=130.0, rep_duration_s=0.3, torso_ok=False,
                 classifier_labels=["pushups - shallow", "Pushups - Knee Push-Up", "pushups - good"])
    valid, reasons = judge_rep(m, D)
    assert not valid
    assert reasons == ["multiple_people", "not_in_frame", "knees_down", "hips_sag", "too_shallow", "no_lockout",
                       "too_fast", "not_horizontal", "classifier:pushups - shallow",
                       "classifier:Pushups - Knee Push-Up"]
    assert judge_rep(_metrics(max_hip_line_dev_deg=-15.1), D) == (False, ["hips_pike"])
    assert judge_rep(_metrics(max_hip_line_dev_deg=15.0), D) == (True, [])
    assert judge_rep(_metrics(max_hip_line_dev_deg=-15.0), D) == (True, [])


def test_depth_gate_uses_visible_side_and_shoulder_elbow_gap():
    assert judge_rep(_metrics(min_elbow_deg_l=90.0), D) == (True, [])
    assert judge_rep(_metrics(min_elbow_deg_l=90.5), D) == (False, ["too_shallow"])
    assert judge_rep(_metrics(side="right", min_elbow_deg_l=150.0, min_elbow_deg_r=80.0), D) == (True, [])
    assert judge_rep(_metrics(side="right", min_elbow_deg_l=60.0, min_elbow_deg_r=95.0), D) == (False, ["too_shallow"])
    assert judge_rep(_metrics(shoulder_elbow_gap=0.05), D) == (True, [])
    assert judge_rep(_metrics(shoulder_elbow_gap=0.06), D) == (False, ["too_shallow"])
    # shoulder_wrist_drop is informational only
    assert judge_rep(_metrics(shoulder_wrist_drop=5.0), D) == (True, [])


def test_lockout_tempo_torso_gates():
    assert judge_rep(_metrics(top_elbow_deg=159.0), D) == (False, ["no_lockout"])
    assert judge_rep(_metrics(top_elbow_deg=160.0), D) == (True, [])
    assert judge_rep(_metrics(rep_duration_s=0.79), D) == (False, ["too_fast"])
    assert judge_rep(_metrics(rep_duration_s=0.8, cadence_rpm=60.0), D) == (True, [])
    assert judge_rep(_metrics(cadence_rpm=61.0), D) == (False, ["too_fast"])
    assert judge_rep(_metrics(torso_ok=False), D) == (False, ["not_horizontal"])


def test_frame_and_person_gates():
    assert judge_rep(_metrics(frame_conf_frac=0.89), D) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(frame_conf_frac=0.9), D) == (True, [])
    assert judge_rep(_metrics(persons_in_frame=0), D) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(persons_in_frame=3), D) == (False, ["multiple_people"])
    # unmeasurable geometry is reported as not_in_frame, never silently passed
    assert judge_rep(_metrics(min_knee_deg=None), D) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(top_elbow_deg=float("nan")), D) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(side="none"), D) == (False, ["not_in_frame"])


def test_classifier_veto_rules():
    assert judge_rep(_metrics(classifier_labels=["pushups - good form"]), D) == (True, [])
    assert judge_rep(_metrics(classifier_labels=["PUSHUPS - INSUFFICIENT"]), D) == (
        False, ["classifier:PUSHUPS - INSUFFICIENT"])
    assert judge_rep(_metrics(classifier_labels=["pushups - hip sagging", "pushups - hip sagging"]), D) == (
        False, ["classifier:pushups - hip sagging"])
    assert judge_rep(_metrics(classifier_labels=["pushups - elevated hips"]), D)[1] == [
        "classifier:pushups - elevated hips"]


def test_thresholds_partial_override_and_no_mutation():
    thr = {"knee_min_deg": 170}
    before = copy.deepcopy(thr)
    m = _metrics(min_knee_deg=165.0)
    m_before = dataclasses.asdict(m)
    assert judge_rep(m, thr) == (False, ["knees_down"])
    assert judge_rep(m, {}) == (True, [])
    assert thr == before and dataclasses.asdict(m) == m_before
    assert judge_rep(m, thr) == judge_rep(m, thr)


# ---------------------------------------------------------------- accumulator mechanics

def test_deterministic_metrics():
    a = accumulate_clip(synth_pushups(noise=0.01, seed=3), D)
    b = accumulate_clip(synth_pushups(noise=0.01, seed=3), D)
    assert [dataclasses.asdict(x) for x in a] == [dataclasses.asdict(x) for x in b]


def test_late_fire_carries_frames_to_next_window():
    clip = synth_pushups(noise=0.005, seed=1)
    a = accumulate_clip(clip, D)
    b = accumulate_clip(clip, D, fire_lag_s=0.3)
    assert [dataclasses.asdict(x) for x in a] == [dataclasses.asdict(x) for x in b]


def test_aspect_correction_makes_angles_aspect_invariant():
    ref = accumulate_clip(synth_pushups(aspect=16 / 9), D)[1]
    other = accumulate_clip(synth_pushups(aspect=4 / 3), D)[1]
    for k in ("min_elbow_deg_l", "top_elbow_deg", "min_knee_deg", "max_hip_line_dev_deg"):
        assert getattr(other, k) == pytest.approx(getattr(ref, k), abs=0.05)
    # the same normalised landmarks read with a wrong aspect give different angles (correction is not a no-op)
    clip = synth_pushups(aspect=16 / 9)
    for f in clip.frames:
        f.aspect = 1.0
    wrong = accumulate_clip(clip, D)[1]
    assert abs(wrong.min_elbow_deg_l - ref.min_elbow_deg_l) > 3


def test_geometry_helpers_y_down():
    assert angle_deg(np.array([0.0, 0.0]), np.array([1.0, 0.0]), np.array([1.0, 1.0])) == pytest.approx(90.0)
    s, a = np.array([0.0, 0.5]), np.array([1.0, 0.5])
    assert hip_line_dev_deg(s, np.array([0.5, 0.6]), a) > 0          # hip lower in the image = sag
    assert hip_line_dev_deg(s, np.array([0.5, 0.4]), a) < 0          # hip higher = pike
    assert hip_line_dev_deg(a, np.array([0.5, 0.6]), s) > 0          # facing the other way: same sign
    assert hip_line_dev_deg(s, np.array([0.5, 0.5]), a) == pytest.approx(0.0, abs=1e-9)


def test_single_frame_second_person_glitch_ignored_but_sustained_flagged():
    clip = synth_pushups(n_reps=1)
    clip.frames[12].persons = 2
    assert verdicts(clip)[0] == (True, [])
    clip.frames[13].persons = 2
    assert verdicts(clip)[0] == (False, ["multiple_people"])


def test_empty_window_and_reset():
    acc = RepMetricsAccumulator(D)
    m = acc.close_rep(5.0, [], None)
    assert judge_rep(m, D)[1][0] == "not_in_frame" and m.side == "none" and m.frame_conf_frac == 0.0
    clip = synth_pushups(n_reps=2)
    for f in clip.frames:
        acc.add_frame(f)
    acc.reset()
    assert acc.close_rep(clip.fire_times[0], [], None).frame_conf_frac == 0.0


def test_setup_before_first_rep_outside_window_is_ignored():
    clip = synth_pushups(lead_in_s=4.0, n_reps=2)
    junk = [FrameObs(t=-10.0 + i / 10, img=None, world=None, persons=0) for i in range(100)]
    acc = RepMetricsAccumulator(D, max_window_s=6.0)
    for f in junk + clip.frames:
        acc.add_frame(f)
    ms = []
    for tf in clip.fire_times:
        ms.append(acc.close_rep(tf, [], None))
    assert ms[0].rep_duration_s == pytest.approx(16.0)
    assert [judge_rep(m, D) for m in ms] == [(True, []), (True, [])]


def test_torso_flag_passthrough_and_labels():
    clip = synth_pushups(n_reps=1)
    m = accumulate_clip(clip, D, torso_ok=False, labels=["pushups - shallow"])[0]
    assert judge_rep(m, D) == (False, ["not_horizontal", "classifier:pushups - shallow"])


def test_low_visibility_frames_reduce_frame_conf_frac():
    clip = synth_pushups(n_reps=1)
    for f in clip.frames[5:12]:
        f.img[[11, 12], 3] = 0.1                      # shoulders lost for 7 of ~31 frames
    m = accumulate_clip(clip, D)[0]
    assert m.frame_conf_frac < 0.9 and m.min_keypoint_conf < 0.5
    assert judge_rep(m, D)[1][0] == "not_in_frame"


def test_out_of_image_landmark_counts_as_unconfident():
    clip = synth_pushups(n_reps=1)
    for f in clip.frames:
        f.img[[27, 28], 0] = 1.05                     # ankles cut off at the frame edge, visibility still high
    m = accumulate_clip(clip, D)[0]
    assert m.frame_conf_frac == 0.0 and judge_rep(m, D)[1][0] == "not_in_frame"
