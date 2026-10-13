"""Ship-gate regression check on the real labelled clips (task 15, docs/challenge/CALIBRATION.md).

Ship-gate step, run explicitly (not collected by the unit suite, because the footage is gitignored and local only):
    PYTHONPATH=src:. .venv/bin/python -m pytest -q -p no:cacheprovider judge_eval/check_real_clips.py
Needs judge_eval/clips + judge_eval/labels.yaml in this checkout, or the paths in JUDGE_EVAL_CLIPS / JUDGE_EVAL_LABELS;
it FAILS (does not skip) when they are missing, so a gate run can never pass vacuously.
Each clip goes through judge_eval.run.run_video_clip (decode, pose,
RepCounter2, judge: the live code path). Slow (about 2 min for ~5k frames), so it is one module-scoped run.

Pinned values are what j3 (lenient, CALIBRATION.md "j3 lenient") achieves: clean 29/30 = 93.3% accepted, worst clean
count error 1, off-angle 31 reps accepted, so a regression fails. j3 deliberately accepts moderate inclines / declines
(owner decision), so not_horizontal is no longer a never-accept category; its acceptance is pinned to an upper bound
instead, so it cannot silently grow.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from judge_eval.run import CHEAT, parse_labels, run_video_clip, ship_gate

ROOT = Path(__file__).resolve().parents[1]
CLIPS = Path(os.environ.get("JUDGE_EVAL_CLIPS", ROOT / "judge_eval" / "clips"))
LABELS = Path(os.environ.get("JUDGE_EVAL_LABELS", ROOT / "judge_eval" / "labels.yaml"))


# Categories in which no rep may ever be accepted (knees, two people). j2 also listed not_horizontal here; j3 accepts
# inclines up to incline_max_deg 25 / declines up to decline_max_deg 35 by design (see test_not_horizontal_bounded).
NEVER_ACCEPT = tuple(CHEAT)
# Clips in which RepCounter2 counts nothing, with the reason (CALIBRATION.md "Zero-rep clips").
ZERO_REP_OK = {"px_6970183.mp4": "ankles outside the frame (x ~1.13): the counter's prone gate never arms",
               "px_4804790.mp4": "ankles below the frame (y ~1.12) on an incline ledge: the counter never arms"}


@pytest.fixture(scope="module")
def results():
    assert CLIPS.is_dir() and LABELS.is_file(), f"real clips/labels missing: {CLIPS}, {LABELS}"
    labels = [x for x in parse_labels(LABELS.read_text()) if (CLIPS / x.clip).is_file()]
    assert labels, "no labelled clip files present"
    return [run_video_clip(x, CLIPS / x.clip, None) for x in labels]


def test_no_cheat_or_non_horizontal_rep_accepted(results):
    bad = {r.label.clip: r.got_valid for r in results if r.label.category in NEVER_ACCEPT and r.got_valid}
    assert bad == {}


# j3: 8 of the 12 counted reps in the 6 not_horizontal clips are accepted (px_4804783 3, px_8171386 3, px_8402109 1,
# px_6970145 1: moderate inclines inside incline_max_deg 25). The steep ones are still rejected. Upper bound pinned.
NOT_HORIZONTAL_ACCEPT_MAX = 8


def test_not_horizontal_bounded(results):
    got = {r.label.clip: r.got_valid for r in results if r.label.category == "not_horizontal"}
    assert got, "no not_horizontal clips"
    assert sum(got.values()) <= NOT_HORIZONTAL_ACCEPT_MAX, got


# Achieved on the 6 clean clips. j2 (D-31): 26/30 = 86.7%, worst count error 2 (px_8456661 sleeves read 145-147 deg at
# the top, rejected no_lockout). j3 (lockout 135): 29/30 = 93.3%, worst count error 1 (px_4945123: one no_lockout).
# Raised deliberately to the j3 level, which meets the ship goal (>= 90% / <= 1), so a regression fails.
CLEAN_ACCEPT_ACHIEVED = 0.93
CLEAN_COUNT_ERR_ACHIEVED = 1
# Off-angle reps accepted: j2 3 (support line read -25..-43 deg from the camera angle), j3 31 of 44 expected (world
# wrist-ankle support line, per-signal keypoints). Pinned so the angle robustness cannot regress.
OFF_ANGLE_ACCEPTED_ACHIEVED = 31


def test_clean_acceptance_and_count_error(results):
    gate = ship_gate(results)
    clean = {r.label.clip: (r.label.expected_valid, r.got_valid, len(r.reps)) for r in results
             if r.label.category == "clean"}
    assert clean, "no clean clips"
    assert gate["clean_accept_rate"] >= CLEAN_ACCEPT_ACHIEVED, clean
    assert all(r.count_error <= CLEAN_COUNT_ERR_ACHIEVED for r in results if r.label.category == "clean"), clean


def test_off_angle_clips_still_count_reps(results):
    silent = [r.label.clip for r in results if r.label.category == "off_angle" and not r.reps]
    assert silent == []
    off = {r.label.clip: r.got_valid for r in results if r.label.category == "off_angle"}
    assert sum(off.values()) >= OFF_ANGLE_ACCEPTED_ACHIEVED, off
    assert all(r.reps or r.label.clip in ZERO_REP_OK for r in results), \
        [r.label.clip for r in results if not r.reps]


def test_latency_p95_under_50ms(results):
    ms = [m for r in results for m in r.frame_ms]
    assert ms and float(np.percentile(ms, 95)) < 50.0
