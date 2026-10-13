"""Deterministic push-up gates (CONTRACTS C5, SPEC §6).

`judge_rep(m, thr)` is a pure function of the stored per-rep metrics and the thresholds, so stored reps can be
re-judged later under new thresholds (scripts/rejudge.py). Reasons come back in the fixed C5 priority order:

    multiple_people, not_in_frame, knees_down, hips_sag, hips_pike, too_shallow, no_lockout, too_fast,
    not_horizontal, classifier:<label>

Gate definitions (metrics are defined precisely in challenge/judge/metrics.py):
  multiple_people  persons_in_frame > 1.
  not_in_frame     persons_in_frame < 1, OR frame_conf_frac < thr.frame_conf_frac, OR any metric a geometric gate needs
                   is unmeasurable (None / NaN). A gate whose metric is unmeasurable is not evaluated further, so an
                   occluded rep reports not_in_frame rather than a guessed fault.
  knees_down       min_knee_deg < knee_min_deg OR knee_floor_contact.
  hips_sag         max_hip_line_dev_deg >  hip_line_max_dev_deg   (signed: + = hips below the shoulder-ankle line).
  hips_pike        max_hip_line_dev_deg < -hip_line_max_dev_deg.
  too_shallow      visible-side min elbow > depth_elbow_max_deg OR shoulder_elbow_gap > depth_margin
                   (shoulder must reach elbow height within depth_margin torso lengths; contract amendment to C5).
  no_lockout       top_elbow_deg < lockout_min_deg.
  too_fast         rep_duration_s < min_rep_s OR cadence_rpm > max_cadence_rpm (cadence only once 5 reps exist).
  not_horizontal   not torso_ok.
  classifier:<l>   label l (case-insensitive) is in classifier_veto or contains any classifier_veto_substrings.
Missing threshold keys fall back to DEFAULT_THRESHOLDS.
"""
from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from challenge.judge.metrics import RepMetrics

JUDGE_VERSION = "j1"
DEFAULT_THRESHOLDS: dict[str, Any] = {
    "min_conf": 0.5, "frame_conf_frac": 0.9, "knee_min_deg": 160, "knee_floor_margin": 0.02,
    "hip_line_max_dev_deg": 15, "depth_elbow_max_deg": 90, "depth_margin": 0.05, "lockout_min_deg": 160,
    "min_rep_s": 0.8, "max_cadence_rpm": 60,
    "classifier_veto": ["pushups - shallow", "pushups - insufficient", "pushups - elevated hips"],
    "classifier_veto_substrings": ["knee", "sag"], "liveness_window_s": [45, 150], "liveness_timeout_s": 4,
    "cue_min_gap_s": 4,
    # liveness challenge (challenge/judge/liveness.py; distances in torso lengths, times in seconds)
    "liveness_lift_h": 0.4, "liveness_floor_leave": 0.25, "liveness_quiet_s": 2.0, "liveness_min_react_s": 0.5,
    "liveness_hold_s": 1.5, "liveness_double_tap_gap_s": 2.0, "liveness_freeze_s": 2.5, "liveness_freeze_still": 0.15,
    "liveness_freeze_motion_min": 0.25, "liveness_cam_shift": 0.3, "liveness_max_gap_s": 0.3,
    "liveness_retry_delay_s": [3.0, 4.5], "liveness_periodic_cv": 0.25,
    "liveness_postpone_s": [10.0, 30.0],
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


def judge_rep(m: RepMetrics, thr: dict) -> tuple[bool, list[str]]:
    """Pure: (valid, reasons in C5 priority order). valid iff reasons is empty."""
    t = merged_thresholds(thr)
    r: list[str] = []
    if m.persons_in_frame > 1:
        r.append("multiple_people")
    elbow_vis = m.min_elbow_deg_l if m.side == "left" else m.min_elbow_deg_r if m.side == "right" else None
    needed = (m.min_knee_deg, m.knee_floor_contact, m.max_hip_line_dev_deg, elbow_vis, m.shoulder_elbow_gap,
              m.top_elbow_deg)
    if (m.persons_in_frame < 1 or _missing(m.frame_conf_frac) or m.frame_conf_frac < t["frame_conf_frac"]
            or any(_missing(x) for x in needed)):
        r.append("not_in_frame")
    if not _missing(m.min_knee_deg) and m.knee_floor_contact is not None:
        if m.min_knee_deg < t["knee_min_deg"] or m.knee_floor_contact:
            r.append("knees_down")
    if not _missing(m.max_hip_line_dev_deg):
        if m.max_hip_line_dev_deg > t["hip_line_max_dev_deg"]:
            r.append("hips_sag")
        elif m.max_hip_line_dev_deg < -t["hip_line_max_dev_deg"]:
            r.append("hips_pike")
    if not _missing(elbow_vis) and not _missing(m.shoulder_elbow_gap):
        if elbow_vis > t["depth_elbow_max_deg"] or m.shoulder_elbow_gap > t["depth_margin"]:
            r.append("too_shallow")
    if not _missing(m.top_elbow_deg) and m.top_elbow_deg < t["lockout_min_deg"]:
        r.append("no_lockout")
    if (_missing(m.rep_duration_s) or m.rep_duration_s < t["min_rep_s"]
            or (not _missing(m.cadence_rpm) and m.cadence_rpm > t["max_cadence_rpm"])):
        r.append("too_fast")
    if not m.torso_ok:
        r.append("not_horizontal")
    for lab in dict.fromkeys(m.classifier_labels):
        if _vetoed(lab, t):
            r.append(f"classifier:{lab}")
    return (not r, r)
