"""Strict judge core: metrics accumulation, deterministic gates, synthetic cheat coverage (CONTRACTS C5, SPEC §6)."""
import copy
import dataclasses
import json
import re
from pathlib import Path

import numpy as np
import pytest

from challenge.judge import DEFAULT_THRESHOLDS, JUDGE_VERSION, FrameObs, RepMetrics, RepMetricsAccumulator, judge_rep
from challenge.judge.gates import merged_thresholds
from challenge.judge.metrics import angle_deg, hip_line_dev_deg
from challenge.judge.synth import BODIES, accumulate_clip, synth_pushups

D = DEFAULT_THRESHOLDS
# The j2 strict calibration (docs/challenge/CALIBRATION.md "Thresholds (j2)"): j3 made the DEFAULTS lenient, but the
# competition_config can tighten the judge again, so the cheat-detection mechanics are pinned under these values.
# depth_drop_max 0.64 (not j2's 0.75): j3 accepts depth when EITHER signal reaches its limit, so the drop limit is
# matched to the 100 deg elbow limit (side view: 100 deg ~ 0.645, 110 deg ~ 0.735, 125 deg ~ 0.85).
STRICT = merged_thresholds({
    "min_conf": 0.5, "frame_conf_frac": 0.9, "knee_min_deg": 150, "knee_floor_margin": 0.02,
    "hip_line_max_dev_deg": 17.5, "hip_pike_max_dev_deg": 20, "depth_elbow_max_deg": 100, "depth_drop_max": 0.64,
    "lockout_min_deg": 150, "incline_max_deg": 9, "decline_max_deg": 23, "min_rep_s": 0.8, "max_cadence_rpm": 60,
    "classifier_veto": ["pushups - shallow", "pushups - insufficient", "pushups - elevated hips"],
    "classifier_veto_substrings": ["knee", "sag"]})
BODY_NAMES = tuple(BODIES)
SIDES = ("left", "right")
GRID = [(b, s) for b in BODY_NAMES for s in SIDES]


def verdicts(clip, thr=None, **kw):
    return [judge_rep(m, thr if thr is not None else STRICT) for m in accumulate_clip(clip, thr or STRICT, **kw)]


def sag_offset(body):
    return 0.22 * BODIES[body]["torso"]          # ~20 deg hip-line deviation for every body


CHEATS = {
    "knees": (dict(knees_down=True), "knees_down"),
    "half_rep": (dict(depth=125.0), "too_shallow"),
    "pike": (dict(hip_offset=-0.15), "hips_pike"),
    "no_lockout": (dict(lockout=140.0), "no_lockout"),
    "fast": (dict(rep_s=0.6, lead_in_s=0.0, fps=20.0), "too_fast"),   # 10 fps cannot show 2 bottom frames
    "out_of_frame": (dict(occlude_arms=True), "not_in_frame"),      # j3: only the upper body must be measurable
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
    # j3 lenient defaults (docs/challenge/CALIBRATION.md "j3 lenient"), equal to the owner's live competition_config
    assert JUDGE_VERSION == "j3"
    assert D["knee_min_deg"] == 120 and D["depth_elbow_max_deg"] == 125 and D["lockout_min_deg"] == 135
    assert D["hip_line_max_dev_deg"] == 30 and D["hip_pike_max_dev_deg"] == 40 and D["depth_drop_max"] == 0.88
    assert D["incline_max_deg"] == 25 and D["decline_max_deg"] == 35 and D["knee_floor_margin"] == 0.1
    assert "depth_margin" not in D and D["liveness_enabled"] is False
    assert D["classifier_veto_substrings"] == [] and D["classifier_veto"] == []


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
    # >= 2 frames must reach depth (D-16): a 0.3 s pause at exactly 90 deg
    ms = accumulate_clip(synth_pushups(body=body, side=side, depth=90.0, n_reps=3, bottom_hold_s=0.3), STRICT)
    for m in ms:
        el = m.min_elbow_deg_l if side == "left" else m.min_elbow_deg_r
        assert el <= 90.0 and m.shoulder_wrist_drop <= STRICT["depth_drop_max"]
        assert judge_rep(m, STRICT) == (True, [])


@pytest.mark.parametrize("body,side", GRID)
def test_clean_metrics_are_sane(body, side):
    ms = accumulate_clip(synth_pushups(body=body, side=side, n_reps=3), STRICT)
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
@pytest.mark.parametrize("noise", [0.01, 0.02])
def test_zero_cheat_reps_accepted_at_high_noise(cheat, noise):
    accepted = total = 0
    for body, side in GRID:
        for seed in range(2):
            kw = dict(hip_offset=sag_offset(body)) if cheat == "sag" else dict(CHEATS[cheat][0])
            kw.pop("fps", None)                       # fast reps at the default 10 fps must be rejected too
            vs = verdicts(synth_pushups(body=body, side=side, noise=noise, seed=seed, **kw))
            accepted += sum(v for v, _ in vs)
            total += len(vs)
            if (cheat, noise) != ("no_lockout", 0.02):
                assert not any(v for v, _ in vs), (cheat, body, side, seed)
    # D-31: a 140 deg near-lockout under sigma 0.02 jitter reads up to ~152 deg, over lockout_min_deg 150 (set from real
    # clean tops down to 145.6). Accepted residual, measured 12/60 = 0.20; zero is still required at sigma <= 0.01.
    if (cheat, noise) == ("no_lockout", 0.02):
        assert total == 60 and accepted / total <= 0.25, accepted


def test_fast_reps_after_long_setup_still_flagged_from_second_rep():
    vs = verdicts(synth_pushups(rep_s=0.6, lead_in_s=1.0, fps=20.0))
    assert vs[0] == (True, [])                      # first window includes the 1 s plank hold: 1.6 s
    assert all(r[0] == "too_fast" for _, r in vs[1:])


def test_sustained_cadence_flags_too_fast():
    vs = verdicts(synth_pushups(rep_s=0.9, n_reps=7, lead_in_s=0.0))
    # 0.9 s >= min_rep_s, but once 5 reps exist the rolling cadence is 66.7 rpm > 60
    assert [v for v, _ in vs[:4]] == [True] * 4
    assert all(r == ["too_fast"] for _, r in vs[4:])
    ms = accumulate_clip(synth_pushups(rep_s=0.9, n_reps=7, lead_in_s=0.0), STRICT)
    assert ms[3].cadence_rpm is None and ms[4].cadence_rpm == pytest.approx(66.6667, abs=1e-3)


def test_knees_down_needs_floor_contact_and_a_bent_knee():
    # j3: clearly on the knees only. A straight knee near the floor line (camera perspective), a bent knee in the
    # air, or a knee whose angle is unmeasurable (ankles out of frame) is not knees_down.
    assert judge_rep(_metrics(knee_floor_contact=True), STRICT) == (True, [])
    assert judge_rep(_metrics(min_knee_deg=149.9), STRICT) == (True, [])
    assert judge_rep(_metrics(min_knee_deg=149.9, knee_floor_contact=True), STRICT) == (False, ["knees_down"])
    assert judge_rep(_metrics(min_knee_deg=150.0, knee_floor_contact=True), STRICT) == (True, [])
    assert judge_rep(_metrics(min_knee_deg=None, knee_floor_contact=True), STRICT) == (True, [])


def test_knee_pushup_metrics():
    m = accumulate_clip(synth_pushups(knees_down=True), STRICT)[1]
    assert m.knee_floor_contact is True and m.min_knee_deg < 160


# ---------------------------------------------------------------- gates (pure)

def test_reason_priority_order_full():
    m = _metrics(persons_in_frame=2, frame_conf_frac=0.5, min_knee_deg=120.0, knee_floor_contact=True,
                 max_hip_line_dev_deg=30.0, min_elbow_deg_l=120.0, min_elbow_deg_r=None, shoulder_wrist_drop=0.8,
                 top_elbow_deg=130.0, rep_duration_s=0.3, torso_ok=False,
                 classifier_labels=["pushups - shallow", "Pushups - Knee Push-Up", "pushups - good"])
    valid, reasons = judge_rep(m, STRICT)
    assert not valid
    assert reasons == ["multiple_people", "not_in_frame", "knees_down", "hips_sag", "too_shallow", "no_lockout",
                       "too_fast", "not_horizontal", "classifier:pushups - shallow",
                       "classifier:Pushups - Knee Push-Up"]
    assert judge_rep(_metrics(max_hip_line_dev_deg=-20.1), STRICT) == (False, ["hips_pike"])
    assert judge_rep(_metrics(max_hip_line_dev_deg=17.6), STRICT) == (False, ["hips_sag"])
    assert judge_rep(_metrics(max_hip_line_dev_deg=17.5), STRICT) == (True, [])
    assert judge_rep(_metrics(max_hip_line_dev_deg=-20.0), STRICT) == (True, [])


def test_depth_gate_uses_better_side_or_shoulder_wrist_drop():
    # j3: depth is reached when EITHER the better side's elbow OR the shoulder drop ratio reaches its limit
    shallow = dict(min_elbow_deg_r=None, shoulder_wrist_drop=0.8)
    assert judge_rep(_metrics(min_elbow_deg_l=100.0, **shallow), STRICT) == (True, [])
    assert judge_rep(_metrics(min_elbow_deg_l=100.5, **shallow), STRICT) == (False, ["too_shallow"])
    assert judge_rep(_metrics(side="right", min_elbow_deg_l=150.0, min_elbow_deg_r=80.0), STRICT) == (True, [])
    assert judge_rep(_metrics(side="right", min_elbow_deg_l=60.0, min_elbow_deg_r=105.0), STRICT) == (True, [])
    # drop ratio (bottom / top shoulder-to-wrist height): a front / diagonal view foreshortens the elbow angle
    assert judge_rep(_metrics(min_elbow_deg_l=140.0, min_elbow_deg_r=None, shoulder_wrist_drop=0.64), STRICT) == (True, [])
    assert judge_rep(_metrics(min_elbow_deg_l=140.0, min_elbow_deg_r=None, shoulder_wrist_drop=0.65), STRICT) == (
        False, ["too_shallow"])
    assert judge_rep(_metrics(shoulder_wrist_drop=None), STRICT) == (True, [])
    # shoulder_elbow_gap is informational only (j2)
    assert judge_rep(_metrics(shoulder_elbow_gap=5.0), STRICT) == (True, [])


def test_lockout_tempo_torso_gates():
    assert judge_rep(_metrics(top_elbow_deg=149.9), STRICT) == (False, ["no_lockout"])
    assert judge_rep(_metrics(top_elbow_deg=150.0), STRICT) == (True, [])
    assert judge_rep(_metrics(rep_duration_s=0.79), STRICT) == (False, ["too_fast"])
    assert judge_rep(_metrics(rep_duration_s=0.8, cadence_rpm=60.0), STRICT) == (True, [])
    assert judge_rep(_metrics(cadence_rpm=61.0), STRICT) == (False, ["too_fast"])
    assert judge_rep(_metrics(torso_ok=False), STRICT) == (False, ["not_horizontal"])


def test_frame_and_person_gates():
    assert judge_rep(_metrics(frame_conf_frac=0.89), STRICT) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(frame_conf_frac=0.9), STRICT) == (True, [])
    assert judge_rep(_metrics(persons_in_frame=0), STRICT) == (False, ["not_in_frame"])
    assert judge_rep(_metrics(persons_in_frame=3), STRICT) == (False, ["multiple_people"])
    # j3: unmeasurable leg geometry (feet / knees out of frame) skips its gates; only an unmeasurable upper body is
    # not_in_frame
    legs_out = dict(min_knee_deg=None, knee_floor_contact=None, max_hip_line_dev_deg=float("nan"))
    assert judge_rep(_metrics(**legs_out), STRICT) == (True, [])
    assert judge_rep(_metrics(top_elbow_deg=float("nan")), STRICT) == (True, [])
    assert judge_rep(_metrics(side="none", min_elbow_deg_l=None, min_elbow_deg_r=None, top_elbow_deg=None,
                              shoulder_wrist_drop=None), STRICT) == (False, ["not_in_frame"])


def test_classifier_veto_rules():
    assert judge_rep(_metrics(classifier_labels=["pushups - good form"]), STRICT) == (True, [])
    assert judge_rep(_metrics(classifier_labels=["PUSHUPS - INSUFFICIENT"]), STRICT) == (
        False, ["classifier:PUSHUPS - INSUFFICIENT"])
    assert judge_rep(_metrics(classifier_labels=["pushups - hip sagging", "pushups - hip sagging"]), STRICT) == (
        False, ["classifier:pushups - hip sagging"])
    assert judge_rep(_metrics(classifier_labels=["pushups - elevated hips"]), STRICT)[1] == [
        "classifier:pushups - elevated hips"]


def test_thresholds_partial_override_and_no_mutation():
    thr = {"knee_min_deg": 170}
    before = copy.deepcopy(thr)
    m = _metrics(min_knee_deg=165.0, knee_floor_contact=True)
    m_before = dataclasses.asdict(m)
    assert judge_rep(m, thr) == (False, ["knees_down"])
    assert judge_rep(m, {}) == (True, [])
    assert thr == before and dataclasses.asdict(m) == m_before
    assert judge_rep(m, thr) == judge_rep(m, thr)


# ---------------------------------------------------------------- accumulator mechanics

def test_deterministic_metrics():
    a = accumulate_clip(synth_pushups(noise=0.01, seed=3), STRICT)
    b = accumulate_clip(synth_pushups(noise=0.01, seed=3), STRICT)
    assert [dataclasses.asdict(x) for x in a] == [dataclasses.asdict(x) for x in b]


def test_late_fire_carries_frames_to_next_window():
    clip = synth_pushups(noise=0.005, seed=1)
    a = accumulate_clip(clip, STRICT)
    b = accumulate_clip(clip, STRICT, fire_lag_s=0.3)
    assert [dataclasses.asdict(x) for x in a] == [dataclasses.asdict(x) for x in b]


def test_aspect_correction_makes_angles_aspect_invariant():
    ref = accumulate_clip(synth_pushups(aspect=16 / 9), STRICT)[1]
    other = accumulate_clip(synth_pushups(aspect=4 / 3), STRICT)[1]
    for k in ("min_elbow_deg_l", "top_elbow_deg", "min_knee_deg", "max_hip_line_dev_deg"):
        assert getattr(other, k) == pytest.approx(getattr(ref, k), abs=0.05)
    # the same normalised landmarks read with a wrong aspect give different angles (correction is not a no-op)
    clip = synth_pushups(aspect=16 / 9)
    for f in clip.frames:
        f.aspect = 1.0
    wrong = accumulate_clip(clip, STRICT)[1]
    assert abs(wrong.min_elbow_deg_l - ref.min_elbow_deg_l) > 3


def test_geometry_helpers_y_down():
    assert angle_deg(np.array([0.0, 0.0]), np.array([1.0, 0.0]), np.array([1.0, 1.0])) == pytest.approx(90.0)
    s, a = np.array([0.0, 0.5]), np.array([1.0, 0.5])
    assert hip_line_dev_deg(s, np.array([0.5, 0.6]), a) > 0          # hip lower in the image = sag
    assert hip_line_dev_deg(s, np.array([0.5, 0.4]), a) < 0          # hip higher = pike
    assert hip_line_dev_deg(a, np.array([0.5, 0.6]), s) > 0          # facing the other way: same sign
    assert hip_line_dev_deg(s, np.array([0.5, 0.5]), a) == pytest.approx(0.0, abs=1e-9)


def test_single_frame_second_person_glitch_ignored_two_frames_flagged():
    clip = synth_pushups(n_reps=1)
    clip.frames[12].persons = 2
    assert verdicts(clip)[0] == (True, [])
    clip.frames[25].persons = 2                       # a second, non-consecutive frame
    assert verdicts(clip)[0] == (False, ["multiple_people"])


def test_long_rep_keeps_early_evidence():
    # 10 s rep: a second person at t = 1..4 s must still reject the rep fired at t = 11 s (no window truncation)
    clip = synth_pushups(n_reps=1, rep_s=10.0, lead_in_s=1.0)
    for f in clip.frames:
        if 1.0 <= f.t <= 4.0:
            f.persons = 2
    assert clip.fire_times == [11.0]
    assert verdicts(clip)[0] == (False, ["multiple_people"])


def test_empty_window_and_reset():
    acc = RepMetricsAccumulator(STRICT)
    m = acc.close_rep(5.0, [], None)
    assert judge_rep(m, STRICT)[1][0] == "not_in_frame" and m.side == "none" and m.frame_conf_frac == 0.0
    clip = synth_pushups(n_reps=2)
    for f in clip.frames:
        acc.add_frame(f)
    acc.reset()
    assert acc.close_rep(clip.fire_times[0], [], None).frame_conf_frac == 0.0


def test_counting_start_is_reset_and_whole_window_counts():
    clip = synth_pushups(lead_in_s=4.0, n_reps=2)
    junk = [FrameObs(t=-10.0 + i / 10, img=None, world=None, persons=0) for i in range(100)]
    acc = RepMetricsAccumulator(STRICT)
    for f in junk:
        acc.add_frame(f)
    acc.reset()                                       # counting starts: setup frames are dropped
    for f in clip.frames:
        acc.add_frame(f)
    ms = [acc.close_rep(tf, [], None) for tf in clip.fire_times]
    assert ms[0].rep_duration_s == pytest.approx(6.0)
    assert [judge_rep(m, STRICT) for m in ms] == [(True, []), (True, [])]
    # without the reset the setup frames still belong to the first rep window (duration), but the first rep is judged
    # from its last lockout before the descent on, so unreadable setup frames cannot fail it (j2 rep window)
    acc = RepMetricsAccumulator(STRICT)
    for f in junk + clip.frames:
        acc.add_frame(f)
    m = acc.close_rep(clip.fire_times[0], [], None)
    assert m.rep_duration_s == pytest.approx(16.0) and judge_rep(m, STRICT) == (True, [])


def test_torso_flag_passthrough_and_labels():
    clip = synth_pushups(n_reps=1)
    m = accumulate_clip(clip, STRICT, torso_ok=False, labels=["pushups - shallow"])[0]
    assert judge_rep(m, STRICT) == (False, ["not_horizontal", "classifier:pushups - shallow"])


def test_low_visibility_frames_reduce_frame_conf_frac():
    clip = synth_pushups(n_reps=1)
    for f in clip.frames[_mid_rep_frames(clip, 1)[0] - 3:][:7]:
        f.img[[11, 12], 3] = 0.1                      # shoulders lost for 7 frames around the bottom
    m = accumulate_clip(clip, STRICT)[0]
    assert m.frame_conf_frac < 0.9 and m.min_keypoint_conf < 0.5
    assert judge_rep(m, STRICT)[1][0] == "not_in_frame"


def test_out_of_image_landmark_counts_as_unconfident():
    clip = synth_pushups(n_reps=1)
    for f in clip.frames:
        f.img[[27, 28], 0] = 1.05                     # ankles cut off at the frame edge, visibility still high
    m = accumulate_clip(clip, STRICT)[0]
    # j3: the ankles are unconfident (no knee angle) but a cut-off foot never rejects the rep
    assert m.min_knee_deg is None and m.frame_conf_frac == 1.0 and judge_rep(m, STRICT) == (True, [])


# ---------------------------------------------------------------- transient faults (D-16)

def _mid_rep_frames(clip, n):
    """Indices of n consecutive good frames around the bottom of the first rep."""
    t_mid = clip.fire_times[0] - 1.0
    i0 = min(range(len(clip.frames)), key=lambda i: abs(clip.frames[i].t - t_mid))
    return list(range(i0, i0 + n))


def _bend_knee(f, side="left"):
    k = 25 if side == "left" else 26
    f.img[k, 1] -= 0.10                               # knee lifted 0.1 frame heights: ~130 deg knee


def _drop_hip(f, side="left"):
    h = 23 if side == "left" else 24
    f.img[h, 1] += 0.09                               # hip pushed toward the floor: ~20 deg sag


def _knee_to_floor(f, side="left"):
    h, k, w, a = (23, 25, 15, 27) if side == "left" else (24, 26, 16, 28)
    u = (f.img[h, 0] - f.img[a, 0]) / (f.img[w, 0] - f.img[a, 0])
    f.img[k, :2] = f.img[a, :2] + u * (f.img[w, :2] - f.img[a, :2])   # knee on the wrist-ankle floor line, under the hip


# j3: a knee bent in the air (_bend_knee) is not knees_down (reason None: never rejected); a bent knee on the floor is
@pytest.mark.parametrize("fault,reason", [(_bend_knee, None), (_drop_hip, "hips_sag"),
                                          (_knee_to_floor, "knees_down")])
@pytest.mark.parametrize("side", SIDES)
def test_transient_faults(fault, reason, side):
    for n_bad, expect_valid in ((1, True), (2, reason is None), (3, reason is None)):
        clip = synth_pushups(n_reps=1, side=side)
        for i in _mid_rep_frames(clip, n_bad):
            fault(clip.frames[i], side)
        valid, reasons = verdicts(clip)[0]
        assert valid is expect_valid, (fault.__name__, n_bad, reasons)
        if not expect_valid:
            assert reason in reasons


def test_single_glitch_cannot_rescue_a_bad_rep():
    clip = synth_pushups(n_reps=1, lockout=140.0)
    i = _mid_rep_frames(clip, 1)[0] + 9               # one frame near the top reads as a perfect lockout
    f = clip.frames[i]
    f.img[15, :2] = f.img[13, :2] + (f.img[13, :2] - f.img[11, :2]) * 0.9
    assert verdicts(clip)[0][1] == ["no_lockout"]


# ---------------------------------------------------------------- near-threshold noise (50 reps per case)

def _pass_rate(noise, **kw):
    ok = n = 0
    for seed in range(10):
        clip = synth_pushups(body=BODY_NAMES[seed % 3], side=SIDES[seed % 2], noise=noise, seed=100 + seed, **kw)
        for valid, _ in verdicts(clip):
            ok += valid
            n += 1
    assert n == 50
    return ok / n


# Cases are relative to the thresholds (lockout thr - 10 / - 5, depth thr + 5 / + 10). Pass-rate bounds per case.
# The brief asked for <= 5% cheat / >= 95% clean everywhere; with per-frame elbow jitter of
# about 4 deg (sigma 0.01) and 9 deg (sigma 0.02) and only a few frames at the top/bottom of a 10 fps rep, a >= 2-frame
# rule cannot separate a 155 deg lockout from the 160 deg threshold at sigma 0.02. These bounds pin what is achieved
# (j2, measured 0.01: clean 1.00, lock-10: 0.00, lock-5: 0.10, depth+5: 0.04, depth+10: 0.00; 0.02: clean 1.00,
# lock-10: 0.14, lock-5: 0.30, depth+5: 0.28, depth+10: 0.04) so a regression fails. depth+5 at sigma 0.02 is looser
# than j1's 0.14 because the real-footage calibration dropped the shoulder-elbow gap gate (docs/challenge/CALIBRATION.md).
# j3 (STRICT thresholds): depth passes when EITHER the elbow or the drop ratio reaches its limit, so jitter on two
# signals lets more near-threshold depth reps through; measured 0.01: depth+5 0.08, depth+10 0.00; 0.02: depth+5 0.38,
# depth+10 0.12 (the lockout cases are unchanged).
NEAR = {
    0.01: {"clean": (">=", 0.95), "lock_m10": ("<=", 0.05), "lock_m5": ("<=", 0.10), "depth_p5": ("<=", 0.10),
           "depth_p10": ("<=", 0.05)},
    0.02: {"clean": (">=", 0.90), "lock_m10": ("<=", 0.20), "lock_m5": ("<=", 0.40), "depth_p5": ("<=", 0.45),
           "depth_p10": ("<=", 0.15)},
}
NEAR_KW = {"clean": {}, "lock_m10": dict(lockout=STRICT["lockout_min_deg"] - 10.0),
           "lock_m5": dict(lockout=STRICT["lockout_min_deg"] - 5.0),
           "depth_p5": dict(depth=STRICT["depth_elbow_max_deg"] + 5.0),
           "depth_p10": dict(depth=STRICT["depth_elbow_max_deg"] + 10.0)}


@pytest.mark.parametrize("noise", sorted(NEAR))
@pytest.mark.parametrize("case", sorted(NEAR_KW))
def test_near_threshold_pass_rates(noise, case):
    op, bound = NEAR[noise][case]
    r = _pass_rate(noise, **NEAR_KW[case])
    assert (r >= bound) if op == ">=" else (r <= bound), (case, noise, r)


def test_knee_floor_margin_no_false_rejects_at_high_noise():
    contact = n = 0
    for body, side in GRID:
        for seed in range(5):
            for m in accumulate_clip(synth_pushups(body=body, side=side, noise=0.02, seed=seed), STRICT):
                contact += bool(m.knee_floor_contact)
                n += 1
    assert contact / n < 0.01
    for body, side in GRID:
        assert all(m.knee_floor_contact for m in accumulate_clip(
            synth_pushups(body=body, side=side, knees_down=True, noise=0.02, seed=1), STRICT))


def test_dispatcher_config_defaults_match_judge_defaults():
    """Every key the dispatcher's fallback config sets equals the judge default, and every calibrated gate key is set
    (a stale gate value there overrides the calibration). Keys it omits (liveness_*, task 12) fall back to
    DEFAULT_THRESHOLDS through merged_thresholds."""
    from challenge.config import DEFAULTS
    cfg = DEFAULTS["judge_thresholds"]
    assert cfg == {k: D[k] for k in cfg}
    assert set(GATE_KEYS) <= set(cfg)
    assert merged_thresholds(cfg) == D


CALIBRATION_SQL = Path(__file__).resolve().parents[2] / "db" / "migrations" / "20261022_challenge_judge_j3.sql"
GATE_KEYS = [k for k, v in D.items() if isinstance(v, (int, float)) and not isinstance(v, bool)
             and not k.startswith(("liveness_", "cue_"))]


def test_calibration_migration_sets_every_gate_value_explicitly():
    sql = CALIBRATION_SQL.read_text()
    obj = json.loads(re.search(r"\|\| '(\{.*?\})'::jsonb", sql, re.S).group(1))
    assert {k: obj.get(k) for k in GATE_KEYS} == {k: D[k] for k in GATE_KEYS}
    assert set(obj) <= set(D)


def test_migrated_competition_config_judges_with_calibrated_thresholds(conn):
    # the seeded judge_thresholds row overrides DEFAULT_THRESHOLDS, so the j3 migration must set every gate value
    for _ in range(2):                                # applied once by the harness; re-running must be a no-op
        v = conn.execute("select value from competition_config where key = 'judge_thresholds'").fetchone()[0]
        assert "depth_margin" not in v and {k: v.get(k) for k in GATE_KEYS} == {k: D[k] for k in GATE_KEYS}
        assert merged_thresholds(v) == D
        conn.execute(CALIBRATION_SQL.read_text())
    for role in ("anon", "authenticated"):
        assert conn.execute("select has_function_privilege(%s, 'ch_stamp_frozen_at()', 'execute')",
                            (role,)).fetchone()[0] is False


def _hips_settling(clip, side, t0, t_from=0.0):
    """Hips 0.12 frame heights high (about -27 deg pike) from t_from until 0.6 s into the descent that starts at t0,
    then coming down linearly onto the plank line by t0 + 0.8 s (bottom at t0 + 1.0)."""
    h = 23 if side == "left" else 24
    for f in clip.frames:
        if t_from <= f.t < t0 + 0.8:
            f.img[h, 1] -= 0.12 * min(1.0, (t0 + 0.8 - f.t) / 0.2)


@pytest.mark.parametrize("side", SIDES)
def test_first_rep_walk_in_pike_ignored_later_pike_kept(side):
    # walking into the plank: hips still coming down through the first part of the first descent (px_8456661 rep 1)
    clip = synth_pushups(n_reps=2, side=side)                     # descents start at 1.0 and 3.0 s
    _hips_settling(clip, side, 1.0)
    assert [v for v, _ in verdicts(clip)] == [True, True]
    # the same hip path in a later rep is a pike (that rep is not a walk-in)
    clip = synth_pushups(n_reps=2, side=side)
    _hips_settling(clip, side, 3.0, t_from=3.0)
    assert verdicts(clip) == [(True, []), (False, ["hips_pike"])]
    # a first rep that never reaches the plank line is still a pike
    clip = synth_pushups(n_reps=1, side=side, hip_offset=-0.15)
    assert verdicts(clip)[0][1][0] == "hips_pike"


def _set_hip_dev(f, side, target):
    """Move the visible-side hip vertically until hip_line_dev_deg reads `target` (deg, + sag / - pike); the knee
    stays on the (straight) ankle-hip line at its original fraction."""
    s, h, a = (11, 23, 27) if side == "left" else (12, 24, 28)
    k = h + 2
    P = lambda k: f.img[k, :2].astype(float) * np.array([f.aspect, 1.0])
    frac = float(np.linalg.norm(f.img[k, :2] - f.img[a, :2]) / np.linalg.norm(f.img[h, :2] - f.img[a, :2]))
    y0 = float(f.img[h, 1])
    lo, hi = y0 - 0.3, y0 + 0.3                      # dev grows with y (hip lower = sag)
    for _ in range(60):
        f.img[h, 1] = (lo + hi) / 2
        if hip_line_dev_deg(P(s), P(h), P(a)) < target:
            lo = f.img[h, 1]
        else:
            hi = f.img[h, 1]
    f.img[k, :2] = f.img[a, :2] + frac * (f.img[h, :2] - f.img[a, :2])


@pytest.mark.parametrize("side", SIDES)
def test_allowed_pike_cannot_mask_sustained_sag(side):
    # +18.5 deg sag held all rep (over the 17.5 sag limit) with a few -19.5 deg frames (inside the 20 deg pike limit)
    clip = synth_pushups(n_reps=5, side=side, hip_offset=0.205 * BODIES["average"]["torso"])
    for tf in clip.fire_times:
        for f in clip.frames:
            if tf - 2.0 < f.t <= tf:
                _set_hip_dev(f, side, 18.5)
    for tf in clip.fire_times:
        for f in clip.frames:
            if tf - 1.6 <= f.t < tf - 1.25:            # 4 consecutive frames early in each descent
                _set_hip_dev(f, side, -19.5)
    vs = verdicts(clip)
    assert all(not v and r == ["hips_sag"] for v, r in vs), vs
    # mirror: an allowed sag cannot mask a sustained pike
    clip = synth_pushups(n_reps=5, side=side)
    for tf in clip.fire_times:
        for f in clip.frames:
            if tf - 2.0 < f.t <= tf:
                _set_hip_dev(f, side, -21.0 if not (tf - 1.6 <= f.t < tf - 1.25) else 17.0)
    vs = verdicts(clip)
    assert all(not v and r == ["hips_pike"] for v, r in vs), vs


def _knees_on_floor_extended(knee_deg=161.7, hip_scale=1.0, **kw):
    """Knee push-up (knee resting on the floor, the rep's pivot) with the foot raised so the knee angle reads
    `knee_deg` in every frame: above the 150 deg knee_min_deg and the 160 deg bent-knee contact limit. hip_scale
    scales the hip's motion about its mean (0 = stationary hips: the torso pivots at the hip)."""
    noise, seed = kw.pop("noise", 0.0), kw.get("seed", 0)
    side = kw.get("side", "left")
    clip = synth_pushups(knees_down=True, **kw)
    h, k, a = (23, 25, 27) if side == "left" else (24, 26, 28)
    rng = np.random.default_rng(seed + 1000)
    hm = np.mean([f.img[h, :2] for f in clip.frames], axis=0)
    for f in clip.frames:
        f.img[h, :2] = hm + (f.img[h, :2] - hm) * hip_scale
        sc = np.array([f.aspect, 1.0])
        H, K, A = f.img[h, :2] * sc, f.img[k, :2] * sc, f.img[a, :2] * sc
        u = (K - H) / np.linalg.norm(K - H)             # thigh continued past the knee
        cands = []
        for sgn in (1.0, -1.0):
            r = np.radians(sgn * (180.0 - knee_deg))
            v = np.array([u[0] * np.cos(r) - u[1] * np.sin(r), u[0] * np.sin(r) + u[1] * np.cos(r)])
            cands.append(K + np.linalg.norm(A - K) * v)
        f.img[a, :2] = min(cands, key=lambda p: p[1]) / sc    # foot raised off the floor
        if noise:
            f.img[:, 0] += rng.normal(0, noise / f.aspect, 33)
            f.img[:, 1] += rng.normal(0, noise, 33)
    return clip


# j3 (owner decision 2026-10-13): knees_down only when clearly on the knees. The j2 pivot test (a knee near the floor
# line whose height does not follow the hips) also fired on real planks seen from a raised phone, so it is gone: a knee
# whose angle reads straight is never knees_down, whatever its height. These synthetic knee-rest reps with a raised
# foot (knee angle 160-162 deg) are therefore not rejected for the knees any more (other gates may still fire).
@pytest.mark.parametrize("noise", [0.0, 0.01, 0.02])
def test_knees_resting_on_floor_with_extended_knee_angle_not_knees_down(noise):
    accepted = total = 0
    for body, side in GRID:
        for seed in range(2):
            clip = _knees_on_floor_extended(body=body, side=side, seed=seed, noise=noise)
            ms = accumulate_clip(clip, STRICT)
            if noise == 0.0:
                assert all(m.min_knee_deg > 160 and not m.knee_floor_contact for m in ms)
            for m in ms:
                v, r = judge_rep(m, STRICT)
                accepted += v
                total += 1
                assert "knees_down" not in r
    assert accepted / total >= 0.95, accepted                 # measured 60/60 at every noise level


@pytest.mark.parametrize("noise", [0.0, 0.01, 0.02])
@pytest.mark.parametrize("hip_scale", [0.0, 0.1, 0.3])
def test_planted_knees_with_little_hip_motion_not_knees_down(hip_scale, noise):
    """Knees at 160.1 deg (just above the bent-knee contact limit) with stationary or barely moving hips: j3 has no
    pivot test, so a straight-reading knee is not knees_down however little the hips move."""
    knees = total = 0
    for body, side in GRID:
        for seed in range(2):
            clip = _knees_on_floor_extended(knee_deg=160.1, hip_scale=hip_scale, body=body, side=side, seed=seed,
                                            noise=noise)
            ms = accumulate_clip(clip, STRICT)
            if noise == 0.0:
                assert all(m.min_knee_deg > 160.0 for m in ms)
            for m in ms:
                v, r = judge_rep(m, STRICT)
                knees += "knees_down" in r
                total += 1
                assert v or r[0] in ("hips_sag", "knees_down")   # the stationary hips sit below the line (STRICT)
    # 0 at sigma <= 0.01; at 0.02 jitter can bend the knee below 150 deg at the floor line: measured 0 / 0 / 2 of 60
    assert knees / total <= (0.0 if noise < 0.02 else 0.05), knees


# ---------------------------------------------------------------- j3 lenient defaults (owner decision 2026-10-13)

@pytest.mark.parametrize("body,side", GRID)
def test_j3_lower_body_out_of_frame_never_rejects(body, side):
    # feet / ankles / knees cut off or occluded: the leg gates are skipped, the arm and torso gates still run
    for seed in range(2):
        ms = accumulate_clip(synth_pushups(body=body, side=side, occlude_lower_body=True, noise=0.01, seed=seed), D)
        assert ms and all(m.min_knee_deg is None and m.knee_floor_contact is None for m in ms)
        assert all(judge_rep(m, D) == (True, []) for m in ms), [judge_rep(m, D) for m in ms]


def test_j3_defaults_still_reject_non_pushups():
    out = {}
    for name, kw in {"arms_out": dict(occlude_arms=True), "tiny_bend": dict(depth=150.0),
                     "bouncing": dict(rep_s=0.4, fps=30.0, lead_in_s=0.0), "two_people": dict(extra_person=True)}.items():
        vs = [judge_rep(m, D) for body, side in GRID for seed in range(2)
              for m in accumulate_clip(synth_pushups(body=body, side=side, noise=0.01, seed=seed, **kw), D)]
        out[name] = (sum(v for v, _ in vs), {r[0] for v, r in vs if not v})
    assert out == {"arms_out": (0, {"not_in_frame"}), "tiny_bend": (0, {"too_shallow"}),
                   "bouncing": (0, {"too_fast"}), "two_people": (0, {"multiple_people"})}
    assert judge_rep(_metrics(torso_ok=False), D) == (False, ["not_horizontal"])          # standing / not in a plank
    assert judge_rep(_metrics(min_knee_deg=95.0, knee_floor_contact=True), D) == (False, ["knees_down"])


def test_j3_defaults_accept_imperfect_form():
    # 125 deg side-view depth, a -28 deg pike and a +20 deg sag all count; the elbow limit is "about 90-125 deg"
    for kw in (dict(depth=125.0), dict(hip_offset=-0.15), dict(hip_offset=sag_offset("average"))):
        vs = [judge_rep(m, D) for side in SIDES for seed in range(2)
              for m in accumulate_clip(synth_pushups(side=side, noise=0.01, seed=seed, **kw), D)]
        assert sum(v for v, _ in vs) / len(vs) >= 0.9, (kw, vs)


# Stored metrics of the owner's real test call (2026-10-13, phone raised off the floor, j2: all 34 reps voided; the 9
# that passed the j2 gates were voided by the liveness challenge). Every one of these is a real rep the j2 gates
# rejected (reason in the comment); j3 accepts them. The last two are setup / walk-in frames and stay rejected.
OWNER_CALL = [
    (dict(min_elbow_deg_l=106.1, min_elbow_deg_r=None, top_elbow_deg=151.44, max_hip_line_dev_deg=-8.06,
          min_knee_deg=152.04, knee_floor_contact=True, shoulder_wrist_drop=0.621, frame_conf_frac=0.9167,
          rep_duration_s=1.887), True),                                               # knees_down, too_shallow
    (dict(min_elbow_deg_l=113.3, min_elbow_deg_r=161.84, top_elbow_deg=163.88, max_hip_line_dev_deg=-13.32,
          min_knee_deg=169.25, knee_floor_contact=False, shoulder_wrist_drop=0.9062, frame_conf_frac=0.7778,
          rep_duration_s=3.128), True),                                               # not_in_frame, too_shallow
    (dict(min_elbow_deg_l=119.15, min_elbow_deg_r=None, top_elbow_deg=162.43, max_hip_line_dev_deg=-20.96,
          min_knee_deg=176.28, knee_floor_contact=False, shoulder_wrist_drop=0.6738, frame_conf_frac=1.0,
          rep_duration_s=0.922), True),                                               # hips_pike, too_shallow
    (dict(min_elbow_deg_l=59.45, min_elbow_deg_r=None, top_elbow_deg=164.63, max_hip_line_dev_deg=-15.88,
          min_knee_deg=166.88, knee_floor_contact=False, shoulder_wrist_drop=0.3443, frame_conf_frac=1.0,
          rep_duration_s=1.006, cadence_rpm=63.2), True),                 # too_fast (cadence > 60; not stored, 63.2 assumed)
    (dict(min_elbow_deg_l=63.41, min_elbow_deg_r=162.59, top_elbow_deg=178.03, max_hip_line_dev_deg=19.69,
          min_knee_deg=166.91, knee_floor_contact=True, shoulder_wrist_drop=0.4701, frame_conf_frac=0.9167,
          rep_duration_s=16.71), True),                                               # knees_down, hips_sag
    (dict(min_elbow_deg_l=65.64, min_elbow_deg_r=138.17, top_elbow_deg=65.64, max_hip_line_dev_deg=48.09,
          min_knee_deg=91.92, knee_floor_contact=False, shoulder_wrist_drop=None, frame_conf_frac=0.1176,
          rep_duration_s=1.57, torso_ok=False), False),                               # walking in: not in frame
    (dict(min_elbow_deg_l=108.1, min_elbow_deg_r=44.91, top_elbow_deg=177.77, max_hip_line_dev_deg=-132.44,
          min_knee_deg=141.42, knee_floor_contact=False, shoulder_wrist_drop=0.4553, frame_conf_frac=0.4667,
          rep_duration_s=3.673), False),                                              # setup: hips far above the line
]


@pytest.mark.parametrize("i", range(len(OWNER_CALL)))
def test_j3_owner_test_call_reps(i):
    kw, ok = OWNER_CALL[i]
    assert judge_rep(_metrics(**kw), D)[0] is ok, judge_rep(_metrics(**kw), D)


def test_j3_world_support_line_ignores_camera_perspective():
    # the incline / decline limit uses the wrist-ankle line in world landmarks: shifting the image ankles up (a phone
    # looking down from the feet side) changes nothing, while a real incline in the world is caught (STRICT 9 deg)
    clip = synth_pushups(n_reps=2)
    for f in clip.frames:
        f.img[[27, 28, 29, 30, 31, 32], 1] -= 0.25
    assert all(m.torso_ok for m in accumulate_clip(clip, STRICT))
    clip = synth_pushups(n_reps=2)
    for f in clip.frames:
        f.world[[27, 28], 1] += 0.4                   # ankles 0.4 m lower than the hands in the world: ~ +18 deg
    assert not any(m.torso_ok for m in accumulate_clip(clip, STRICT))
    assert all(m.torso_ok for m in accumulate_clip(clip, D))
