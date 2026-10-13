"""Ship-gate regression check on the real labelled clips (task 15, docs/challenge/CALIBRATION.md).

Runs only where the gitignored footage exists: judge_eval/clips + judge_eval/labels.yaml in this checkout, or the
paths in JUDGE_EVAL_CLIPS / JUDGE_EVAL_LABELS. Each clip goes through judge_eval.run.run_video_clip (decode, pose,
RepCounter2, judge: the live code path). Slow (about 2 min for ~5k frames), so it is one module-scoped run.

Pinned values are what j2 achieves (clean 86% accepted, worst clean count error 2), so a regression fails. The
ship goal stays 90% accepted / count error <= 1 (judge_eval.run SHIP GATE); it needs more clean side-view footage.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from judge_eval.run import CHEAT, parse_labels, run_video_clip, ship_gate

ROOT = Path(__file__).resolve().parents[2]
CLIPS = Path(os.environ.get("JUDGE_EVAL_CLIPS", ROOT / "judge_eval" / "clips"))
LABELS = Path(os.environ.get("JUDGE_EVAL_LABELS", ROOT / "judge_eval" / "labels.yaml"))

pytestmark = pytest.mark.skipif(not (CLIPS.is_dir() and LABELS.is_file()),
                                reason="real judge_eval clips / labels not present (gitignored, local only)")

# Categories in which no rep may ever be accepted (CHEAT + not_horizontal: incline / decline / wall push-ups).
NEVER_ACCEPT = tuple(CHEAT) + ("not_horizontal",)
# Clips in which RepCounter2 counts nothing, with the reason (CALIBRATION.md "Zero-rep clips").
ZERO_REP_OK = {"px_6970183.mp4": "ankles outside the frame (x ~1.13): the counter's prone gate never arms",
               "px_4804790.mp4": "ankles below the frame (y ~1.12) on an incline ledge: the counter never arms"}


@pytest.fixture(scope="module")
def results():
    labels = [x for x in parse_labels(LABELS.read_text()) if (CLIPS / x.clip).is_file()]
    if not labels:
        pytest.skip("no labelled clip files present")
    return [run_video_clip(x, CLIPS / x.clip, None) for x in labels]


def test_no_cheat_or_non_horizontal_rep_accepted(results):
    bad = {r.label.clip: r.got_valid for r in results if r.label.category in NEVER_ACCEPT and r.got_valid}
    assert bad == {}


# Achieved on the 6 clean clips with judge j2 (D-31): 26/30 = 86.7% accepted, worst count error 2 (px_8456661: two
# honest reps whose sleeves hide the elbow read 145.6 / 146.8 deg at the top and are rejected no_lockout). These pin the
# achieved level so a regression fails. The ship GOAL stays >= 90% / <= 1 (judge_eval.run SHIP GATE); reaching it needs
# more clean side-view footage (docs/challenge/CALIBRATION.md).
CLEAN_ACCEPT_ACHIEVED = 0.86
CLEAN_COUNT_ERR_ACHIEVED = 2


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
    assert all(r.reps or r.label.clip in ZERO_REP_OK for r in results), \
        [r.label.clip for r in results if not r.reps]


def test_latency_p95_under_50ms(results):
    ms = [m for r in results for m in r.frame_ms]
    assert ms and float(np.percentile(ms, 95)) < 50.0
