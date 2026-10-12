"""Anti-replay liveness challenge verified by pose (SPEC §6 Liveness, CONTRACTS C5).

Once per call, at a random time in thr['liveness_window_s'] seconds after the call's counting start, the caller cues a
random challenge ("Tap your left shoulder" / "Tap your right shoulder" / "Lift your right hand"); the person has
thr['liveness_timeout_s'] seconds to perform it. Pass -> continue. No pass -> ONE retry with a DIFFERENT challenge;
no pass again -> 'fail' (the caller voids the call's reps and plays challenge_failed). A replayed video ignores the cue.

Driving (all times on the judge frame clock, seconds; the worker wiring is task 30):

    lc = LivenessChallenge(random.Random(seed), thr)
    fire_t = lc.schedule(call_t0)               # uniform in [call_t0 + w0, call_t0 + w1]
    every frame:  lc.on_frame(f)                # always (also before the challenge: it learns the plank floor)
                  if not lc.started and lc.due(t): say(lc.start(t))
                  elif lc.active: status, cue = lc.poll(t); say(cue) if cue
    lc.window()  -> (t0, t1) for JudgeRuntime.set_challenge_window (reps in it neither count nor are penalised)
    lc.finish(t_end) at call end -> final result

poll(t) -> (status, cue_key|None): 'pending' (None) while the current attempt is open; 'pass' (challenge_passed) once
the motion was detected in a frame inside the attempt; 'retry' (the new challenge's cue key; the retry attempt starts
at t) when the first attempt's deadline passed without it; 'fail' (challenge_failed) when the retry's deadline passed;
'skipped' (None) when the retry's deadline passed and the person was not in frame in ANY frame of either attempt.
Each terminal status is returned once with its cue; later polls return (result, None). Call poll after on_frame of
the frame with the same clock: an attempt times out only when t > its deadline (start + liveness_timeout_s), and
frames after the deadline never count, so motion performed late cannot pass that attempt.

result in {'pass', 'fail', 'skipped'} (None while undecided):
  skipped  the call ended before fire_t (or start() was never called), or the person was not in frame for the whole
           challenge (no frame of either attempt had a person with a confident shoulder + wrist): there is no evidence
           either way, so the reps are not voided.
  fail     the person was seen and did not perform the commanded motion within the timeout twice, OR the call ended
           during an attempt without a pass (hanging up on the cue cannot dodge the challenge; schedule so that
           fire_t + 2 * timeout is before the count ends).

Detection (side view; geometry in height units P = (x * aspect, y), y down, like metrics.py; conf = min(visibility,
presence), 0 outside the image; a keypoint is tracked when conf >= thr['min_conf']):
  baseline  outside attempts, on plank frames (one person; a side with tracked shoulder, hip and ankle whose
            shoulder->ankle direction is within 35 deg of horizontal), exponential moving averages (alpha 0.1) of:
            torso_len = mean tracked |shoulder - hip|; floor wrist point = mean of the tracked wrists that are on the
            floor (height < floor_leave once a floor exists); floor ankle point = mean tracked ankle. The floor line
            runs through the two points (horizontal through the wrist point when no ankle was seen). Frozen during
            attempts. No baseline -> nothing can be detected (the attempt times out).
  height    of a wrist = perpendicular distance above the floor line / torso_len.
  armed     a hand counts only if its wrist was seen ON the floor (height < liveness_floor_leave; landmark position at
            any confidence, one-person frames) at some frame at or after start - ARM_LOOKBACK_S: the motion must
            leave the floor (a hand already up is not a response).
  tap       a wrist with height > liveness_floor_leave within liveness_tap_dist * torso_len of the target shoulder.
  lift      a wrist with height > liveness_lift_h ("rises above its plank floor position").
  evidence  the condition holds for the same hand in EVIDENCE_FRAMES consecutive one-person frames inside the attempt
            (D-16: no single frame decides), so a 1-frame landmark spike cannot pass.
  hands     camera mirror / side ambiguity: in a side view the far arm is usually occluded and left/right labels are
            only trustworthy when MediaPipe tracks BOTH wrists separately. If both wrists are tracked in a frame the
            commanded hand is distinguishable by visibility and only it counts (tap: the right hand to the LEFT
            shoulder for challenge_tap_left, the left hand to the right shoulder for challenge_tap_right; the target
            is the commanded shoulder when tracked, else either tracked shoulder; lift: the right hand). Otherwise any
            tracked wrist counts (tap target: either tracked shoulder). Frames must be un-mirrored (FaceTime sends the
            remote camera unmirrored; a mirrored source swaps the labels in the strict case).
Push-ups never pass on their own: in a push-up the wrists stay on the floor (height ~ 0), and only frames inside an
attempt are examined, so natural motion outside the challenge window is ignored.
"""
from __future__ import annotations

import math
import random

import numpy as np

from challenge.judge.gates import merged_thresholds
from challenge.judge.metrics import FrameObs

CHALLENGES = ("challenge_tap_left", "challenge_tap_right", "challenge_lift_right")
# cue -> (kind, commanded hand, target shoulder for a tap)
_SPEC = {"challenge_tap_left": ("tap", "right", "left"), "challenge_tap_right": ("tap", "left", "right"),
         "challenge_lift_right": ("lift", "right", None)}
KP = {"left": dict(sh=11, wr=15, hp=23, an=27), "right": dict(sh=12, wr=16, hp=24, an=28)}
EVIDENCE_FRAMES = 2
ARM_LOOKBACK_S = 1.0
PLANK_MAX_TILT_DEG = 35.0
EMA_ALPHA = 0.1
_EPS = 1e-9


class _Ema:
    __slots__ = ("v",)

    def __init__(self) -> None:
        self.v = None

    def add(self, x):
        self.v = x if self.v is None else self.v + EMA_ALPHA * (x - self.v)


class LivenessChallenge:
    def __init__(self, rng: random.Random, thr: dict | None = None):
        self.rng = rng
        self.thr = merged_thresholds(thr)
        w = self.thr["liveness_window_s"]
        self.w0, self.w1 = float(w[0]), float(w[1])
        if not (math.isfinite(self.w0) and math.isfinite(self.w1)) or self.w1 < self.w0:
            raise ValueError(f"bad liveness_window_s: {w!r}")
        self.timeout = float(self.thr["liveness_timeout_s"])
        if not self.timeout > 0:
            raise ValueError(f"liveness_timeout_s must be > 0, got {self.timeout!r}")
        self.min_conf = float(self.thr["min_conf"])
        self.tap_dist = float(self.thr["liveness_tap_dist"])
        self.lift_h = float(self.thr["liveness_lift_h"])
        self.floor_leave = float(self.thr["liveness_floor_leave"])
        self.fire_t: float | None = None
        self.attempts: list[dict] = []      # {cue, start, deadline, seen, passed_at, end}
        self.result: str | None = None
        self.result_t: float | None = None
        self._announced = False
        self._torso = _Ema()
        self._floor_w = _Ema()
        self._floor_a = _Ema()
        self._on_floor_t = {"left": None, "right": None}
        self._run = {"left": 0, "right": 0}

    # ---------------------------------------------------------------- scheduling / state
    def schedule(self, call_t0: float) -> float:
        if self.fire_t is not None:
            raise RuntimeError("liveness challenge already scheduled")
        self.fire_t = float(call_t0) + self.rng.uniform(self.w0, self.w1)
        return self.fire_t

    def due(self, t: float) -> bool:
        return self.fire_t is not None and not self.attempts and self.result is None and t >= self.fire_t

    @property
    def started(self) -> bool:
        return bool(self.attempts)

    @property
    def active(self) -> bool:
        return bool(self.attempts) and self.result is None

    def start(self, t: float) -> str:
        if self.attempts or self.result is not None:
            raise RuntimeError("liveness challenge already started or finished")
        cue = self.rng.choice(CHALLENGES)
        self._open(cue, float(t))
        return cue

    def _open(self, cue: str, t: float) -> None:
        self.attempts.append(dict(cue=cue, start=t, deadline=t + self.timeout, seen=False, passed_at=None, end=None))
        self._run = {"left": 0, "right": 0}

    def _resolve(self, result: str, t: float) -> None:
        self.result, self.result_t = result, t
        if self.attempts and self.attempts[-1]["end"] is None:
            self.attempts[-1]["end"] = t

    def poll(self, t: float) -> tuple[str, str | None]:
        if not self.attempts and self.result is None:
            raise RuntimeError("liveness challenge not started")
        if self.result is not None:
            if self._announced:
                return self.result, None
            self._announced = True
            return self.result, _RESULT_CUE.get(self.result)
        a = self.attempts[-1]
        if a["passed_at"] is not None:
            self._resolve("pass", float(t))
            self._announced = True
            return "pass", "challenge_passed"
        if t <= a["deadline"]:
            return "pending", None
        a["end"] = a["deadline"]
        if len(self.attempts) == 1:
            cue = self.rng.choice([c for c in CHALLENGES if c != a["cue"]])
            self._open(cue, float(t))
            return "retry", cue
        self._resolve("fail" if any(x["seen"] for x in self.attempts) else "skipped", float(t))
        self._announced = True
        return self.result, _RESULT_CUE.get(self.result)

    def finish(self, t_end: float) -> str:
        """Call ended at t_end: settle and return the final result (see the module docstring)."""
        if self.result is not None:
            return self.result
        if not self.attempts:
            self._resolve("skipped", float(t_end))
            return self.result
        a = self.attempts[-1]
        if a["passed_at"] is not None:
            self._resolve("pass", float(t_end))
        else:
            self._resolve("fail" if any(x["seen"] for x in self.attempts) else "skipped", float(t_end))
        self._announced = True        # the call is over: no cue
        return self.result

    def window(self) -> tuple[float, float] | None:
        """(first cue time, resolution time or the open attempt's deadline): the span to exclude from counting."""
        if not self.attempts:
            return None
        end = self.result_t if self.result_t is not None else self.attempts[-1]["deadline"]
        return self.attempts[0]["start"], max(end, self.attempts[0]["start"])

    # ---------------------------------------------------------------- frames
    def on_frame(self, f: FrameObs) -> None:
        if self.result is not None or f.img is None:
            return
        img = np.asarray(f.img, dtype=float)
        if img.ndim != 2 or img.shape[0] < 33 or img.shape[1] < 4:
            return
        aspect = float(getattr(f, "aspect", 16 / 9) or 16 / 9)
        t = float(f.t)
        one = int(f.persons) == 1
        P = {}
        for side, kp in KP.items():
            for name, idx in kp.items():
                if self._conf(img, idx) >= self.min_conf:
                    P[(side, name)] = np.array([img[idx, 0] * aspect, img[idx, 1]], dtype=float)
        a = self.attempts[-1] if self.attempts else None
        in_attempt = a is not None and a["start"] <= t <= a["deadline"] and a["passed_at"] is None
        if a is None and one:
            self._learn(P)
        heights = {s: self._height(P[(s, "wr")]) for s in ("left", "right") if (s, "wr") in P}
        if one:
            for s, kp in KP.items():
                # arming uses the landmark position at any confidence: an occluded far hand resting on the floor
                # is estimated there by the pose model (a hand already up must still come down first)
                raw = img[kp["wr"], :2]
                if np.all(np.isfinite(raw)) and np.all((raw >= 0) & (raw <= 1)):
                    h = self._height(np.array([raw[0] * aspect, raw[1]], dtype=float))
                    if h is not None and h < self.floor_leave:
                        self._on_floor_t[s] = t
        if not in_attempt:
            return
        if one and any((s, "wr") in P for s in KP) and any((s, "sh") in P for s in KP):
            a["seen"] = True
        kind, cmd_hand, target = _SPEC[a["cue"]]
        strict = ("left", "wr") in P and ("right", "wr") in P
        hands = (cmd_hand,) if strict else tuple(s for s in ("left", "right") if (s, "wr") in P)
        for s in ("left", "right"):
            ok = False
            if one and s in hands and heights.get(s) is not None:
                armed = self._on_floor_t[s] is not None and self._on_floor_t[s] >= a["start"] - ARM_LOOKBACK_S
                if armed:
                    if kind == "lift":
                        ok = heights[s] > self.lift_h
                    else:
                        ok = heights[s] > self.floor_leave and self._near_shoulder(P, P[(s, "wr")], target, strict)
            self._run[s] = self._run[s] + 1 if ok else 0
            if self._run[s] >= EVIDENCE_FRAMES:
                a["passed_at"] = t
                return

    def _conf(self, img: np.ndarray, idx: int) -> float:
        c = float(img[idx, 3])
        if img.shape[1] >= 5:
            c = min(c, float(img[idx, 4]))
        x, y = float(img[idx, 0]), float(img[idx, 1])
        if not (math.isfinite(c) and math.isfinite(x) and math.isfinite(y)) or not (0 <= x <= 1 and 0 <= y <= 1):
            return 0.0
        return c

    def _learn(self, P: dict) -> None:
        plank = False
        torsos, ankles = [], []
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
                    tilt = math.degrees(math.atan2(abs(v[1]), abs(v[0])))
                    plank = plank or tilt <= PLANK_MAX_TILT_DEG
        if not plank or not torsos:
            return
        self._torso.add(float(np.mean(torsos)))
        if ankles:
            self._floor_a.add(np.mean(ankles, axis=0))
        wrists = []
        for s in KP:
            if (s, "wr") in P:
                h = self._height(P[(s, "wr")])
                if h is None or h < self.floor_leave:
                    wrists.append(P[(s, "wr")])
        if wrists:
            self._floor_w.add(np.mean(wrists, axis=0))

    def _height(self, w: np.ndarray) -> float | None:
        """Height of point w above the floor line in torso lengths (+ up); None without a baseline."""
        tl, fw = self._torso.v, self._floor_w.v
        if tl is None or fw is None or tl <= _EPS:
            return None
        fa = self._floor_a.v
        if fa is not None and float(np.linalg.norm(fa - fw)) > _EPS:
            u = (fa - fw) / float(np.linalg.norm(fa - fw))
            n = np.array([-u[1], u[0]])
            if n[1] > 0:
                n = -n                       # normal pointing up the image (away from the floor)
            return float((w - fw) @ n) / tl
        return float(fw[1] - w[1]) / tl

    def _near_shoulder(self, P: dict, w: np.ndarray, target: str | None, strict: bool) -> bool:
        if strict and target is not None and (target, "sh") in P:
            cands = [P[(target, "sh")]]
        else:
            cands = [P[(s, "sh")] for s in KP if (s, "sh") in P]
        tl = self._torso.v
        return any(float(np.linalg.norm(w - c)) / tl <= self.tap_dist for c in cands)


_RESULT_CUE = {"pass": "challenge_passed", "fail": "challenge_failed", "skipped": None}
