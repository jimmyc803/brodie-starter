"""Deterministic push-up gates (CONTRACTS C5, SPEC §6).

`judge_rep(m, thr)` is a pure function of the stored per-rep metrics and the thresholds, so stored reps can be
re-judged later under new thresholds (scripts/rejudge.py). Reasons come back in the fixed C5 priority order:

    multiple_people, not_in_frame, knees_down, hips_sag, hips_pike, too_shallow, no_lockout, too_fast,
    not_horizontal, classifier:<label>

Gate definitions (j4, docs/challenge/CALIBRATION.md "j3 lenient" and "j4"; metrics in challenge/judge/metrics.py).
A gate is evaluated only when its metric is measurable (not None / NaN); an unmeasurable metric passes its gate, so
feet, ankles or knees outside the frame (or the occluded far side) never reject a rep:
  multiple_people  persons_in_frame > 1.
  not_in_frame     persons_in_frame < 1, OR frame_conf_frac (fraction of judged frames whose shoulder, elbow and wrist
                   are confident on at least one side) < thr.frame_conf_frac, OR the upper body is unmeasurable (no
                   elbow angle on either side, no shoulder_wrist_drop and no top_elbow_deg).
  knees_down       knee_floor_contact (the knee at / below the wrist-ankle floor line) AND min_knee_deg < knee_min_deg:
                   clearly on the knees only. Never from a pivot heuristic, never with the knee angle unmeasurable
                   (ankles out of frame: a low close camera put plank knees near the wrists' level in real footage).
  hips_sag         max_hip_line_dev_deg >  hip_line_max_dev_deg   (signed: + = hips below the shoulder-ankle line).
  hips_pike        max_hip_line_dev_deg < -hip_pike_max_dev_deg.
                   Both hip gates are skipped when min_knee_deg < hip_knee_min_deg (j4): with clearly bent legs the
                   shoulder-hip-ankle line is not a body line (and a knee push-up is knees_down's job, not the hips').
  too_shallow      neither depth signal reached its limit: the better side's min elbow (min of min_elbow_deg_l/_r)
                   > depth_elbow_max_deg AND shoulder_wrist_drop > depth_drop_max (either one suffices; a front or
                   diagonal view foreshortens the elbow angle but still shows the shoulder travel). A missing signal
                   cannot pass the rep on its own; only when both are missing is the gate skipped.
                   j5: the drop cannot pass a rep whose min elbow is beyond depth_elbow_max_deg +
                   depth_elbow_veto_deg. That elbow is the view-independent world angle when the image one is
                   foreshortened (metrics j5), so it means the arm stayed straight -- and a phone standing in front of
                   the lifter shrinks the shoulder's image travel enough for a half rep's drop to read deep (D-45).
  no_lockout       top_elbow_deg < lockout_min_deg.
  too_fast         rep_duration_s < min_rep_s OR cadence_rpm > max_cadence_rpm (cadence only once 5 reps exist).
  not_horizontal   not torso_ok (torso_ok also folds in the incline_max_deg / decline_max_deg support-line tilt, which
                   is evaluated when the metrics are computed, so a rejudge cannot change it; same for knee_floor_margin).
  classifier:<l>   label l (case-insensitive) is in classifier_veto or contains any classifier_veto_substrings
                   (both empty by default since j3).
Missing threshold keys fall back to DEFAULT_THRESHOLDS. liveness_enabled (default False since j3) turns the liveness
challenge (challenge/judge/liveness.py, run by challenge/worker/controller.py) back on. say_count (default True; not a
gate) makes the competition worker speak the running valid-rep count; competition_config.judge_thresholds
{"say_count": false} silences it from the next call on, no deploy.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from challenge.judge.metrics import RepMetrics

JUDGE_VERSION = "j5"
# Judge families whose stored metrics the current gates can re-judge (scripts/rejudge.py). j2 metrics are a stricter
# reading of the same quantities (frame_conf_frac over all six keypoints, knee_floor_contact incl. the pivot test), and
# so are j3 metrics relative to j4 (image-only hip deviation, knee and lockout angles, which j4 relaxes with the
# view-independent world landmarks), so re-judging them never accepts more than j4 would have measured live -- except
# the j4 bent-leg hip skip, which a lower stored knee angle can trigger (intended: see "j4" in CALIBRATION.md).
# j4 metrics are likewise a more lenient reading of depth than j5 (an image-only min elbow, which a front view
# foreshortens), so the j5 depth veto can only turn a stored j4 rep invalid, never valid.
REJUDGE_FAMILIES = ("j2", "j3", "j4", "j5")
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_conf": 0.4, "leg_min_conf": 0.7, "frame_conf_frac": 0.6, "knee_min_deg": 145, "knee_floor_margin": 0.1,
    "hip_knee_min_deg": 120,
    "hip_line_max_dev_deg": 30, "hip_pike_max_dev_deg": 40, "depth_elbow_max_deg": 125, "depth_drop_max": 0.88, "depth_elbow_veto_deg": 10,
    "lockout_min_deg": 130, "incline_max_deg": 25, "decline_max_deg": 65, "min_rep_s": 0.45, "max_cadence_rpm": 100,
    "classifier_veto": [], "classifier_veto_substrings": [],
    "liveness_enabled": False, "liveness_window_s": [45, 150], "liveness_timeout_s": 4,
    "cue_min_gap_s": 4, "cue_repeat_gap_s": 10,
    "say_count": True,   # competition calls: Brodie says the running valid-rep count aloud (challenge/worker/controller.py)
    # liveness challenge (challenge/judge/liveness.py; distances in torso lengths, times in seconds); only used with
    # liveness_enabled
    "liveness_lift_h": 0.4, "liveness_floor_leave": 0.25, "liveness_quiet_s": 2.0, "liveness_min_react_s": 0.5,
    "liveness_hold_s": 1.5, "liveness_double_tap_gap_s": 2.0, "liveness_freeze_s": 2.5, "liveness_freeze_still": 0.15,
    "liveness_freeze_motion_min": 0.25, "liveness_cam_shift": 0.3, "liveness_max_gap_s": 0.3,
    "liveness_retry_delay_s": [3.0, 4.5], "liveness_periodic_cv": 0.25,
    "liveness_postpone_s": [10.0, 30.0], "liveness_go_delay_s": [2.0, 8.0], "liveness_go_react_s": 2.0,
    "liveness_go_min_react_s": 0.25, "liveness_hand_cooldown_s": 15.0, "liveness_resume_min": 0.15,
}
REASON_ORDER = ("multiple_people", "not_in_frame", "knees_down", "hips_sag", "hips_pike", "too_shallow",
                "no_lockout", "too_fast", "not_horizontal")


def merged_thresholds(thr: dict | None) -> dict[str, Any]:
    """DEFAULT_THRESHOLDS overlaid with `thr` (a fresh dict; inputs are not mutated)."""
    return {**DEFAULT_THRESHOLDS, **(thr or {})}


def _missing(x: Any) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def _vetoed(label: str, t: dict) -> bool:
    lab = label.strip().lower()
    if lab in {str(v).strip().lower() for v in t["classifier_veto"]}:
        return True
    return any(str(s).lower() in lab for s in t["classifier_veto_substrings"] if str(s))


def _present(*xs: Any) -> list[float]:
    return [float(x) for x in xs if not _missing(x)]


def judge_rep(m: RepMetrics, thr: dict) -> tuple[bool, list[str]]:
    """Pure: (valid, reasons in C5 priority order). valid iff reasons is empty."""
    t = merged_thresholds(thr)
    r: list[str] = []
    if m.persons_in_frame > 1:
        r.append("multiple_people")
    elbows = _present(m.min_elbow_deg_l, m.min_elbow_deg_r)
    upper_body = bool(elbows) or not _missing(m.shoulder_wrist_drop) or not _missing(m.top_elbow_deg)
    if (m.persons_in_frame < 1 or _missing(m.frame_conf_frac) or m.frame_conf_frac < t["frame_conf_frac"]
            or not upper_body):
        r.append("not_in_frame")
    if m.knee_floor_contact is True and not _missing(m.min_knee_deg) and m.min_knee_deg < t["knee_min_deg"]:
        r.append("knees_down")
    legs_straight = _missing(m.min_knee_deg) or m.min_knee_deg >= t["hip_knee_min_deg"]
    if not _missing(m.max_hip_line_dev_deg) and legs_straight:
        if m.max_hip_line_dev_deg > t["hip_line_max_dev_deg"]:
            r.append("hips_sag")
        elif m.max_hip_line_dev_deg < -t["hip_pike_max_dev_deg"]:
            r.append("hips_pike")
    if elbows or not _missing(m.shoulder_wrist_drop):
        # j5: a min elbow this far beyond the depth limit is a straight arm (the world angle when the image one is
        # foreshortened), and the drop is not allowed to overrule it -- a front-on phone shrinks the shoulder travel.
        straight = (bool(elbows)
                    and min(elbows) > t["depth_elbow_max_deg"] + float(t["depth_elbow_veto_deg"]))
        deep = ((bool(elbows) and min(elbows) <= t["depth_elbow_max_deg"])
                or (not straight and not _missing(m.shoulder_wrist_drop)
                    and m.shoulder_wrist_drop <= t["depth_drop_max"]))
        if not deep:
            r.append("too_shallow")
    if not _missing(m.top_elbow_deg) and m.top_elbow_deg < t["lockout_min_deg"]:
        r.append("no_lockout")
    if ((not _missing(m.rep_duration_s) and m.rep_duration_s < t["min_rep_s"])
            or (not _missing(m.cadence_rpm) and m.cadence_rpm > t["max_cadence_rpm"])):
        r.append("too_fast")
    if not m.torso_ok:
        r.append("not_horizontal")
    for lab in dict.fromkeys(m.classifier_labels):
        if _vetoed(lab, t):
            r.append(f"classifier:{lab}")
    return (not r, r)
