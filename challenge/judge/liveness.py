"""Anti-replay liveness challenge verified by pose (SPEC §6 Liveness, CONTRACTS C5, ruling D-20).

Once per call, at a random time in thr['liveness_window_s'] seconds after counting starts, the caller cues a random
challenge; the person has thr['liveness_timeout_s'] seconds to perform it. Pass -> continue. No pass -> ONE retry of
a DIFFERENT challenge type (the same type is allowed after a void attempt, which was never a fair try); no pass
again -> 'fail' (the caller voids the call's reps and plays challenge_failed).

Challenge types (D-20 A). Each is detectable in a side view without telling left from right, and they are mutually
exclusive, so one recorded motion cannot answer more than one of them:
  challenge_lift_hold   a hand leaves the floor and stays up (height > liveness_lift_h) for >= liveness_hold_s.
  challenge_double_tap  two separate lift-and-return cycles (floor -> up -> floor, either hand, not overlapping) whose
                        onsets are <= liveness_double_tap_gap_s apart, the second return inside the timeout.
  challenge_freeze      (D-29) "Freeze!" then "And go!". Stop: the body holds still for liveness_freeze_s (shoulder
                        and hip 0.5 s block means within liveness_freeze_still torso lengths, no hand off the floor,
                        every frame valid), the window starting >= liveness_min_react_s after the cue and ending
                        within liveness_timeout_s of it (else 'timeout'). Go: challenge_go is cued a fresh random
                        liveness_go_delay_s after the stop is confirmed (drawn from the rng per attempt, never from
                        the clock); the shoulder must stay within liveness_resume_min torso lengths of its mean over
                        the last 1 s of the stop until liveness_go_min_react_s after go (moving earlier -> 'early',
                        the attempt ends at once), then move beyond it (3-frame mean, 2 consecutive frames) within
                        liveness_go_react_s of go (else 'no_resume').
The legacy tap/lift-right cue keys stay in cues.CUES but are not drawn: left/right cannot be told apart reliably in
a side view (mirror / occlusion), which made one tap answer every cue (review P1).

Selection (at each check time; a type is eligible only if a replay cannot have learned to answer it):
  nothing     unless push-ups are in progress (3-frame-median shoulder height range >= liveness_freeze_motion_min in
              the liveness_quiet_s before the check): the challenge guards reps, and a video that is not producing
              reps gains nothing; a still plank / static replay is never challenged (and never gets FREEZE).
  FREEZE      whenever push-ups are in progress (continuous push-ups never pass it).
  LIFT_HOLD, DOUBLE_TAP  only if no hand lift was seen since counting started (an unprompted lift, or one inside a
              failed attempt): a video that lifts hands, periodically or not, never gets a hand challenge.
  If nothing is eligible the check moves to a fresh random time liveness_postpone_s later (first cue: fire_t moves;
  retry: the retry check moves). Eligibility never flips at a predictable moment (no expiring look-back), so a replay
  cannot use the postponement to time its motion. A first cue postponed past the end of the call -> 'skipped' (the
  call ended before the - postponed - fire_t); a retry postponed past the end -> 'fail' (the person was seen).
Known residual (D-30, accepted; tests: strict xfail): a replay of push-ups with long pauses (period-3 s pause,
3 s of push-ups) still answers FREEZE+go when a pause both starts right after "Freeze!" and ends just after the
random go cue: measured 5.5 % (period 9) and 7 % (period 10) with go delay 2-8 s (period 6: 0 %, 8: 2 %).
Mitigated by admin re-judge of top finishers.
Driving (judge frame clock, seconds; worker wiring is task 30):
    lc = LivenessChallenge(random.Random(seed), thr); fire_t = lc.schedule(call_t0)
    every counted frame: lc.on_frame(f); if lc.due(t): say(lc.start(t)) elif lc.active: st, cue = lc.poll(t); say(cue)
    lc.windows()[-1] -> (cue, deadline) of a new attempt for JudgeRuntime.set_challenge_window;
    lc.finish(t_end) at call end; lc.summary() -> result, unprompted_lifts, suspicious, postponed, attempts.
poll(t) -> (status, cue_key|None): 'pending' while an attempt (or the gap before the retry) is open; 'go' with challenge_go when a
FREEZE attempt reaches its go time (also on a void attempt, so an honest person is never left frozen); 'retry' with the
retry's cue key when the retry starts, a random liveness_retry_delay_s after the first attempt's deadline (time for an
honest late responder to lower the hand; random so a replay cannot time it) or later if postponed; 'pass'
(challenge_passed); 'fail' (challenge_failed); 'skipped' (None). Terminal statuses carry their cue once, later polls return (result, None).
An attempt times out only when t > deadline (start + timeout; FREEZE: confirm_by = start + timeout for the stop, then
go time + liveness_go_react_s); frames after the deadline never count. Attempt outcomes: pass | timeout | quiet |
camera | early | no_resume | ended.

Attempt validity (an invalid attempt cannot pass; at its deadline it becomes the retry, or 'fail' if it was the retry):
  quiet (D-20 B)   a hand was off the floor (tracked wrist height > liveness_floor_leave in 2 consecutive frames, or a
                   hand in the 'up' state) at any time in the liveness_quiet_s before the cue.
  camera (D-20 E)  the body anchor (mean tracked ankle position, 3-frame mean) moved more than liveness_cam_shift
                   torso lengths from its position at the cue in 2 consecutive frames (the ankles rest on the floor
                   through push-ups and hand lifts; a moved phone or filmed screen moves them).
Response onset (D-20 B): a counted lift needs a floor -> up transition observed after the cue: the hand was seen in
the 'floor' state in a frame at/after the cue, and the first frame of its 'up' run is >= liveness_min_react_s after
the cue (no lookback; a hand already up, or rising at the cue, must come down first).

Hand state (per anatomical hand; either hand counts): heights are perpendicular distances above the floor line in
torso lengths, the line translated by the current anchor offset (so a small camera drift does not fake a lift).
'floor' when height < liveness_floor_leave (landmark position at any confidence: an occluded far hand resting on the
floor is placed there by the pose model), 'up' when height > liveness_lift_h with the wrist tracked (conf >= min_conf).
A state change needs 2 consecutive frames (D-16); heights in between keep the state (hysteresis). Frames (D-20 F):
a frame is valid with exactly one person, landmarks, a baseline and a tracked ankle; an invalid frame resets the
consecutive-evidence counters, and a timestamp gap > liveness_max_gap_s (or a hand unusable for that long) also
resets the hand to 'unknown' (unknown -> up is never a transition). Non-increasing timestamps are ignored.

Baseline (learned outside challenge windows on one-person plank frames: a side with tracked shoulder, hip and ankle
within 35 deg of horizontal): EMAs (alpha 0.1) of torso_len (|shoulder - hip|), the floor wrist point (tracked wrists
on the floor) and the floor ankle point. No baseline -> nothing can be verified.

Presence (D-20 D): a frame shows the person when persons >= 1 and a shoulder or hip is tracked, independent of the
wrists. result: 'pass'; 'skipped' only when the call ended before the first cue (before fire_t, possibly postponed) or
nobody was in frame in any frame of the attempts; otherwise 'fail' (present but unverifiable - wrists hidden, no
ankle, no baseline - is a fail, and so is ending the call during an open challenge or a pending retry without a pass).

Unprompted motion (D-20 C): floor -> up transitions whose onset is outside every attempt window [cue, deadline] are
counted as unprompted_lifts; suspicious = >= 3 such lifts whose onset intervals have a
coefficient of variation < liveness_periodic_cv (a periodic, replay-like pattern). Reported in summary() only - the
flag alone never fails the call.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from challenge.judge.gates import merged_thresholds
from challenge.judge.metrics import FrameObs

LIFT_HOLD, DOUBLE_TAP, FREEZE = "challenge_lift_hold", "challenge_double_tap", "challenge_freeze"
CHALLENGES = (LIFT_HOLD, DOUBLE_TAP, FREEZE)
GO_CUE = "challenge_go"
KP = {"left": dict(sh=11, wr=15, hp=23, an=27), "right": dict(sh=12, wr=16, hp=24, an=28)}
EVIDENCE_FRAMES = 2
PLANK_MAX_TILT_DEG = 35.0
EMA_ALPHA = 0.1
FREEZE_BLOCKS = 5
HISTORY_S = 8.0
REF_S = 1.0
_EPS = 1e-9
_RESULT_CUE = {"pass": "challenge_passed", "fail": "challenge_failed", "skipped": None}


class _Ema:
    __slots__ = ("v",)

    def __init__(self) -> None:
        self.v = None

    def add(self, x):
        self.v = x if self.v is None else self.v + EMA_ALPHA * (x - self.v)


@dataclass
class _Hand:
    state: str = "unknown"            # unknown | floor | up
    cand: str | None = None
    cand_n: int = 0
    cand_t0: float = 0.0
    last_valid_t: float | None = None
    off_run: int = 0
    last_off_t: float | None = None
    onset_t: float | None = None      # start of the current 'up' run

    def reset_counters(self) -> None:
        self.cand, self.cand_n, self.off_run = None, 0, 0


@dataclass
class _Attempt:
    cue: str
    start: float
    deadline: float
    invalid: str | None = None        # 'quiet' | 'camera'
    seen: bool = False
    passed_at: float | None = None
    end: float | None = None
    outcome: str | None = None        # pass | timeout | quiet | camera | early | no_resume | ended
    confirm_by: float = 0.0           # FREEZE: stillness must be confirmed by then (start + timeout)
    go_delay: float = 0.0             # FREEZE: go cue this long after the stillness is confirmed (drawn at open)
    confirm_t: float | None = None
    go_t: float | None = None         # planned, then actual (when poll returned 'go') go-cue time
    go_said: bool = False
    ref: np.ndarray | None = None     # frozen shoulder position (camera-compensated)
    resume_run: int = 0
    anchor0: np.ndarray | None = None
    cam_run: int = 0
    floor_obs: dict = field(default_factory=lambda: {"left": False, "right": False})
    up_onset: dict = field(default_factory=lambda: {"left": None, "right": None})
    cycles: list = field(default_factory=list)       # (onset, return) of completed lift-and-return cycles


@dataclass
class _Hist:
    t: float
    valid: bool
    sh: np.ndarray | None
    hp: np.ndarray | None
    sh_h: float | None
    hands_down: bool


class LivenessChallenge:
    def __init__(self, rng: random.Random, thr: dict | None = None):
        self.rng = rng
        self.thr = t = merged_thresholds(thr)
        self.w0, self.w1 = (float(x) for x in t["liveness_window_s"])
        if not (math.isfinite(self.w0) and math.isfinite(self.w1)) or self.w1 < self.w0:
            raise ValueError(f"bad liveness_window_s: {t['liveness_window_s']!r}")
        self.timeout = float(t["liveness_timeout_s"])
        self.hold_s = float(t["liveness_hold_s"])
        self.freeze_s = float(t["liveness_freeze_s"])
        self.min_react = float(t["liveness_min_react_s"])
        if not self.timeout > 0:
            raise ValueError(f"liveness_timeout_s must be > 0, got {self.timeout!r}")
        if self.min_react + max(self.hold_s, self.freeze_s) > self.timeout:
            raise ValueError("liveness_min_react_s + hold/freeze time exceeds liveness_timeout_s")
        self.r0, self.r1 = (float(x) for x in t["liveness_retry_delay_s"])
        if not 0 <= self.r0 <= self.r1:
            raise ValueError(f"bad liveness_retry_delay_s: {t['liveness_retry_delay_s']!r}")
        self.min_conf = float(t["min_conf"])
        self.lift_h = float(t["liveness_lift_h"])
        self.floor_leave = float(t["liveness_floor_leave"])
        if not 0 < self.floor_leave < self.lift_h:
            raise ValueError("need 0 < liveness_floor_leave < liveness_lift_h")
        self.quiet_s = float(t["liveness_quiet_s"])
        self.tap_gap = float(t["liveness_double_tap_gap_s"])
        self.still = float(t["liveness_freeze_still"])
        self.motion_min = float(t["liveness_freeze_motion_min"])
        self.cam_shift = float(t["liveness_cam_shift"])
        self.max_gap = float(t["liveness_max_gap_s"])
        self.periodic_cv = float(t["liveness_periodic_cv"])
        self.fire_t: float | None = None
        self.attempts: list[_Attempt] = []
        self.result: str | None = None
        self.result_t: float | None = None
        self._announced = False
        self._retry_at: float | None = None
        self._torso, self._floor_w, self._floor_a = _Ema(), _Ema(), _Ema()
        self._hands = {"left": _Hand(), "right": _Hand()}
        self._anchors: deque = deque(maxlen=3)
        self._hist: deque[_Hist] = deque()
        self._last_t: float | None = None
        self._lifts: list[float] = []         # unprompted lift onsets (outside attempt windows)
        self._all_lifts: list[float] = []     # every observed lift onset
        self.postponed = 0                    # checks at which no challenge type was eligible
        self.go0, self.go1 = (float(x) for x in t["liveness_go_delay_s"])
        if not 0 < self.go0 <= self.go1:
            raise ValueError(f"bad liveness_go_delay_s: {t['liveness_go_delay_s']!r}")
        self.go_react = float(t["liveness_go_react_s"])
        self.go_min_react = float(t["liveness_go_min_react_s"])
        self.resume_min = float(t["liveness_resume_min"])
        if not 0 <= self.go_min_react < self.go_react:
            raise ValueError("need 0 <= liveness_go_min_react_s < liveness_go_react_s")
        self.p0, self.p1 = (float(x) for x in t["liveness_postpone_s"])
        if not 0 < self.p0 <= self.p1:
            raise ValueError(f"bad liveness_postpone_s: {t['liveness_postpone_s']!r}")

    # ------------------------------------------------------------------ public state
    def schedule(self, call_t0: float) -> float:
        if self.fire_t is not None:
            raise RuntimeError("liveness challenge already scheduled")
        self.fire_t = float(call_t0) + self.rng.uniform(self.w0, self.w1)
        return self.fire_t

    def due(self, t: float) -> bool:
        """True when the first cue should be played now. Past fire_t with no eligible challenge type (see
        _eligible) the cue is postponed by a random liveness_postpone_s instead (fire_t moves; returns False)."""
        if self.fire_t is None or self.attempts or self.result is not None or t < self.fire_t:
            return False
        if self._eligible(t, None):
            return True
        self.postponed += 1
        self.fire_t = t + self.rng.uniform(self.p0, self.p1)
        return False

    @property
    def started(self) -> bool:
        return bool(self.attempts)

    @property
    def active(self) -> bool:
        return bool(self.attempts) and self.result is None

    @property
    def unprompted_lifts(self) -> int:
        return len(self._lifts)

    @property
    def suspicious(self) -> bool:
        if len(self._lifts) < 3:
            return False
        iv = np.diff(np.asarray(self._lifts, dtype=float))
        m = float(iv.mean())
        return m > _EPS and float(iv.std()) / m < self.periodic_cv

    def summary(self) -> dict:
        return dict(result=self.result, unprompted_lifts=self.unprompted_lifts, suspicious=self.suspicious,
                    fire_t=self.fire_t, postponed=self.postponed,
                    attempts=[dict(cue=a.cue, start=a.start, end=a.end, outcome=a.outcome, seen=a.seen, go_t=a.go_t)
                              for a in self.attempts])

    def windows(self) -> list[tuple[float, float]]:
        """(cue time, deadline) of every attempt so far, known when the attempt starts: pass each new one to
        JudgeRuntime.set_challenge_window (reps fired inside neither count nor are penalised)."""
        return [(a.start, a.deadline) for a in self.attempts]

    # ------------------------------------------------------------------ challenge flow
    def start(self, t: float) -> str:
        """Open the first attempt (call when due(t)); returns the cue key to play."""
        if self.attempts or self.result is not None:
            raise RuntimeError("liveness challenge already started or finished")
        types = self._eligible(float(t), None)
        if not types:
            raise RuntimeError("no eligible challenge type now: start only when due(t)")
        return self._open(float(t), types)

    def _eligible(self, t: float, exclude: str | None) -> list[str]:
        """Challenge types that a replay cannot answer by luck at time t (D-20 + selection rule, module docstring):
        Nothing unless push-ups are in progress; then FREEZE, plus the hand types if no hand lift was seen since
        counting started (unprompted, or in a failed attempt). Minus `exclude` (the retry is a different type)."""
        if not self._moving_before(t):
            return []
        types = [FREEZE]
        if not any(x <= t for x in self._all_lifts):
            types = [LIFT_HOLD, DOUBLE_TAP] + types
        return [c for c in types if c != exclude]

    def _open(self, t: float, types: list[str]) -> str:
        cue = self.rng.choice(types)
        a = _Attempt(cue=cue, start=t, deadline=t + self.timeout, confirm_by=t + self.timeout)
        if cue == FREEZE:
            a.go_delay = self.rng.uniform(self.go0, self.go1)
            a.deadline = t + self.timeout + self.go1 + self.go_react      # latest possible end, until the go cue
        if any(h.state == "up" or (h.last_off_t is not None and h.last_off_t >= t - self.quiet_s)
               for h in self._hands.values()):
            a.invalid = "quiet"
        if self._anchors:
            a.anchor0 = np.mean([p for _, p in self._anchors], axis=0)
        self.attempts.append(a)
        return cue

    def _resolve(self, result: str, t: float, announce: bool) -> tuple[str, str | None]:
        self.result, self.result_t = result, t
        self._retry_at = None
        a = self.attempts[-1] if self.attempts else None
        if a is not None and a.end is None:
            a.end = t
            a.outcome = a.outcome or ("pass" if result == "pass" else "ended")
        self._announced = True
        return result, (_RESULT_CUE[result] if announce else None)

    def poll(self, t: float) -> tuple[str, str | None]:
        t = float(t)
        if not self.attempts and self.result is None:
            raise RuntimeError("liveness challenge not started")
        if self.result is not None:
            if self._announced:
                return self.result, None
            return self._resolve(self.result, self.result_t, True)
        if self._retry_at is not None:
            if t < self._retry_at:
                return "pending", None
            a1 = self.attempts[0]
            types = self._eligible(t, None if a1.invalid else a1.cue)   # a void attempt was never a fair try
            if not types:
                self.postponed += 1
                self._retry_at = t + self.rng.uniform(self.p0, self.p1)
                return "pending", None
            self._retry_at = None
            return "retry", self._open(t, types)
        a = self.attempts[-1]
        if a.passed_at is not None:
            a.outcome, a.end = "pass", a.passed_at
            return self._resolve("pass", t, True)
        if a.cue == FREEZE and a.invalid in (None, "quiet"):
            if a.confirm_t is None and t > a.confirm_by:
                return self._attempt_over(a, a.confirm_by, "timeout", t)
            if a.go_t is not None and not a.go_said and t >= a.go_t:
                a.go_said, a.go_t = True, t                   # the go cue is played now
                a.deadline = t + self.go_react
                return "go", GO_CUE
        if a.invalid == "early":
            return self._attempt_over(a, t, "early", t)
        if t <= a.deadline:
            return "pending", None
        miss = "no_resume" if a.go_said else "timeout"
        return self._attempt_over(a, a.deadline, a.invalid or miss, t)

    def _attempt_over(self, a: _Attempt, end: float, outcome: str, t: float) -> tuple[str, str | None]:
        a.end, a.outcome, a.deadline = end, outcome, min(a.deadline, max(end, a.start))
        if len(self.attempts) == 1:
            self._retry_at = end + self.rng.uniform(self.r0, self.r1)
            return "pending", None
        return self._resolve(self._no_pass_result(), t, True)

    def _no_pass_result(self) -> str:
        return "fail" if any(x.seen for x in self.attempts) else "skipped"

    def finish(self, t_end: float) -> str:
        """Call ended at t_end: settle and return the final result (module docstring). No cue is due."""
        if self.result is not None:
            return self.result
        if not self.attempts:
            self.result, self.result_t, self._announced = "skipped", float(t_end), True
            return self.result
        a = self.attempts[-1]
        if a.passed_at is not None and self._retry_at is None:
            a.outcome, a.end = "pass", a.passed_at
            return self._resolve("pass", float(t_end), False)[0]
        return self._resolve(self._no_pass_result(), float(t_end), False)[0]

    # ------------------------------------------------------------------ frames
    def on_frame(self, f: FrameObs) -> None:
        t = float(f.t)
        if not math.isfinite(t) or (self._last_t is not None and t <= self._last_t):
            return
        if self._last_t is not None and t - self._last_t > self.max_gap:
            for h in self._hands.values():
                h.reset_counters()
                h.state = "unknown"
            self._anchors.clear()
        self._last_t = t
        a = self._open_attempt(t)
        P, raw, aspect, persons = self._parse(f)
        present = persons >= 1 and any((s, k) in P for s in KP for k in ("sh", "hp"))
        if present and a is not None:
            a.seen = True
        one = persons == 1 and raw is not None
        ankles = [P[(s, "an")] for s in KP if (s, "an") in P]
        if one and ankles:
            self._anchors.append((t, np.mean(ankles, axis=0)))
        if not self.active and one:
            self._learn(P)
        valid = one and bool(ankles) and self._baseline_ok()
        off = self._offset() if valid else None
        hands_down = True
        for name, h in self._hands.items():
            if h.last_valid_t is not None and t - h.last_valid_t > self.max_gap and h.state != "unknown":
                h.state = "unknown"
                h.reset_counters()
            if not valid or raw[name] is None:
                h.reset_counters()
                continue
            hh = self._height(raw[name], off)
            tracked = (name, "wr") in P
            if tracked and hh > self.floor_leave:
                hands_down = False
            self._update_hand(name, h, hh, tracked, t, a)
            if h.state == "up":
                hands_down = False
        sh, hp = self._torso_points(P)
        sh_h = self._height(sh, off) if (valid and sh is not None) else None
        self._hist.append(_Hist(t, valid and sh is not None and hp is not None,
                                None if sh is None or off is None else sh - off,
                                None if hp is None or off is None else hp - off, sh_h, hands_down))
        while self._hist and self._hist[0].t < t - HISTORY_S:
            self._hist.popleft()
        # a void ('quiet') attempt still plays out exactly like a valid one (FREEZE: confirm, go cue), so the person
        # cannot tell it is void and is not left frozen; it just cannot pass
        if a is None or a.passed_at is not None or a.invalid not in (None, "quiet"):
            return
        if not valid:
            a.cam_run = 0
            return
        anchor = np.mean([p for _, p in self._anchors], axis=0)
        if a.anchor0 is None:
            a.anchor0 = anchor
        if float(np.linalg.norm(anchor - a.anchor0)) / self._torso.v > self.cam_shift:
            a.cam_run += 1
            if a.cam_run >= EVIDENCE_FRAMES:
                a.invalid = "camera"
                return
        else:
            a.cam_run = 0
        if self._satisfied(a, t) and a.invalid is None:
            a.passed_at = t

    def _open_attempt(self, t: float) -> _Attempt | None:
        if self.result is not None or not self.attempts or self._retry_at is not None:
            return None
        a = self.attempts[-1]
        return a if a.start <= t <= a.deadline else None

    def _parse(self, f: FrameObs):
        persons = int(f.persons) if f.persons is not None else 0
        if f.img is None:
            return {}, None, 16 / 9, persons
        img = np.asarray(f.img, dtype=float)
        if img.ndim != 2 or img.shape[0] < 33 or img.shape[1] < 4:
            return {}, None, 16 / 9, persons
        aspect = float(getattr(f, "aspect", 16 / 9) or 16 / 9)
        P, raw = {}, {}
        for side, kp in KP.items():
            for name, idx in kp.items():
                x, y = float(img[idx, 0]), float(img[idx, 1])
                inside = math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1
                c = float(img[idx, 3])
                if img.shape[1] >= 5:
                    c = min(c, float(img[idx, 4]))
                pt = np.array([x * aspect, y])
                if inside and math.isfinite(c) and c >= self.min_conf:
                    P[(side, name)] = pt
                if name == "wr":
                    raw[side] = pt if inside else None
        return P, raw, aspect, persons

    def _update_hand(self, name: str, h: _Hand, hh: float, tracked: bool, t: float, a: _Attempt | None) -> None:
        h.last_valid_t = t
        if tracked and hh > self.floor_leave:
            h.off_run += 1
            if h.off_run >= EVIDENCE_FRAMES:
                h.last_off_t = t
        else:
            h.off_run = 0
        cond = "floor" if hh < self.floor_leave else ("up" if hh > self.lift_h and tracked else None)
        if cond is None or cond == h.state:
            h.cand, h.cand_n = None, 0
        elif cond == h.cand:
            h.cand_n += 1
        else:
            h.cand, h.cand_n, h.cand_t0 = cond, 1, t
        if h.cand is not None and h.cand_n >= EVIDENCE_FRAMES:
            prev, h.state, onset = h.state, h.cand, h.cand_t0
            h.cand, h.cand_n = None, 0
            if prev == "floor" and h.state == "up":
                h.onset_t = onset
                self._all_lifts.append(onset)
                if a is not None and onset >= a.start:
                    if a.floor_obs[name] and onset >= a.start + self.min_react:
                        a.up_onset[name] = onset
                elif not any(x.start <= onset <= x.deadline for x in self.attempts):
                    self._lifts.append(onset)
            elif h.state == "floor" and a is not None and a.up_onset[name] is not None:
                a.cycles.append((a.up_onset[name], onset))
                a.up_onset[name] = None
            if h.state != "up":
                h.onset_t = None
                if a is not None:
                    a.up_onset[name] = None
        if h.state == "up":
            h.last_off_t = t
        if a is not None and h.state == "floor" and t >= a.start:
            a.floor_obs[name] = True

    def _satisfied(self, a: _Attempt, t: float) -> bool:
        if a.cue == LIFT_HOLD:
            return any(on is not None and self._hands[n].state == "up" and t - on >= self.hold_s - 1e-9
                       for n, on in a.up_onset.items())
        if a.cue == DOUBLE_TAP:
            cyc = sorted(a.cycles)
            return any(c2[0] >= c1[1] and c2[0] - c1[0] <= self.tap_gap + 1e-9
                       for i, c1 in enumerate(cyc) for c2 in cyc[i + 1:])
        return self._freeze_step(a, t)

    def _freeze_step(self, a: _Attempt, t: float) -> bool:
        """FREEZE (D-29): still window confirmed by confirm_by -> still until the go cue (+ go_min_react) -> the
        shoulder moves away from its frozen position within liveness_go_react_s of the go cue."""
        if a.confirm_t is None:
            if t <= a.confirm_by and self._still_window(a, t):
                a.confirm_t, a.go_t = t, t + a.go_delay
                # frozen reference: the last REF_S of the confirmed window (its start may still hold the stop's tail)
                pts = [e.sh for e in self._hist if e.t >= t - REF_S - 1e-9 and e.sh is not None]
                a.ref = np.mean(pts, axis=0)
            return False
        last = [e for e in list(self._hist)[-3:] if e.valid and e.sh is not None]
        if len(last) < 3 or any(b.t - x.t > self.max_gap for x, b in zip(last, last[1:])):
            a.resume_run = 0
            return False
        d = float(np.linalg.norm(np.mean([e.sh for e in last], axis=0) - a.ref)) / self._torso.v
        if not a.go_said or t < a.go_t + self.go_min_react:
            if d > self.resume_min:
                a.invalid = "early"                            # moved before (or too soon after) the go cue
            return False
        if t > a.go_t + self.go_react:
            return False
        a.resume_run = a.resume_run + 1 if d > self.resume_min else 0
        return a.resume_run >= EVIDENCE_FRAMES

    def _still_window(self, a: _Attempt, t: float) -> bool:
        w0 = t - self.freeze_s
        if w0 < a.start + self.min_react - 1e-9 or t > a.confirm_by + 1e-9:
            return False
        win = [e for e in self._hist if e.t >= w0 - 1e-9]
        if not win or win[0].t > w0 + self.max_gap:
            return False
        if any(not e.valid or not e.hands_down for e in win):
            return False
        if any(b.t - x.t > self.max_gap for x, b in zip(win, win[1:])):
            return False
        blocks: list[list[_Hist]] = [[] for _ in range(FREEZE_BLOCKS)]
        for e in win:
            blocks[min(FREEZE_BLOCKS - 1, int((e.t - w0) / self.freeze_s * FREEZE_BLOCKS))].append(e)
        if any(not b for b in blocks):
            return False
        tl = self._torso.v
        for key in ("sh", "hp"):
            means = [np.mean([getattr(e, key) for e in b], axis=0) for b in blocks]
            spread = max(float(np.linalg.norm(m1 - m2)) for i, m1 in enumerate(means) for m2 in means[i + 1:])
            if spread / tl >= self.still:
                return False
        return True

    def _moving_before(self, t: float) -> bool:
        hs = [e.sh_h for e in self._hist if e.t >= t - self.quiet_s and e.valid and e.sh_h is not None]
        if len(hs) < 5:
            return False
        med = [float(np.median(hs[max(0, i - 1):i + 2])) for i in range(len(hs))]
        return max(med) - min(med) >= self.motion_min

    # ------------------------------------------------------------------ geometry
    def _torso_points(self, P: dict):
        best = None
        for s in KP:
            if (s, "sh") in P and (s, "hp") in P:
                return P[(s, "sh")], P[(s, "hp")]
            if best is None and (s, "sh") in P:
                best = (P[(s, "sh")], None)
        return best if best is not None else (None, None)

    def _baseline_ok(self) -> bool:
        return self._torso.v is not None and self._torso.v > _EPS and self._floor_w.v is not None \
            and self._floor_a.v is not None

    def _offset(self) -> np.ndarray:
        return np.mean([p for _, p in self._anchors], axis=0) - self._floor_a.v

    def _learn(self, P: dict) -> None:
        plank, torsos, ankles = False, [], []
        for s in KP:
            if (s, "sh") in P and (s, "hp") in P:
                d = float(np.linalg.norm(P[(s, "sh")] - P[(s, "hp")]))
                if d > _EPS:
                    torsos.append(d)
            if (s, "an") in P:
                ankles.append(P[(s, "an")])
            if all((s, k) in P for k in ("sh", "hp", "an")):
                v = P[(s, "sh")] - P[(s, "an")]
                if float(np.linalg.norm(v)) > _EPS:
                    plank = plank or math.degrees(math.atan2(abs(v[1]), abs(v[0]))) <= PLANK_MAX_TILT_DEG
        if not plank or not torsos or not ankles:
            return
        self._torso.add(float(np.mean(torsos)))
        wrists = []
        if self._baseline_ok() and self._anchors:
            off = self._offset()                 # judge wrists against the line where the ankles are now
            wrists = [P[(s, "wr")] - off for s in KP if (s, "wr") in P
                      and self._height(P[(s, "wr")], off) < self.floor_leave]
            ankle = np.mean(ankles, axis=0) - off
            self._floor_a.add(ankle)
            if wrists:
                self._floor_w.add(np.mean(wrists, axis=0))
        else:
            self._floor_a.add(np.mean(ankles, axis=0))
            wr = [P[(s, "wr")] for s in KP if (s, "wr") in P]
            if wr:
                self._floor_w.add(np.mean(wr, axis=0))

    def _height(self, w: np.ndarray, off: np.ndarray) -> float:
        """Height of w above the floor line (translated by off) in torso lengths, + up."""
        fw, fa, tl = self._floor_w.v + off, self._floor_a.v + off, self._torso.v
        d = fa - fw
        n = float(np.linalg.norm(d))
        if n <= _EPS:
            return float(fw[1] - w[1]) / tl
        u = d / n
        nv = np.array([-u[1], u[0]])
        if nv[1] > 0:
            nv = -nv                           # normal pointing up the image (away from the floor)
        return float((w - fw) @ nv) / tl
