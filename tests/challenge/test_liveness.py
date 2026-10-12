"""Liveness challenge (task 12): synth-driven acceptance tests (SPEC §6, CONTRACTS C5)."""
from __future__ import annotations

import random

import numpy as np
import pytest

from challenge.judge.cues import CUES
from challenge.judge.gates import DEFAULT_THRESHOLDS
from challenge.judge.liveness import CHALLENGES, LivenessChallenge
from challenge.judge.runtime import JudgeRuntime
from challenge.judge.synth import challenge_motion, synth_pushups

OTHER_HAND = {"left": "right", "right": "left"}


def drive(clip, seed=0, start_t=3.0, thr=None, force=None, stop_on_result=False):
    """Feed a clip as the worker would: on_frame, start at start_t, poll every frame. force = list of cue keys
    to impose on attempts (test hook: overrides the drawn cue so the motion can be placed deterministically)."""
    lc = LivenessChallenge(random.Random(seed), thr)
    log = []
    for f in clip.frames:
        lc.on_frame(f)
        if not lc.started and f.t >= start_t - 1e-9:
            cue = lc.start(f.t)
            if force:
                lc.attempts[0]["cue"] = cue = force[0]
            log.append((round(f.t, 3), "start", cue))
        elif lc.active:
            st, cue = lc.poll(f.t)
            if st == "retry" and force and len(force) > 1:
                lc.attempts[1]["cue"] = cue = force[1]
            if st != "pending":
                log.append((round(f.t, 3), st, cue))
            if stop_on_result and lc.result is not None:
                break
    return lc, log


def statuses(log):
    return [s for _, s, _ in log]


def plank(motions=(), secs=12.0, **kw):
    kw.setdefault("noise", 0.004)
    kw.setdefault("seed", 5)
    return synth_pushups(n_reps=0, lead_in_s=secs, hand_motions=list(motions), **kw)


def test_defaults_and_cue_keys():
    for k in ("liveness_tap_dist", "liveness_lift_h", "liveness_floor_leave"):
        assert k in DEFAULT_THRESHOLDS
    assert DEFAULT_THRESHOLDS["liveness_window_s"] == [45, 150] and DEFAULT_THRESHOLDS["liveness_timeout_s"] == 4
    for k in (*CHALLENGES, "challenge_passed", "challenge_failed"):
        assert k in CUES


def test_schedule_uniform_in_window_and_deterministic():
    fires = [LivenessChallenge(random.Random(s)).schedule(100.0) for s in range(300)]
    assert all(145.0 <= x <= 250.0 for x in fires)
    assert min(fires) < 160 and max(fires) > 235          # spans the window
    assert fires == [LivenessChallenge(random.Random(s)).schedule(100.0) for s in range(300)]
    cues = {LivenessChallenge(random.Random(s)).start(0.0) for s in range(60)}
    assert cues == set(CHALLENGES)
    lc = LivenessChallenge(random.Random(1))
    lc.schedule(0.0)
    with pytest.raises(RuntimeError):
        lc.schedule(0.0)


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("key", CHALLENGES)
@pytest.mark.parametrize("far_vis", [0.45, 0.8])
def test_commanded_motion_within_timeout_passes(side, key, far_vis):
    clip = plank([challenge_motion(key, 4.5)], side=side, far_vis=far_vis)
    lc, log = drive(clip, force=[key])
    assert statuses(log) == ["start", "pass"], log
    assert log[-1][2] == "challenge_passed"
    assert lc.result == "pass" and 4.5 < log[-1][0] <= 3.0 + 4.0
    assert lc.finish(20.0) == "pass"


@pytest.mark.parametrize("seed", range(6))
def test_seeded_cue_answered_passes(seed):
    probe = LivenessChallenge(random.Random(seed))
    key = probe.start(3.0)                    # the cue this seed draws first
    clip = plank([challenge_motion(key, 5.0)], seed=seed)
    lc, log = drive(clip, seed=seed)
    assert log[0][2] == key and statuses(log) == ["start", "pass"]


@pytest.mark.parametrize("reps", [0, 6])
def test_no_motion_replay_retries_with_different_challenge_then_fails(reps):
    clip = synth_pushups(n_reps=reps, lead_in_s=12.0 if reps == 0 else 1.0, tail_s=6.0, depth=55, noise=0.004, seed=2)
    lc, log = drive(clip, seed=4)
    assert statuses(log) == ["start", "retry", "fail"], log
    assert log[1][2] != log[0][2] and log[1][2] in CHALLENGES
    assert log[2][2] == "challenge_failed" and lc.result == "fail"
    assert log[1][0] > 3.0 + 4.0 and log[2][0] > log[1][0] + 4.0
    t0, t1 = lc.window()
    assert t0 == 3.0 and t1 == log[2][0]
    assert lc.poll(50.0) == ("fail", None)          # terminal cue only once
    assert lc.finish(60.0) == "fail"


def test_retry_answered_passes():
    clip = plank([challenge_motion("challenge_tap_right", 8.0)])
    lc, log = drive(clip, force=["challenge_lift_right", "challenge_tap_right"])
    assert statuses(log) == ["start", "retry", "pass"], log
    assert lc.result == "pass"


def test_motion_after_timeout_does_not_pass_that_attempt():
    clip = plank([challenge_motion("challenge_lift_right", 7.3)])      # start 3.0 -> deadline 7.0
    lc, log = drive(clip, force=["challenge_lift_right", "challenge_tap_left"])
    assert statuses(log)[:2] == ["start", "retry"]
    assert "pass" not in statuses(log)


def test_motion_after_timeout_on_both_attempts_fails():
    # each motion answers its cue but starts 4.5 s after it; a lift does not answer a tap cue
    clip = plank([challenge_motion("challenge_lift_right", 7.5), challenge_motion("challenge_tap_left", 11.8)],
                 secs=16.0)
    lc, log = drive(clip, force=["challenge_lift_right", "challenge_tap_left"])
    assert statuses(log) == ["start", "retry", "fail"], log
    assert lc.result == "fail"


def test_motion_before_cue_is_ignored():
    clip = plank([challenge_motion("challenge_lift_right", 0.8, 1.2)])
    lc, log = drive(clip, force=["challenge_lift_right"])
    assert "pass" not in statuses(log)


def test_hand_already_up_at_cue_is_not_a_response():
    clip = plank([challenge_motion("challenge_lift_right", 1.0, 6.0)])     # held up through the cue at 3.0
    lc, log = drive(clip, force=["challenge_lift_right"], stop_on_result=True)
    assert statuses(log)[:2] == ["start", "retry"]


@pytest.mark.parametrize("depth", [50, 75])
@pytest.mark.parametrize("side", ["left", "right"])
def test_pushups_inside_window_do_not_false_pass(depth, side):
    for seed in range(4):
        clip = synth_pushups(n_reps=8, lead_in_s=1.0, rep_s=1.2, depth=depth, side=side, noise=0.006, seed=seed)
        lc, log = drive(clip, seed=seed, start_t=2.0)
        assert "pass" not in statuses(log), (seed, log)


def test_wrong_hand_rejected_when_distinguishable_accepted_when_not():
    # left side view: the right (far) hand is commanded. far_vis 0.8 -> both wrists tracked -> labels distinguishable.
    wrong = [("lift", "left", 4.5, 1.5)]
    _, log = drive(plank(wrong, side="left", far_vis=0.8), force=["challenge_lift_right"], stop_on_result=True)
    assert "pass" not in statuses(log)
    # far hand occluded (vis 0.45): which hand moved is not distinguishable -> any hand
    _, log = drive(plank(wrong, side="left", far_vis=0.45), force=["challenge_lift_right"])
    assert statuses(log) == ["start", "pass"]


def test_lift_is_not_a_tap():
    clip = plank([("lift", "right", 4.5, 1.5), ("lift", "left", 4.5, 1.5)])
    _, log = drive(clip, force=["challenge_tap_left"], stop_on_result=True)
    assert "pass" not in statuses(log)


def test_single_frame_spike_does_not_pass():
    clip = plank(secs=10.0, noise=0.0)
    i = next(k for k, f in enumerate(clip.frames) if f.t >= 4.5)
    for k in (i, i + 3):                       # two isolated 1-frame spikes, never consecutive
        img = clip.frames[k].img
        img[15, 1] = img[11, 1] - 0.02
        img[16, 1] = img[12, 1] - 0.02
    _, log = drive(clip, force=["challenge_lift_right"], stop_on_result=True)
    assert "pass" not in statuses(log)


def test_two_people_in_frame_do_not_pass():
    clip = plank([challenge_motion("challenge_lift_right", 4.5)], extra_person=True)
    _, log = drive(clip, force=["challenge_lift_right"], stop_on_result=True)
    assert "pass" not in statuses(log)


def test_skipped_when_call_ends_before_fire():
    lc = LivenessChallenge(random.Random(3))
    fire = lc.schedule(0.0)
    assert not lc.due(fire - 0.1) and lc.due(fire)
    assert lc.finish(fire - 1.0) == "skipped"
    assert lc.result == "skipped" and lc.window() is None
    with pytest.raises(RuntimeError):
        lc.start(fire)


def test_skipped_when_person_never_in_frame_during_challenge():
    clip = plank(secs=14.0)
    for f in clip.frames:
        if f.t >= 2.5:
            f.img, f.persons = None, 0
    lc, log = drive(clip)
    assert statuses(log) == ["start", "retry", "skipped"], log
    assert log[-1][2] is None and lc.result == "skipped"


def test_absent_first_attempt_seen_second_fails():
    clip = plank(secs=14.0)
    for f in clip.frames:
        if 2.5 <= f.t <= 7.0:
            f.img, f.persons = None, 0
    lc, log = drive(clip)
    assert statuses(log) == ["start", "retry", "fail"]


def test_hangup_during_challenge_fails_and_pass_survives_end():
    clip = plank(secs=5.0)
    lc, _ = drive(clip)
    assert lc.active
    assert lc.finish(5.0) == "fail"
    lc2, _ = drive(plank([challenge_motion("challenge_lift_right", 4.0)], secs=5.5), force=["challenge_lift_right"])
    assert lc2.finish(5.5) == "pass"


def test_poll_before_start_raises_and_deterministic_replay():
    with pytest.raises(RuntimeError):
        LivenessChallenge(random.Random(0)).poll(1.0)
    clip = synth_pushups(n_reps=6, lead_in_s=1.0, tail_s=6.0, noise=0.004, seed=9)
    assert drive(clip, seed=11)[1] == drive(clip, seed=11)[1]


def test_window_feeds_runtime_and_excludes_reps():
    clip = synth_pushups(n_reps=8, lead_in_s=1.0, tail_s=6.0, noise=0.002, seed=1)
    lc, log = drive(clip, seed=2, start_t=4.0)
    rt = JudgeRuntime()
    rt.set_challenge_window(*lc.window())
    t0, t1 = lc.window()
    for f in clip.frames:
        rt.on_frame(f)
    inside = [tf for tf in clip.fire_times if t0 <= tf <= t1]
    assert inside
    for tf in clip.fire_times:
        assert rt.on_rep({"t": tf}).in_challenge == (t0 <= tf <= t1)


def test_bad_thresholds_rejected():
    with pytest.raises(ValueError):
        LivenessChallenge(random.Random(0), {"liveness_window_s": [10, 5]})
    with pytest.raises(ValueError):
        LivenessChallenge(random.Random(0), {"liveness_timeout_s": 0})


def test_synth_motion_validation_and_no_motion_identity():
    with pytest.raises(ValueError):
        synth_pushups(n_reps=1, hand_motions=[("wave", "left", 1.0, 1.0)])
    a = synth_pushups(n_reps=2, noise=0.003, seed=4)
    b = synth_pushups(n_reps=2, noise=0.003, seed=4, hand_motions=[("lift", "right", 99.0, 1.0)])
    assert all(np.array_equal(x.img, y.img) for x, y in zip(a.frames, b.frames))
