"""Live judge hook (CONTRACTS C5 JudgeRuntime): per-frame observations in, one RepVerdict per counted rep out.

RepCounter2 decides THAT a rep happened; this decides whether it counts. facetime.pipeline.FramePipeline owns one
JudgeRuntime per push-up Coach (judge option on) and drives it on the pipeline's frame clock (seconds, t_ms / 1000):

    on_frame(FrameObs)            every processed frame (also frames without a pose or while the counter is paused)
    on_label(t, label)            every classifier correction label the Coach emitted (Coach.say(..., 'correction', label))
    on_rep(event) -> RepVerdict   when the counter's count goes up; event = {'t': fire time on the same clock, 'n': ...,
                                  (the rep's OWN fire time: a rep the counter held and confirms later keeps its earlier t;
                                  frames newer than t stay pending for the next rep while within max_lag_s of the newest)
                                  optional 'torso_ok': bool (None/absent: computed from the window, see metrics.py)}
    set_challenge_window(t0, t1)  reps fired inside [t0, t1] are marked in_challenge (liveness challenge; the caller
                                  neither counts nor penalises them) and get no corrective cue.
    update_challenge_window(t0, t1)  replace the window starting at t0 (or add it): feed LivenessChallenge.windows()
                                  after every start()/poll(), since a FREEZE attempt's deadline shrinks.

Classifier labels for a rep = labels emitted in (previous fire, this fire]; the classifier can only veto (gates.py).
Cue: the most useful reject reason that has a spoken cue (challenge.judge.cues.best_cue, CUE_PRIORITY: depth before hips
and lockout, not_horizontal last), at most one cue per thr['cue_min_gap_s'] seconds and the same cue at most once per
thr['cue_repeat_gap_s'] seconds, so a caller repeating one fault hears it once, not every other rep (j4, no nagging; a
suppressed cue is None, not queued).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any

from challenge.judge.cues import best_cue
from challenge.judge.gates import JUDGE_VERSION, judge_rep, merged_thresholds
from challenge.judge.metrics import FrameObs, RepMetricsAccumulator


@dataclass
class RepVerdict:
    valid: bool
    reasons: list[str]
    metrics: dict[str, Any]          # RepMetrics as a dict: the C2 reps metric columns (+ side, classifier_labels, cadence_rpm)
    cue_key: str | None
    in_challenge: bool = False
    judge_version: str = JUDGE_VERSION
    t: float | None = None
    n: int | None = None
    labels: list[str] = field(default_factory=list)

    def event_fields(self) -> dict[str, Any]:
        """The fields a rep event gains (facetime.perception rep events)."""
        return {"valid": self.valid, "reject_reasons": list(self.reasons), "metrics": dict(self.metrics),
                "judge_version": self.judge_version, "cue": self.cue_key, "in_challenge": self.in_challenge}


class JudgeRuntime:
    def __init__(self, thr: dict | None = None, max_lag_s: float = 2.0):
        self.thr = merged_thresholds(thr)
        self.acc = RepMetricsAccumulator(self.thr, max_lag_s=max_lag_s)
        self.windows: list[tuple[float, float]] = []
        self.verdicts: list[RepVerdict] = []
        self._labels: list[tuple[float, str]] = []
        self._last_fire: float | None = None
        self._last_cue_t: float | None = None
        self._cue_t: dict[str, float] = {}         # cue key -> time it was last given (cue_repeat_gap_s)

    def reset(self) -> None:
        """Counting (re)starts (also when the tracked person is replaced, so no rep mixes two people): drop the buffered frames, labels, cadence history and cue rate limit (challenge windows stay)."""
        self.acc.reset()
        self._labels = []
        self._last_fire = None
        self._last_cue_t = None
        self._cue_t = {}

    def on_frame(self, f: FrameObs) -> None:
        self.acc.add_frame(f)

    def on_label(self, t: float, label: str) -> None:
        if label:
            self._labels.append((float(t), str(label)))

    def set_challenge_window(self, t0: float, t1: float) -> None:
        t0, t1 = float(t0), float(t1)
        if t1 < t0:
            raise ValueError(f"challenge window ends before it starts: {t0} > {t1}")
        self.windows.append((t0, t1))

    def update_challenge_window(self, t0: float, t1: float) -> None:
        """Set the window that starts at t0 to end at t1 (adds it if none starts at t0): a liveness FREEZE attempt
        registers its latest possible deadline and shrinks it later (LivenessChallenge.windows())."""
        t0, t1 = float(t0), float(t1)
        if t1 < t0:
            raise ValueError(f"challenge window ends before it starts: {t0} > {t1}")
        for i, (a, _) in enumerate(self.windows):
            if a == t0:
                self.windows[i] = (t0, t1)
                return
        self.windows.append((t0, t1))

    def in_challenge(self, t: float) -> bool:
        return any(a <= t <= b for a, b in self.windows)

    def on_rep(self, event: dict) -> RepVerdict:
        t = float(event["t"])
        lo = self._last_fire
        labels = list(dict.fromkeys(lab for tl, lab in self._labels if tl <= t and (lo is None or tl > lo)))
        self._labels = [(tl, lab) for tl, lab in self._labels if tl > t]
        self._last_fire = t
        m = self.acc.close_rep(t, labels, event.get("torso_ok"))
        valid, reasons = judge_rep(m, self.thr)
        inch = self.in_challenge(t)
        cue = None if (valid or inch) else self._cue(t, reasons)
        v = RepVerdict(valid=valid, reasons=reasons, metrics=dataclasses.asdict(m), cue_key=cue, in_challenge=inch,
                       t=t, n=event.get("n"), labels=labels)
        self.verdicts.append(v)
        return v

    def _cue(self, t: float, reasons: list[str]) -> str | None:
        key = best_cue(reasons)
        if key is None:
            return None
        if self._last_cue_t is not None and t - self._last_cue_t < float(self.thr["cue_min_gap_s"]):
            return None
        last = self._cue_t.get(key)
        if last is not None and t - last < float(self.thr["cue_repeat_gap_s"]):
            return None
        self._last_cue_t = t
        self._cue_t[key] = t
        return key
