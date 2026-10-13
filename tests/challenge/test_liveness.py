"""Liveness challenge (task 12 + fix round D-20): detector unit tests, honest-response rates and the replay-attack suite.

Synthetic clips come from challenge.judge.synth (10 Hz, side view). `honest()` simulates a person who answers whatever
cue the challenge draws (reaction 0.6-1.3 s); `replay()` simulates recorded videos that ignore the cue. Rates are over
200 seeds per family and printed (pytest -s) for the report.
"""
from __future__ import annotations

import functools
import random

import numpy as np
import pytest

from challenge.judge.cues import CUES
from challenge.judge.gates import DEFAULT_THRESHOLDS
from challenge.judge.liveness import CHALLENGES, DOUBLE_TAP, FREEZE, LIFT_HOLD, LivenessChallenge
from challenge.judge.runtime import JudgeRuntime
from challenge.judge.synth import BODIES, synth_pushups
from facetime.cues_tts import vocabulary

N_SEEDS = 200
NOW = {"liveness_window_s": [0, 0]}          # schedule(t) fires exactly at t


def drive(clip, fire_t, seed=0, thr=None, force=None, stop_on_result=False, finish=True):
    """Worker loop: on_frame, due -> start, else poll. force = cue keys imposed on attempts 1/2 (TEST HOOK: overrides
    the drawn type so a detector can be tested with a given motion)."""
    lc = LivenessChallenge(random.Random(seed), {**NOW, **(thr or {})})
    lc.schedule(fire_t)
    log = []
    for f in clip.frames:
        lc.on_frame(f)
        if lc.due(f.t):
            cue = lc.start(f.t)
            if force:
                lc.attempts[0].cue = cue = force[0]
            log.append((round(f.t, 3), "start", cue))
        elif lc.active:
            st, cue = lc.poll(f.t)
            if st == "retry" and force and len(force) > 1:
                lc.attempts[1].cue = cue = force[1]
            if st != "pending":
                log.append((round(f.t, 3), st, cue))
            if stop_on_result and lc.result is not None:
                break
    if finish and lc.result is None:
        lc.finish(clip.frames[-1].t)
    return lc, log


def statuses(log):
    return [s for _, s, _ in log]


def response(cue, t0, rr):
    """(hand_motions, pauses) of an honest answer to `cue` played at t0."""
    react, hand = rr.uniform(0.6, 1.3), rr.choice(["left", "right"])
    if cue == LIFT_HOLD:
        return [("lift", hand, t0 + react, 2.6)], [(t0 + react - 0.2, 3.5)]
    if cue == DOUBLE_TAP:
        return ([("lift", hand, t0 + react, 0.9), ("lift", hand, t0 + react + 1.2, 0.9)],
                [(t0 + react - 0.2, 3.4)])
    return [], [(t0 + react, 4.0)]


def honest(seed, noise, prelift=False):
    """A person doing push-ups who answers each cue. Responses start after their cue, so earlier frames are unchanged
    and the cue sequence can be discovered by re-running (asserted)."""
    r = random.Random(seed)
    side, body = r.choice(["left", "right"]), r.choice(sorted(BODIES))
    fire, rep_s, depth = r.uniform(4, 9), r.uniform(1.4, 2.4), r.uniform(60, 85)
    kw = dict(n_reps=int((fire + 22) / rep_s), rep_s=rep_s, depth=depth, lead_in_s=1.0, side=side, body=body,
              noise=noise, seed=seed)
    known: list = []
    for _ in range(3):
        motions, pauses = ([("lift", "left", 1.5, 1.5)] if prelift else []), []
        for i, (cue, st) in enumerate(known):
            m, p = response(cue, st, random.Random(seed * 7919 + i))
            motions += m
            pauses += p
        lc, _ = drive(synth_pushups(hand_motions=motions, pauses=pauses, **kw), fire, seed)
        got = [(a.cue, a.start) for a in lc.attempts]
        n = min(len(got), len(known))
        assert got[:n] == known[:n], "simulation is not causal"
        if len(got) <= len(known):
            return lc
        known = got
    return lc


def replay(seed, family, period=0.0):
    """Recorded video ignoring the cue. Plank hold (n_reps=0) unless the family has push-ups; random phase."""
    r = random.Random(seed)
    fire = r.uniform(4, 10)
    T = fire + 25
    hand, side = r.choice(["left", "right"]), r.choice(["left", "right"])
    kw = dict(n_reps=0, lead_in_s=T, side=side, noise=0.01, seed=seed)
    push = dict(n_reps=int(T / 1.8), rep_s=1.8, lead_in_s=0.5)
    motions, shifts = [], []
    if family in ("taps", "lifts", "push_taps", "push_lifts"):
        kind, dur = ("lift", 2.5) if "lifts" in family else ("tap", 1.0)
        t = r.uniform(0, period)
        while t < T:
            motions.append((kind, hand, t, dur))
            t += period
        if family.startswith("push"):
            kw.update(push)
    elif family in ("random_taps", "push_random_taps"):
        t = r.uniform(0, 3)
        while t < T:
            motions.append(("tap", hand, t, 1.0))
            t += r.uniform(1.5, 5.0)
        if family.startswith("push"):
            kw.update(push)
    elif family in ("camera", "push_camera"):      # phone / filmed screen moved up: wrists look 0.5 torso higher
        t = r.uniform(0, period)
        while t < T:
            shifts.append((t, 2.5, 0.0, -0.2))
            t += period
        if family == "push_camera":
            kw.update(push)
    elif family in ("push_pause", "lift_push_pause"):
        t, pz = r.uniform(0, period), []
        while t < T:
            pz.append((t, 3.0))
            t += period
        kw.update(push, pauses=pz)
        if family == "lift_push_pause":
            motions.append(("lift", hand, 1.0, 1.5))
    elif family == "pushups":
        kw.update(push)
    elif family != "static":
        raise ValueError(family)
    lc, _ = drive(synth_pushups(hand_motions=motions, camera_shifts=shifts, **kw), fire, seed)
    return lc


@functools.lru_cache(maxsize=None)
def replay_rate(family, period=0.0):
    res = [replay(s, family, period) for s in range(N_SEEDS)]
    rate = sum(lc.result == "pass" for lc in res) / N_SEEDS
    print(f"\nREPLAY {family} period={period}: pass {rate:.3f} "
          f"(fail {sum(lc.result == 'fail' for lc in res)}, skipped {sum(lc.result == 'skipped' for lc in res)}, "
          f"suspicious {sum(lc.suspicious for lc in res)})")
    return rate


@functools.lru_cache(maxsize=None)
def honest_results(noise, prelift=False, n=N_SEEDS):
    return [honest(s, noise, prelift) for s in range(n)]


def plank(motions=(), secs=14.0, **kw):
    """Two push-ups (0.5-3.3 s, so push-ups are in progress at a cue around 3-3.5 s), then a plank hold."""
    kw.setdefault("noise", 0.004)
    kw.setdefault("seed", 5)
    return synth_pushups(n_reps=2, rep_s=1.4, lead_in_s=0.5, tail_s=secs - 3.3, hand_motions=list(motions), **kw)


def pushups(secs=16.0, **kw):
    kw.setdefault("noise", 0.004)
    kw.setdefault("seed", 5)
    return synth_pushups(n_reps=int(secs / 1.8), rep_s=1.8, lead_in_s=0.5, **kw)


# ---------------------------------------------------------------- config / scheduling

def test_defaults_and_cue_keys():
    for k in ("liveness_lift_h", "liveness_floor_leave", "liveness_quiet_s", "liveness_min_react_s", "liveness_hold_s",
              "liveness_double_tap_gap_s", "liveness_freeze_s", "liveness_freeze_still", "liveness_cam_shift",
              "liveness_max_gap_s", "liveness_periodic_cv", "liveness_postpone_s"):
        assert k in DEFAULT_THRESHOLDS
    assert DEFAULT_THRESHOLDS["liveness_window_s"] == [45, 150] and DEFAULT_THRESHOLDS["liveness_timeout_s"] == 4
    assert DEFAULT_THRESHOLDS["liveness_quiet_s"] == 2.0 and DEFAULT_THRESHOLDS["liveness_max_gap_s"] == 0.3
    assert set(CHALLENGES) == {"challenge_lift_hold", "challenge_double_tap", "challenge_freeze"}
    for k in (*CHALLENGES, "challenge_passed", "challenge_failed"):
        assert k in CUES and CUES[k] in vocabulary()


def test_schedule_uniform_in_window_and_deterministic():
    fires = [LivenessChallenge(random.Random(s)).schedule(100.0) for s in range(300)]
    assert all(145.0 <= x <= 250.0 for x in fires) and min(fires) < 160 and max(fires) > 235
    assert fires == [LivenessChallenge(random.Random(s)).schedule(100.0) for s in range(300)]
    lc = LivenessChallenge(random.Random(1))
    lc.schedule(0.0)
    with pytest.raises(RuntimeError):
        lc.schedule(0.0)


def test_bad_thresholds_rejected():
    for bad in ({"liveness_window_s": [10, 5]}, {"liveness_timeout_s": 0}, {"liveness_hold_s": 4},
                {"liveness_floor_leave": 0.5, "liveness_lift_h": 0.4}, {"liveness_postpone_s": [0, 1]}):
        with pytest.raises(ValueError):
            LivenessChallenge(random.Random(0), bad)


# ---------------------------------------------------------------- honest responses

@pytest.mark.parametrize("noise,floor", [(0.01, 0.97), (0.02, 0.90)])
def test_honest_response_pass_rate(noise, floor):
    res = honest_results(noise)
    rate = sum(lc.result == "pass" for lc in res) / len(res)
    first = {c: sum(lc.attempts[0].cue == c for lc in res) for c in CHALLENGES}
    print(f"\nHONEST sigma={noise}: pass {rate:.3f} first cues {first}")
    assert rate >= floor
    assert all(v >= 20 for v in first.values())          # every type is exercised


def test_honest_after_an_unprompted_lift_still_passes():
    res = honest_results(0.01, True, 100)
    rate = sum(lc.result == "pass" for lc in res) / len(res)
    print(f"\nHONEST with a lift before the cue: pass {rate:.3f}")
    assert rate >= 0.95
    assert all(a.cue == FREEZE for lc in res for a in lc.attempts)     # a lifted hand rules out the hand types


def test_honest_is_deterministic():
    a, b = honest(3, 0.01).summary(), honest(3, 0.01).summary()
    assert a == b


# ---------------------------------------------------------------- replay-attack suite (D-20)

@pytest.mark.parametrize("family,period", [
    ("taps", 3), ("push_taps", 2), ("push_taps", 3), ("push_taps", 4), ("push_taps", 5),
    ("lifts", 8), ("push_lifts", 5), ("push_lifts", 8), ("push_lifts", 12), ("push_lifts", 35), ("push_lifts", 90),
    ("random_taps", 0), ("push_random_taps", 0),
    ("camera", 6), ("push_camera", 4), ("push_camera", 6), ("push_camera", 8),
    ("static", 0), ("pushups", 0),
])
def test_replay_pass_rate_at_most_5pct(family, period):
    assert replay_rate(family, period) <= 0.05


@pytest.mark.xfail(strict=True, reason="known residual: push-ups with a >=2.5 s pause every few seconds answer FREEZE "
                                       "when a pause starts 0.5-1.5 s after the cue (needs a timing-coupled 2nd cue)")
@pytest.mark.parametrize("family", ["push_pause", "lift_push_pause"])
def test_replay_pause_pattern_vs_freeze(family):
    assert replay_rate(family, 6) <= 0.05


def test_periodic_taps_flag_suspicious_but_do_not_fail_alone():
    lc = replay(1, "taps", 3)
    assert lc.unprompted_lifts >= 3 and lc.suspicious
    s = lc.summary()
    assert s["unprompted_lifts"] == lc.unprompted_lifts and s["suspicious"] is True
    irregular = [("tap", "left", t, 1.0) for t in (1.0, 2.6, 8.0, 9.5, 16.0)]      # intervals 1.6 5.4 1.5 6.5
    lc2, _ = drive(plank(irregular, secs=20.0), 99.0)
    assert lc2.unprompted_lifts == 5 and not lc2.suspicious


# ---------------------------------------------------------------- detectors (forced cue: TEST HOOK)

LIFT = ("lift", "right", 4.6, 2.6)
DTAP = [("lift", "left", 4.6, 0.9), ("lift", "left", 5.8, 0.9)]


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("far_vis", [0.45, 0.8])
def test_lift_hold_and_double_tap_detected(side, far_vis):
    _, log = drive(plank([LIFT], side=side, far_vis=far_vis), 3.5, force=[LIFT_HOLD])
    assert statuses(log) == ["start", "pass"], log
    _, log = drive(plank(DTAP, side=side, far_vis=far_vis), 3.5, force=[DOUBLE_TAP])
    assert statuses(log) == ["start", "pass"], log


def test_freeze_detected_only_after_a_stop():
    lc, log = drive(pushups(pauses=[(5.0, 4.0)]), 4.2, force=[FREEZE])
    assert statuses(log) == ["start", "pass"], log
    _, log = drive(pushups(), 4.2, force=[FREEZE], stop_on_result=True)
    assert "pass" not in statuses(log)


def test_motions_do_not_cross_answer():
    for motions, cue in (([LIFT], DOUBLE_TAP), (DTAP, LIFT_HOLD), ([LIFT], FREEZE), (DTAP, FREEZE)):
        clip = plank(motions) if cue != FREEZE else pushups(pauses=[(4.6, 4.0)], hand_motions=motions)
        _, log = drive(clip, 3.5, force=[cue], stop_on_result=True)
        assert "pass" not in statuses(log)[:2], (motions, cue, log)


def test_slow_double_tap_and_short_hold_fail():
    slow = [("lift", "left", 4.6, 0.9), ("lift", "left", 6.9, 0.9)]          # onsets 2.3 s apart
    _, log = drive(plank(slow), 3.5, force=[DOUBLE_TAP], stop_on_result=True)
    assert "pass" not in statuses(log)[:2]
    _, log = drive(plank([("lift", "right", 4.6, 1.3)]), 3.5, force=[LIFT_HOLD], stop_on_result=True)
    assert "pass" not in statuses(log)[:2]


def test_motion_after_timeout_does_not_pass_that_attempt():
    lc, log = drive(plank([("lift", "right", 7.0, 2.6)]), 3.0, force=[LIFT_HOLD])     # deadline 7.0
    assert lc.attempts[0].outcome == "timeout" and lc.attempts[0].passed_at is None


def test_response_before_min_reaction_is_ignored():
    lc, _ = drive(plank([("lift", "right", 3.0, 2.6)]), 3.05, force=[LIFT_HOLD])
    assert lc.attempts[0].passed_at is None


def test_hand_up_before_cue_voids_the_attempt():
    # push-ups keep FREEZE eligible after the lift, so the cue is issued (and then forced to LIFT_HOLD)
    lc, log = drive(pushups(hand_motions=[("lift", "right", 1.0, 6.0)]), 3.0, force=[LIFT_HOLD])
    assert lc.attempts[0].outcome == "quiet" and lc.attempts[0].passed_at is None
    lc, _ = drive(pushups(hand_motions=[("lift", "right", 1.0, 1.4)]), 3.5, force=[LIFT_HOLD])  # down 1.1 s before
    assert lc.attempts[0].invalid == "quiet"
    lc, _ = drive(pushups(hand_motions=[("lift", "right", 0.2, 1.0)]), 3.5, force=[LIFT_HOLD])  # down > 2 s before
    assert lc.attempts[0].invalid is None


def test_camera_shift_during_attempt_invalidates():
    clip = plank([LIFT], camera_shifts=[(4.4, 3.0, 0.0, -0.2)])
    lc, _ = drive(clip, 3.5, force=[LIFT_HOLD])
    assert lc.attempts[0].outcome == "camera" and lc.attempts[0].passed_at is None


def test_camera_shift_alone_does_not_fake_a_lift():
    clip = plank(camera_shifts=[(4.4, 3.0, 0.0, -0.2)])
    lc, _ = drive(clip, 3.5, force=[LIFT_HOLD], thr={"liveness_cam_shift": 99.0})     # camera check disabled
    assert lc.attempts[0].passed_at is None


def test_timestamp_gap_resets_evidence():
    clip = plank([LIFT])
    frames = [f for f in clip.frames if not 4.75 <= f.t <= 5.3]         # 0.6 s hole right as the hand rises
    clip.frames[:] = frames
    lc, _ = drive(clip, 3.5, force=[LIFT_HOLD], stop_on_result=True)
    assert lc.attempts[0].passed_at is None


def test_single_frame_spikes_do_not_pass():
    clip = plank(secs=10.0, noise=0.0)
    i = next(k for k, f in enumerate(clip.frames) if f.t >= 4.5)
    for k in (i, i + 3, i + 6):
        img = clip.frames[k].img
        img[15, 1] = img[11, 1] - 0.05
        img[16, 1] = img[12, 1] - 0.05
    lc, _ = drive(clip, 3.5, force=[DOUBLE_TAP], stop_on_result=True)
    assert lc.attempts[0].passed_at is None


def test_two_people_cannot_pass():
    clip = plank([LIFT])
    for f in clip.frames:
        if f.t >= 4.0:
            f.persons = 2                                # a second person appears for the response
    lc, _ = drive(clip, 3.5, force=[LIFT_HOLD], stop_on_result=True)
    assert lc.attempts[0].passed_at is None and lc.result != "pass"


# ---------------------------------------------------------------- flow / results

def test_no_motion_retries_different_type_then_fails():
    lc, log = drive(pushups(secs=20.0), 4.0, seed=4)
    assert statuses(log) == ["start", "retry", "fail"], log
    assert log[1][2] != log[0][2] and log[2][2] == "challenge_failed"
    a1, a2 = lc.attempts
    assert a1.outcome == "timeout" and 8.0 + 3.0 <= a2.start <= 8.0 + 4.5 + 0.11
    assert lc.windows() == [(a1.start, a1.deadline), (a2.start, a2.deadline)]
    assert lc.poll(99.0) == ("fail", None) and lc.finish(99.0) == "fail"


def test_retry_answered_passes():
    lc, _ = drive(pushups(secs=20.0), 3.0, force=[DOUBLE_TAP, LIFT_HOLD])
    t_retry = lc.attempts[1].start                       # the retry time is random; answer it 0.8 s after
    clip = pushups(secs=20.0, hand_motions=[("lift", "right", t_retry + 0.8, 2.6)])
    lc, log = drive(clip, 3.0, force=[DOUBLE_TAP, LIFT_HOLD])
    assert statuses(log) == ["start", "retry", "pass"], log


def test_no_challenge_while_not_doing_pushups_and_hand_types_ruled_out_after_a_lift():
    lc, log = drive(synth_pushups(n_reps=0, lead_in_s=40.0, noise=0.004, seed=5), 4.0)
    assert not lc.attempts and lc.postponed >= 1 and lc.fire_t > 14.0
    assert lc.result == "skipped"                        # the call ended before the (postponed) cue
    lc, log = drive(pushups(secs=20.0, hand_motions=[("lift", "left", 1.0, 1.5)]), 4.0)
    assert lc.attempts[0].cue == FREEZE


def test_skipped_when_call_ends_before_fire():
    lc = LivenessChallenge(random.Random(3))
    fire = lc.schedule(0.0)
    assert not lc.due(fire - 0.1)
    assert lc.finish(fire - 1.0) == "skipped" and lc.windows() == []
    with pytest.raises(RuntimeError):
        lc.start(fire)


def test_skipped_only_when_nobody_in_frame():
    clip = pushups(secs=20.0)
    for f in clip.frames:
        if f.t >= 3.9:
            f.img, f.persons = None, 0
    lc, log = drive(clip, 4.0)
    assert statuses(log) == ["start"] and lc.result == "skipped"     # the retry was never possible (nobody there)
    assert lc.summary()["attempts"][0]["seen"] is False


def test_present_but_wrists_hidden_fails():
    clip = pushups(secs=20.0)
    for f in clip.frames:
        if f.t >= 3.9:
            f.img[[15, 16], 3] = 0.0
            f.img[[15, 16], 0] = np.nan
    lc, log = drive(clip, 4.0)
    assert lc.result == "fail"


def test_hangup_during_challenge_or_pending_retry_fails():
    lc, _ = drive(pushups(secs=5.0), 4.0, finish=False)
    assert lc.active and lc.finish(5.0) == "fail"
    lc, _ = drive(pushups(secs=9.0), 4.0, finish=False)
    assert lc.active and lc.finish(9.0) == "fail"        # first attempt over, retry pending


def test_poll_before_start_raises():
    with pytest.raises(RuntimeError):
        LivenessChallenge(random.Random(0)).poll(1.0)


def test_windows_feed_runtime():
    clip = pushups(secs=20.0, noise=0.002, seed=1)
    lc, _ = drive(clip, 4.0, seed=2)
    rt = JudgeRuntime()
    for w in lc.windows():
        rt.set_challenge_window(*w)
    for f in clip.frames:
        rt.on_frame(f)
    fires = [tf for tf in clip.fire_times]
    flags = [rt.on_rep({"t": tf}).in_challenge for tf in fires]
    assert flags == [any(a <= tf <= b for a, b in lc.windows()) for tf in fires] and any(flags)


# ---------------------------------------------------------------- synth extensions

def test_synth_motion_validation_and_causality():
    with pytest.raises(ValueError):
        synth_pushups(n_reps=1, hand_motions=[("wave", "left", 1.0, 1.0)])
    with pytest.raises(ValueError):
        synth_pushups(n_reps=1, pauses=[(1.0, 2.0), (2.0, 1.0)])
    with pytest.raises(ValueError):
        synth_pushups(n_reps=1, camera_shifts=[(1.0, 0.0, 0, 0)])
    a = synth_pushups(n_reps=4, noise=0.003, seed=4)
    b = synth_pushups(n_reps=4, noise=0.003, seed=4, hand_motions=[("lift", "right", 5.0, 1.0)],
                      pauses=[(5.0, 2.0)], camera_shifts=[(5.0, 1.0, 0.0, -0.1)])
    early = [(x, y) for x, y in zip(a.frames, b.frames) if x.t < 5.0]
    assert early and all(np.array_equal(x.img, y.img) for x, y in early)
    assert len(b.frames) == len(a.frames) + 20 and b.fire_times[-1] == pytest.approx(a.fire_times[-1] + 2.0)
