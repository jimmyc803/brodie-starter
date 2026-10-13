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


class _ForcedRandom(random.Random):
    """TEST HOOK: choice() over challenge types returns the next forced type (so a detector can be tested with a given
    motion); every other draw is the seeded generator's."""

    def __init__(self, seed, forced):
        super().__init__(seed)
        self.forced = list(forced)

    def choice(self, seq):
        if self.forced and set(seq) <= set(CHALLENGES):
            return self.forced.pop(0)
        return super().choice(seq)


def drive(clip, fire_t, seed=0, thr=None, force=None, stop_on_result=False, finish=True):
    """Worker loop: on_frame, due -> start, else poll. force = challenge types imposed on attempts 1/2 (_ForcedRandom)."""
    lc = LivenessChallenge(_ForcedRandom(seed, force or ()), {**NOW, **(thr or {})})
    lc.schedule(fire_t)
    log = []
    for f in clip.frames:
        lc.on_frame(f)
        if lc.due(f.t):
            cue = lc.start(f.t)
            log.append((round(f.t, 3), "start", cue))
        elif lc.active:
            st, cue = lc.poll(f.t)
            if st != "pending":
                log.append((round(f.t, 3), st, cue))
            if stop_on_result and lc.result is not None:
                break
    if finish and lc.result is None:
        lc.finish(clip.frames[-1].t)
    return lc, log


def statuses(log):
    return [s for _, s, _ in log]


def response(cue, t0, rr, go_t=None):
    """(hand_motions, pauses) of an honest answer to `cue` played at t0. FREEZE: stop after the reaction time and,
    once the go cue time is known, resume push-ups 0.3-0.8 s after it (until then: hold)."""
    react, hand, go_react = rr.uniform(0.6, 1.3), rr.choice(["left", "right"]), rr.uniform(0.3, 0.8)
    if cue == LIFT_HOLD:
        return [("lift", hand, t0 + react, 2.6)], [(t0 + react - 0.2, 3.5)]
    if cue == DOUBLE_TAP:
        return ([("lift", hand, t0 + react, 0.9), ("lift", hand, t0 + react + 1.2, 0.9)],
                [(t0 + react - 0.2, 3.4)])
    return [], [(t0 + react, 15.0 if go_t is None else go_t + go_react - (t0 + react))]


def honest(seed, noise, prelift=False, rest=False, adjust=0):
    """A person doing push-ups who answers each cue (rest: three push-ups, then a plank hold through the cues).
    adjust = n > 0: n phone adjustments (1.5 s hand lifts) 20-40 s apart, the last 0.5-5 s before the first check, so
    every early check finds the hand types in cooldown. Responses start after their cue, so earlier frames are
    unchanged and the cue sequence can be discovered by re-running (asserted)."""
    r = random.Random(seed)
    side, body = r.choice(["left", "right"]), r.choice(sorted(BODIES))
    fire, rep_s, depth = r.uniform(4, 9), r.uniform(1.4, 2.4), r.uniform(60, 85)
    kw = dict(n_reps=int((fire + 40) / rep_s), rep_s=rep_s, depth=depth, lead_in_s=1.0, side=side, body=body,
              noise=noise, seed=seed)
    if rest:
        fire = 1.0 + 3 * rep_s + r.uniform(2.5, 8.0)
        kw.update(n_reps=3, tail_s=fire + 40 - (1.0 + 3 * rep_s))
    adj = []
    if adjust:
        times = [1.0 + 3 * rep_s + 1.0]
        for _ in range(adjust - 1):
            times.append(times[-1] + r.uniform(20, 40))
        fire = times[-1] + r.uniform(0.5, 5.0)
        adj = [("lift", r.choice(["left", "right"]), x, 1.5) for x in times]
        span = fire + 90                                 # room for postponed checks after the cooldown
        kw.update(n_reps=3, tail_s=span - (1.0 + 3 * rep_s)) if rest else kw.update(n_reps=int(span / rep_s))
    known: list = []        # (cue, start, go_t) per attempt, as found by the previous run
    fixed = 0               # attempts of `known` that the previous run produced with correct (non-placeholder) input
    for _ in range(8):
        motions, pauses = ([("lift", "left", 1.5, 1.5)] if prelift else []) + list(adj), []
        for i, (cue, st, go_t) in enumerate(known):
            m, p = response(cue, st, random.Random(seed * 7919 + i), go_t)
            motions += m
            pauses += p
        pauses.sort()
        pauses = [(a, min(d, nxt[0] - a - 0.1) if nxt else d) for (a, d), nxt in zip(pauses, pauses[1:] + [None])]
        lc, _ = drive(synth_pushups(hand_motions=motions, pauses=pauses, **kw), fire, seed)
        # a go time is real only if this run answered the attempt (with the hold-until-told placeholder or an earlier
        # go time); for an attempt new in this run it reflects no response at all, so the next run holds until told
        got = [(a.cue, a.start, a.go_t if a.go_said and i < len(known) and known[i][:2] == (a.cue, a.start) else None)
               for i, a in enumerate(lc.attempts)]
        # responses only act after their cue, so attempts produced from correct input must not change
        assert [g[:2] for g in got[:fixed]] == [k[:2] for k in known[:fixed]], "simulation is not causal"
        if got == known:
            return lc
        # next run, attempt i is reproduced iff it and every earlier attempt match this run's input (then all
        # responses before it are final); the first new attempt after a fully matching prefix is fixed too
        # (a mismatching attempt may itself have been steered by a stale response, so it is not fixed either)
        same = next((j for j in range(min(len(got), len(known))) if known[j] != got[j]), min(len(got), len(known)))
        fixed = same + (1 if same == len(known) < len(got) else 0)
        known = got
    raise AssertionError("honest simulation did not converge")


def replay(seed, family, period=0.0):
    """Recorded video ignoring the cue. Plank hold (n_reps=0) unless the family has push-ups; random phase."""
    r = random.Random(seed)
    # bank_*: the cue is drawn from a 105 s span like the production window (45-150 s): there the attack is a first
    # hand lift that happens to land just after the cue, and its odds scale with ~2 s / span
    fire = r.uniform(4, 10) if not family.startswith("bank_") else r.uniform(10, 115)
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
    elif family in ("push_pause", "lift_push_pause", "push_long_pause"):
        t, pz = r.uniform(0, period), []
        L = period - 3.0 if family == "push_long_pause" else 3.0      # long pauses: 3 s of push-ups between
        while t < T:
            pz.append((t, L))
            t += period
        kw.update(push, pauses=pz)
        if family == "lift_push_pause":
            motions.append(("lift", hand, 1.0, 1.5))
    elif family.startswith("bank_"):             # four push-ups (reps banked by ~7.7 s), then a plank hold
        kw.update(n_reps=4, rep_s=1.8, lead_in_s=0.5, tail_s=T - 7.7)
        if family != "bank_still":
            kind, dur = ("lift", 2.5) if family == "bank_lifts" else ("tap", 1.0)
            t = 8.0 + r.uniform(0, 105.0 if period >= 105 else period)
            while t < T:
                motions.append((kind, hand, t, dur))
                t += period
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
def honest_results(noise, prelift=False, n=N_SEEDS, rest=False, adjust=0):
    return [honest(s, noise, prelift, rest, adjust) for s in range(n)]


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
              "liveness_max_gap_s", "liveness_periodic_cv", "liveness_postpone_s", "liveness_go_delay_s",
              "liveness_go_react_s", "liveness_go_min_react_s", "liveness_resume_min", "liveness_hand_cooldown_s"):
        assert k in DEFAULT_THRESHOLDS
    assert DEFAULT_THRESHOLDS["liveness_window_s"] == [45, 150] and DEFAULT_THRESHOLDS["liveness_timeout_s"] == 4
    assert DEFAULT_THRESHOLDS["liveness_quiet_s"] == 2.0 and DEFAULT_THRESHOLDS["liveness_max_gap_s"] == 0.3
    assert set(CHALLENGES) == {"challenge_lift_hold", "challenge_double_tap", "challenge_freeze"}
    for k in (*CHALLENGES, "challenge_go", "challenge_passed", "challenge_failed"):
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
    assert all(lc.attempts[0].cue == FREEZE for lc in res)      # the lift's cooldown rules out the hand types


def test_honest_at_rest_passes():
    res = honest_results(0.01, rest=True)
    rate = sum(lc.result == "pass" for lc in res) / len(res)
    print(f"\nHONEST at rest: pass {rate:.3f}")
    assert rate >= 0.99 and all(a.cue != FREEZE for lc in res for a in lc.attempts)


@pytest.mark.parametrize("rest,adjust", [(True, 1), (False, 1), (True, 2), (True, 3), (False, 3)])
def test_honest_after_phone_adjustments_passes(rest, adjust):
    """Lift once (or 2-3 times, 20-40 s apart) to adjust the phone, then rest or keep pushing: the hand types come
    back after liveness_hand_cooldown_s, so a person at rest is still cued and can pass."""
    res = honest_results(0.01, n=N_SEEDS, rest=rest, adjust=adjust)
    rate = sum(lc.result == "pass" for lc in res) / len(res)
    print(f"\nHONEST adjust={adjust} {'rest' if rest else 'push'}: pass {rate:.3f}")
    assert rate >= 0.99
    if rest:
        assert all(a.cue != FREEZE for lc in res for a in lc.attempts) and all(lc.postponed >= 1 for lc in res)


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
    ("bank_still", 0), ("bank_taps", 3), ("bank_lifts", 8), ("bank_lifts", 12), ("bank_lifts", 16),
    ("bank_lifts", 200),
])
def test_replay_pass_rate_at_most_5pct(family, period):
    assert replay_rate(family, period) <= 0.05


@pytest.mark.parametrize("family", ["push_pause", "lift_push_pause"])
def test_replay_pause_pattern_vs_freeze(family):
    """Push-ups with a 3 s pause every 6 s (D-29: closed by the random-time go cue)."""
    assert replay_rate(family, 6) <= 0.05


@pytest.mark.parametrize("period", [8, 9])
def test_replay_long_pauses_vs_freeze_go(period):
    """Adaptive variant: pauses long enough to outlast confirm + go delay (period-3 s pause, 3 s of push-ups)."""
    assert replay_rate("push_long_pause", period) <= 0.05


@pytest.mark.xfail(strict=True, reason="D-30 accepted residual: period 10/12 long pauses beat FREEZE+go 6.0%/8.5% "
                                       "(go delay 2-8 s); mitigated by admin re-judge of top finishers")
@pytest.mark.parametrize("period", [10, 12])
def test_replay_long_pauses_residual(period):
    assert replay_rate("push_long_pause", period) <= 0.05


@pytest.mark.xfail(strict=True, reason="hand-cooldown residual: lifts spaced just beyond liveness_hand_cooldown_s at rest "
                                       "(bank_lifts P20/25/35: 9.5/7.5/8.0%; 1.5-2.0% with the old sticky rule); "
                                       "push_lifts P16/20/25 (8.0/9.5/6.0%) were 7.0/9.5/6.0% before - a first lift "
                                       "just after a cue drawn from the test's 6 s span")
@pytest.mark.parametrize("family,period", [("bank_lifts", 20), ("bank_lifts", 25), ("bank_lifts", 35),
                                           ("push_lifts", 16), ("push_lifts", 20), ("push_lifts", 25)])
def test_replay_lifts_beyond_the_hand_cooldown(family, period):
    assert replay_rate(family, period) <= 0.05


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


def test_freeze_needs_stop_then_resume_after_go():
    lc, _ = drive(pushups(secs=34.0, pauses=[(5.0, 20.0)]), 4.2, force=[FREEZE], stop_on_result=True)
    a = lc.attempts[0]
    assert a.confirm_t is not None and a.go_said and a.outcome == "no_resume"     # never resumed
    go = a.go_t
    go0, go1 = DEFAULT_THRESHOLDS["liveness_go_delay_s"]
    assert go0 <= go - a.confirm_t <= go1 + 0.11
    lc, log = drive(pushups(secs=34.0, pauses=[(5.0, go + 0.5 - 5.0)]), 4.2, force=[FREEZE], stop_on_result=True)
    assert statuses(log) == ["start", "go", "pass"] and log[1][2] == "challenge_go", log
    lc, _ = drive(pushups(secs=34.0, pauses=[(5.0, go - 0.6 - 5.0)]), 4.2, force=[FREEZE], stop_on_result=True)
    assert lc.attempts[0].outcome == "early"                                      # moved before the go cue
    lc, _ = drive(pushups(secs=34.0, pauses=[(5.0, go + 2.6 - 5.0)]), 4.2, force=[FREEZE], stop_on_result=True)
    assert lc.attempts[0].outcome == "no_resume"                                  # resumed too late
    _, log = drive(pushups(), 4.2, force=[FREEZE], stop_on_result=True)
    assert "pass" not in statuses(log)                                            # never stopped


def test_motions_do_not_cross_answer():
    for motions, cue in (([LIFT], DOUBLE_TAP), (DTAP, LIFT_HOLD), ([LIFT], FREEZE), (DTAP, FREEZE)):
        clip = plank(motions) if cue != FREEZE else pushups(pauses=[(4.6, 3.6)], hand_motions=motions)
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


def test_tracking_gap_during_hold_drops_the_lift():
    """Review P2: a gap mid-hold clears the attempt's lift; the hand is still up after it but never left the floor
    again, so the hold cannot pass from the pre-gap onset."""
    clip = plank([LIFT])
    clip.frames[:] = [f for f in clip.frames if not 5.6 <= f.t <= 6.2]
    lc, _ = drive(clip, 3.5, force=[LIFT_HOLD], stop_on_result=True)
    assert lc.attempts[0].passed_at is None
    lc, _ = drive(plank([LIFT]), 3.5, force=[LIFT_HOLD], stop_on_result=True)
    assert lc.attempts[0].passed_at is not None                       # same clip without the gap passes


def freeze_clip():
    """Push-ups, stop at 4.8 s, resume 0.5 s after the go cue of the forced FREEZE at 4.2 s (seed 0)."""
    lc, _ = drive(pushups(secs=34.0, pauses=[(4.8, 20.0)]), 4.2, force=[FREEZE], stop_on_result=True)
    a = lc.attempts[0]
    return a, pushups(secs=34.0, pauses=[(4.8, a.go_t + 0.5 - 4.8)])


def test_freeze_needs_continuous_single_person_after_confirm():
    a0, clip = freeze_clip()
    lc, _ = drive(clip, 4.2, force=[FREEZE], stop_on_result=True)
    assert lc.result == "pass"
    for mutate in ("leave", "two"):
        _, clip = freeze_clip()
        for f in clip.frames:
            if a0.confirm_t + 0.5 <= f.t <= a0.go_t - 0.3:
                if mutate == "leave":
                    f.img, f.persons = None, 0
                else:
                    f.persons = 2
        lc, log = drive(clip, 4.2, force=[FREEZE], stop_on_result=True)
        a = lc.attempts[0]
        assert a.passed_at is None and a.outcome == "lost" and statuses(log)[1] == "go", (mutate, log)
    _, clip = freeze_clip()
    clip.frames[:] = [f for f in clip.frames if not a0.confirm_t + 0.5 <= f.t <= a0.confirm_t + 1.0]
    lc, _ = drive(clip, 4.2, force=[FREEZE], stop_on_result=True)
    assert lc.attempts[0].outcome == "lost"


def test_freeze_without_visible_wrists_cannot_confirm():
    """Review P2: missing wrists are no evidence that the hands are down."""
    _, clip = freeze_clip()
    for f in clip.frames:
        if f.t >= 4.0:
            f.img[[15, 16], 0] = np.nan
    lc, _ = drive(clip, 4.2, force=[FREEZE], stop_on_result=True)
    a = lc.attempts[0]
    assert a.confirm_t is None and a.passed_at is None and a.outcome == "timeout"


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
    lc, log = drive(pushups(secs=20.0), 4.0, force=[LIFT_HOLD])
    assert statuses(log) == ["start", "retry", "fail"], log
    assert log[1][2] != log[0][2] and log[2][2] == "challenge_failed"
    a1, a2 = lc.attempts
    assert a1.outcome == "timeout" and 8.0 + 3.0 <= a2.start <= 8.0 + 4.5 + 0.11
    assert lc.windows() == [(a1.start, a1.deadline), (a2.start, a2.deadline)]
    assert lc.poll(99.0) == ("fail", None) and lc.finish(99.0) == "fail"


def test_freeze_exit_without_go_releases_then_retry_is_freeze_again():
    """Review P2: a FREEZE that ends before its go cue releases the person with the go cue; with the hand types ruled
    out (an earlier lift) the retry re-allows FREEZE instead of being impossible."""
    clip = pushups(secs=30.0, hand_motions=[("lift", "left", 1.0, 1.5)])
    lc, log = drive(clip, 6.0)
    a1 = lc.attempts[0]
    assert a1.cue == FREEZE and a1.outcome == "timeout" and a1.invalid is None      # a fair (non-void) attempt
    assert log[:3] == [(6.0, "start", FREEZE), (log[1][0], "go", "challenge_go"), (log[2][0], "retry", FREEZE)], log
    assert a1.confirm_by < log[1][0] <= a1.confirm_by + 0.11 and log[2][0] > log[1][0]
    assert lc.windows()[0] == (a1.start, a1.confirm_by)
    for kind, pauses in (("early", [(4.8, 6.0)]), ("camera", None)):
        clip = pushups(secs=30.0, pauses=pauses or [(4.8, 20.0)],
                       camera_shifts=[] if pauses else [(6.0, 0.5, 0.0, -0.2)])
        lc, log = drive(clip, 4.0, force=[FREEZE])
        assert lc.attempts[0].outcome == kind and statuses(log)[1] == "go", (kind, log)


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


def test_call_ending_before_fire_is_skipped_only_without_reps():
    lc = LivenessChallenge(random.Random(3))
    fire = lc.schedule(0.0)
    assert not lc.due(fire - 0.1)
    assert lc.finish(fire - 1.0) == "skipped" and lc.windows() == []
    with pytest.raises(RuntimeError):
        lc.start(fire)
    lc = LivenessChallenge(random.Random(3))
    fire = lc.schedule(0.0)
    lc.on_rep(1.0)                                       # a counted rep: it can never count without a pass
    assert lc.finish(fire - 1.0) == "fail" and lc.summary()["earned"] is True


def test_left_frame_before_any_rep_is_skipped():
    clip = pushups(secs=20.0)
    for f in clip.frames:
        f.img, f.persons = None, 0
    lc, log = drive(clip, 4.0)
    assert log == [] and lc.result == "skipped" and not lc.earned


def test_banked_reps_then_leaving_frame_fails():
    clip = pushups(secs=20.0)
    for f in clip.frames:
        if f.t >= 3.9:
            f.img, f.persons = None, 0
    lc, log = drive(clip, 4.0)
    assert statuses(log)[0] == "start" and lc.result == "fail" and lc.earned
    assert lc.summary()["attempts"][0]["seen"] is False


def still_after_reps(secs=60.0, motions=()):
    """Four push-ups (done by ~7.7 s), then the body stays still (plank hold) to `secs`."""
    return synth_pushups(n_reps=4, rep_s=1.8, lead_in_s=0.5, tail_s=secs - 7.7, hand_motions=list(motions),
                         noise=0.004, seed=5)


def test_banked_reps_then_holding_still_is_challenged_and_fails():
    """Review P1: a replay banks reps, then holds still - the challenge still fires (hand types work at rest)."""
    lc, log = drive(still_after_reps(), 20.0)
    assert [c for _, s_, c in log if s_ in ("start", "retry")] and lc.attempts[0].cue in (LIFT_HOLD, DOUBLE_TAP)
    assert lc.result == "fail" and all(a.cue != FREEZE for a in lc.attempts)
    # a hand lift puts the hand types in cooldown (FREEZE needs push-ups): the check is postponed, then cued
    lc, log = drive(still_after_reps(motions=[("lift", "left", 15.0, 1.5)]), 20.0)
    assert lc.postponed >= 1 and log[0][1] == "start" and log[0][0] >= 15.0 + 15.0 and lc.result == "fail"


def test_lifts_inside_the_cooldown_postpone_until_it_clears():
    lc, log = drive(still_after_reps(secs=90.0, motions=[("lift", "left", 12.0 * k, 1.5) for k in range(1, 8)]), 20.0)
    assert all(t >= 84.0 + 15.0 or t > 90 for t, *_ in log) and lc.result == "fail"     # lifts every 12 s: never cued
    assert lc.postponed >= 3 and not lc.attempts


def test_cooldown_clear_stretch_of_p1_seconds_always_gets_a_cue():
    """A lift at 19 s blocks the hand types until ~34 s; checks are <= liveness_postpone_s[1] = 30 s apart, so the
    clear stretch up to 64 s always gets one, at a random time (seed-dependent)."""
    clip = still_after_reps(secs=70.0, motions=[("lift", "left", 19.0, 1.5)])
    cues = []
    for seed in range(60):
        lc = LivenessChallenge(random.Random(seed), {"liveness_window_s": [0, 0]})
        lc.schedule(20.0)
        cues.append(next((f.t for f in clip.frames if (lc.on_frame(f), lc.due(f.t))[1]), None))
    assert all(c is not None and 34.0 <= c <= 64.0 for c in cues), cues
    assert max(cues) - min(cues) > 10.0


def test_honest_person_at_rest_answers_hand_challenge():
    for cue, motions in ((LIFT_HOLD, [("lift", "right", 20.8, 2.6)]),
                         (DOUBLE_TAP, [("lift", "left", 20.8, 0.9), ("lift", "left", 22.0, 0.9)])):
        _, log = drive(still_after_reps(motions=motions), 20.0, force=[cue])
        assert statuses(log) == ["start", "pass"], (cue, log)


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
        rt.update_challenge_window(*w)
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


def test_runtime_follows_the_shrinking_freeze_window():
    """Review P2: the FREEZE window registered at the cue (latest possible deadline) shrinks once the go cue is played;
    the runtime must use the current window, so a rep after the real end counts again."""
    a0, clip = freeze_clip()
    lc = LivenessChallenge(_ForcedRandom(0, [FREEZE]), NOW)
    lc.schedule(4.2)
    rt = JudgeRuntime()
    first = None
    for f in clip.frames:
        lc.on_frame(f)
        if lc.due(f.t):
            lc.start(f.t)
        elif lc.active:
            lc.poll(f.t)
        for w in lc.windows():
            rt.update_challenge_window(*w)
        first = first or (rt.windows[0] if rt.windows else None)
    a = lc.attempts[0]
    assert lc.result == "pass" and first[1] > a.deadline and rt.windows == [(a.start, a.deadline)]
    t_after = (a.deadline + first[1]) / 2
    assert not rt.in_challenge(t_after) and rt.in_challenge(a.deadline)
    rt.update_challenge_window(50.0, 51.0)
    assert rt.windows[-1] == (50.0, 51.0)
    with pytest.raises(ValueError):
        rt.update_challenge_window(50.0, 49.0)
