"""Per-rep metric accumulation from per-frame pose landmarks (CONTRACTS C5 / C2 reps columns).

Input: FrameObs per frame. `img` is the MediaPipe (33,5) image-landmark array (x, y, z, visibility, presence), x and y
normalised to [0,1] by frame width / height, y growing DOWNWARD. `aspect` = frame width / height (C5 addition, default
16/9). All geometry is done in "height units": P = (x * aspect, y), i.e. pixels / frame height, so angles are true
image angles regardless of aspect ratio. `world` (33,3) metres, y down, is only used for the torso fallback.

Keypoints per side (MediaPipe): left = shoulder 11, elbow 13, wrist 15, hip 23, knee 25, ankle 27; right = 12, 14, 16,
24, 26, 28. conf(k) = min(visibility, presence) (presence = 1 when the column is absent), NaN -> 0, and 0 when the
landmark lies outside the image ([0,1] in x or y).

Rep window: every frame since the previous close_rep, or since reset() (= counting start), with t <= t_fire. Nothing
is truncated: frames are folded into running per-side aggregates (counters, sums and the two most extreme values), so
memory is O(1) per rep. Frames newer than t_fire (rep event delivered late) stay in a short pending tail (frames
within `max_lag_s` of the newest frame, not yet folded) and go to the next window.

Evidence rule (D-16): no single frame decides a gate in either direction.
  * Geometric signals (elbow, knee, dev, kh, gap, drop) first pass a running median of the last 3 eligible frames
    (continuous across rep windows), so a 1-frame landmark spike vanishes and a pose held for >= 2 consecutive
    frames survives. Each extreme metric is then the SECOND most extreme filtered value ("2nd-lowest" /
    "2nd-highest"): a threshold is crossed only by a fault (or a lockout / depth) lasting >= 2 consecutive frames,
    and the median also keeps sub-threshold jitter at sigma 0.01-0.02 from rejecting clean reps.
  * persons_in_frame is the 2nd-highest RAW count: any 2 frames of the rep (consecutive or not) with > 1 person.
  With a single eligible value the metric is that value.

Per-frame values, all median-filtered as above ("good" frame = all six visible-side keypoints at conf >= min_conf;
torso_len = per-side exponential moving average (alpha 0.1, carried across reps until reset) of |shoulder - hip| in
height units over good frames):
  elbow    angle shoulder-elbow-wrist (deg).            knee   angle hip-knee-ankle (deg).
  dev      180 - angle(shoulder, hip, ankle), + when the hip lies below the shoulder-ankle line (larger image y,
           toward the floor = sag), - above (pike).
  kh       knee height above the floor line / torso_len, + upward. Floor line = line through the per-side EMAs
           (alpha 0.1, over good frames, carried across reps) of the wrist and ankle points, which rest on the floor
           in a plank. None while the two EMA points coincide.
  gap      (elbow_y - shoulder_y) / torso_len; <= 0 means the shoulder is at or below elbow height.
  drop     (wrist_y - shoulder_y) / torso_len.
Metric definitions (n = frames in the window):
  side                  'left'|'right': side whose six keypoints have the higher mean visibility over the window
                        (ties -> left); 'none' when no frame has landmarks.
  frame_conf_frac       (# good frames) / n; 0 when n == 0.
  min_keypoint_conf     min over all window frames of the min visible-side keypoint conf (frames without landmarks = 0).
  persons_in_frame      2nd-highest per-frame person count: > 1 iff >= 2 frames of the rep report more than one person.
  min_elbow_deg_l / _r  2nd-lowest filtered elbow angle of that side over frames where its shoulder, elbow and wrist
                        are confident.
  top_elbow_deg         2nd-highest visible-side elbow angle over good frames (the lockout around the rep).
  min_knee_deg          2nd-lowest visible-side knee angle over good frames.
  max_hip_line_dev_deg  of the 2nd-highest and the 2nd-lowest dev over good frames, the one with the larger magnitude
                        (so |value| > limit iff >= 2 frames deviate beyond the limit on that side).
  knee_floor_contact    2nd-lowest kh < knee_floor_margin (>= 2 frames with the knee within the margin of the floor).
  shoulder_elbow_gap    2nd-lowest gap over good frames (SPEC §6 depth criterion; contract amendment).
  shoulder_wrist_drop   2nd-lowest drop over good frames. Informational only.
  rep_duration_s        t_fire - window start (previous fire, or first frame after reset).
  cadence_rpm           C5 addition: 60 * 5 / (sum of the last 5 rep durations, this one included) once 5 reps were
                        closed since reset; None before.
  torso_ok              given by the caller (RepCounter2 prone gate) or, when None, computed with
                        rtcoach.repcount2.body_state + gate_ok('prone') per good frame: True iff >= 80% of good frames
                        pass (False when there are no good frames).
Every geometric metric is None when no good frame exists (gates.judge_rep then reports not_in_frame).
Angles are rounded to 0.01 deg and ratios to 1e-4 (below float32 `real` storage precision, so re-judging stored
metrics reproduces the live verdict and an exact 90.000 deg bottom is not lost to float error).
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from challenge.judge.gates import merged_thresholds

SIDES = {"left": (11, 13, 15, 23, 25, 27), "right": (12, 14, 16, 24, 26, 28)}
SH, EL, WR, HP, KN, AN = range(6)
CADENCE_REPS = 5
TORSO_OK_FRAC = 0.8
EVIDENCE_FRAMES = 2       # a gate is decided by the k-th most extreme frame (D-16)
EMA_ALPHA = 0.1
_EPS = 1e-9


@dataclass
class FrameObs:
    t: float
    img: np.ndarray | None          # (33,5) x,y,z,visibility,presence normalised; y down
    world: np.ndarray | None        # (33,3) metres
    persons: int
    aspect: float = 16 / 9          # frame width / height (C5 addition)


@dataclass
class RepMetrics:
    min_elbow_deg_l: float | None
    min_elbow_deg_r: float | None
    top_elbow_deg: float | None
    max_hip_line_dev_deg: float | None
    min_knee_deg: float | None
    knee_floor_contact: bool | None
    shoulder_wrist_drop: float | None
    min_keypoint_conf: float
    frame_conf_frac: float
    persons_in_frame: int
    rep_duration_s: float
    torso_ok: bool
    side: str
    classifier_labels: list[str] = field(default_factory=list)
    shoulder_elbow_gap: float | None = None
    cadence_rpm: float | None = None


def angle_deg(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Angle a-b-c at b in degrees (0..180); NaN when a segment has zero length."""
    v1 = a - b
    v2 = c - b
    n = float(np.linalg.norm(v1) * np.linalg.norm(v2))
    if n < _EPS:
        return float("nan")
    return float(np.degrees(np.arccos(np.clip(float(v1 @ v2) / n, -1.0, 1.0))))


def hip_line_dev_deg(s: np.ndarray, h: np.ndarray, a: np.ndarray) -> float:
    """Signed deviation at the hip: + hip below the shoulder-ankle line (sag), - above (pike). Height units, y down."""
    ang = angle_deg(s, h, a)
    if np.isnan(ang):
        return float("nan")
    u = a - s
    n = np.array([-u[1], u[0]])
    if n[1] < 0:
        n = -n                       # normal pointing down the image (toward the floor)
    side = float((h - s) @ n)
    return (180.0 - ang) * (1.0 if side > 0 else -1.0 if side < 0 else 0.0)


def _conf(img: np.ndarray, idx: tuple[int, ...]) -> np.ndarray:
    sub = img[list(idx)]
    c = sub[:, 3].astype(float)
    if img.shape[1] >= 5:
        c = np.minimum(c, sub[:, 4].astype(float))
    c = np.nan_to_num(c, nan=0.0)
    xy = sub[:, :2]
    inside = np.all((xy >= 0.0) & (xy <= 1.0), axis=1)
    return np.where(inside, c, 0.0)


class _Low:
    """The EVIDENCE_FRAMES smallest finite values seen; kth() = the k-th smallest (or the largest held if fewer)."""
    __slots__ = ("v", "k")

    def __init__(self, k: int = EVIDENCE_FRAMES) -> None:
        self.v: list[float] = []
        self.k = k

    def add(self, x: float | None) -> None:
        if x is None or not math.isfinite(x):
            return
        self.v.append(float(x))
        self.v.sort()
        del self.v[self.k:]

    def kth(self) -> float | None:
        return self.v[-1] if self.v else None


class _High(_Low):
    def add(self, x: float | None) -> None:
        super().add(None if x is None else -x)

    def kth(self) -> float | None:
        k = super().kth()
        return None if k is None else -k


class _Ema:
    __slots__ = ("v",)

    def __init__(self) -> None:
        self.v: np.ndarray | float | None = None

    def add(self, x):
        self.v = x if self.v is None else self.v + EMA_ALPHA * (x - self.v)
        return self.v


@dataclass
class _SideFrame:
    """Per-frame scalars for one body side (computed at add_frame with the EMAs current at that frame)."""
    vis: float | None
    conf_min: float
    good: bool
    elbow_side: float | None          # elbow angle when shoulder/elbow/wrist are confident
    elbow: float | None = None        # the rest only for good frames
    knee: float | None = None
    dev: float | None = None
    kh: float | None = None
    gap: float | None = None
    drop: float | None = None
    prone: bool = False


class _Med:
    """Running median of the last 3 values of one per-frame signal (continuous across rep windows, cleared on reset).
    A 1-frame spike never survives; a value held for >= 2 consecutive frames does."""
    __slots__ = ("buf",)

    def __init__(self, n: int = 3) -> None:
        self.buf: deque[float] = deque(maxlen=n)

    def add(self, x: float | None) -> float | None:
        if x is None or not math.isfinite(x):
            return None
        self.buf.append(float(x))
        return float(np.median(self.buf))


_SIGNALS = ("elbow_side", "elbow", "knee", "dev", "kh", "gap", "drop")


class _SideAgg:
    def __init__(self, med: dict[str, _Med]) -> None:
        self.med = med
        self.vis_sum = 0.0
        self.vis_n = 0
        self.good = 0
        self.conf_min: float | None = None
        self.elbow_side = _Low()
        self.top = _High()
        self.knee = _Low()
        self.dev_hi = _High()
        self.dev_lo = _Low()
        self.kh = _Low()
        self.gap = _Low()
        self.drop = _Low()
        self.prone = 0

    def fold(self, s: _SideFrame) -> None:
        if s.vis is not None:
            self.vis_sum += s.vis
            self.vis_n += 1
        self.conf_min = s.conf_min if self.conf_min is None else min(self.conf_min, s.conf_min)
        self.elbow_side.add(self.med["elbow_side"].add(s.elbow_side))
        if s.good:
            self.good += 1
            self.top.add(self.med["elbow"].add(s.elbow))
            self.knee.add(self.med["knee"].add(s.knee))
            d = self.med["dev"].add(s.dev)
            self.dev_hi.add(d)
            self.dev_lo.add(d)
            self.kh.add(self.med["kh"].add(s.kh))
            self.gap.add(self.med["gap"].add(s.gap))
            self.drop.add(self.med["drop"].add(s.drop))
            self.prone += s.prone


@dataclass
class _Rec:
    t: float
    persons: int
    sides: dict[str, _SideFrame]


class RepMetricsAccumulator:
    """Folds frames into the current rep window and turns them into RepMetrics at close_rep. Deterministic."""

    def __init__(self, thr: dict | None = None, max_lag_s: float = 2.0):
        self.thr = merged_thresholds(thr)
        self.max_lag_s = float(max_lag_s)
        self.reset()

    def reset(self) -> None:
        """Counting start: drops the window, pending frames, cadence history and the floor / torso estimates."""
        self._pending: deque[_Rec] = deque()
        self._t_start: float | None = None
        self._durations: deque[float] = deque(maxlen=CADENCE_REPS)
        self._ema = {s: {"torso": _Ema(), "wr": _Ema(), "an": _Ema()} for s in SIDES}
        self._med = {s: {k: _Med() for k in _SIGNALS} for s in SIDES}
        self._new_window()

    def _new_window(self) -> None:
        self._n = 0
        self._persons = _High()
        self._agg = {s: _SideAgg(self._med[s]) for s in SIDES}

    def _fold(self, r: _Rec) -> None:
        self._n += 1
        self._persons.add(float(r.persons))
        for s, sf in r.sides.items():
            self._agg[s].fold(sf)

    def add_frame(self, f: FrameObs) -> None:
        if self._t_start is None:
            self._t_start = float(f.t)
        self._pending.append(_Rec(float(f.t), int(f.persons), {s: self._side_frame(f, s) for s in SIDES}))
        newest = float(f.t)
        while self._pending and self._pending[0].t < newest - self.max_lag_s:
            self._fold(self._pending.popleft())

    def close_rep(self, t_fire: float, labels: list[str], torso_ok: bool | None = None) -> RepMetrics:
        t_fire = float(t_fire)
        keep: deque[_Rec] = deque()
        for r in self._pending:
            if r.t <= t_fire:
                self._fold(r)
            else:
                keep.append(r)
        self._pending = keep
        t0 = self._t_start if self._t_start is not None else t_fire
        duration = max(0.0, t_fire - t0)
        self._t_start = t_fire
        self._durations.append(duration)
        cadence = None
        if len(self._durations) == CADENCE_REPS:
            tot = sum(self._durations)
            cadence = 60.0 * CADENCE_REPS / tot if tot > _EPS else float("inf")
        m = self._metrics(list(labels or []), torso_ok)
        m.rep_duration_s = round(duration, 4)
        m.cadence_rpm = None if cadence is None else round(cadence, 4)
        self._new_window()
        return _rounded(m)

    # -- per frame ---------------------------------------------------------------------------------------------
    def _side_frame(self, f: FrameObs, side: str) -> _SideFrame:
        if f.img is None:
            return _SideFrame(vis=None, conf_min=0.0, good=False, elbow_side=None)
        ix = SIDES[side]
        min_conf = float(self.thr["min_conf"])
        conf = _conf(f.img, ix)
        vis = float(np.nan_to_num(np.mean(np.nan_to_num(f.img[list(ix), 3].astype(float), nan=0.0))))
        P = f.img[list(ix), :2].astype(float) * np.array([f.aspect, 1.0])
        arm_ok = bool(np.all(conf[[SH, EL, WR]] >= min_conf))
        good = bool(np.all(conf >= min_conf))
        sf = _SideFrame(vis=vis, conf_min=float(conf.min()), good=good,
                        elbow_side=angle_deg(P[SH], P[EL], P[WR]) if arm_ok else None)
        if not good:
            return sf
        e = self._ema[side]
        torso = float(e["torso"].add(float(np.linalg.norm(P[SH] - P[HP]))))
        w0 = e["wr"].add(P[WR].copy())
        a0 = e["an"].add(P[AN].copy())
        sf.elbow = sf.elbow_side
        sf.knee = angle_deg(P[HP], P[KN], P[AN])
        sf.dev = hip_line_dev_deg(P[SH], P[HP], P[AN])
        if torso > _EPS:
            sf.gap = float((P[EL, 1] - P[SH, 1]) / torso)
            sf.drop = float((P[WR, 1] - P[SH, 1]) / torso)
            d = a0 - w0
            L = float(np.linalg.norm(d))
            if L > _EPS:
                nrm = np.array([-d[1], d[0]]) / L
                if nrm[1] > 0:
                    nrm = -nrm                   # point up the image (away from the floor)
                sf.kh = float((P[KN] - w0) @ nrm) / torso
        sf.prone = _prone(f)
        return sf

    # -- per rep -----------------------------------------------------------------------------------------------
    def _metrics(self, labels: list[str], torso_ok: bool | None) -> RepMetrics:
        al, ar = self._agg["left"], self._agg["right"]
        if al.vis_n == 0 and ar.vis_n == 0:
            side = "none"
        else:
            ml = al.vis_sum / al.vis_n if al.vis_n else -1.0
            mr = ar.vis_sum / ar.vis_n if ar.vis_n else -1.0
            side = "right" if mr > ml else "left"
        a = self._agg.get(side, al)
        n = self._n
        persons = self._persons.kth()
        if torso_ok is None:
            torso_ok = a.good > 0 and a.prone >= TORSO_OK_FRAC * a.good
        hi, lo = a.dev_hi.kth(), a.dev_lo.kth()
        dev = None
        if hi is not None and lo is not None:
            dev = hi if abs(hi) >= abs(lo) else lo
        kh = a.kh.kth()
        return RepMetrics(
            min_elbow_deg_l=al.elbow_side.kth(), min_elbow_deg_r=ar.elbow_side.kth(),
            top_elbow_deg=a.top.kth(), max_hip_line_dev_deg=dev, min_knee_deg=a.knee.kth(),
            knee_floor_contact=None if kh is None else bool(kh < float(self.thr["knee_floor_margin"])),
            shoulder_wrist_drop=a.drop.kth(),
            min_keypoint_conf=float(a.conf_min) if (a.conf_min is not None and side != "none") else 0.0,
            frame_conf_frac=a.good / n if n else 0.0,
            persons_in_frame=int(persons) if persons is not None else 0,
            rep_duration_s=0.0, torso_ok=bool(torso_ok), side=side, classifier_labels=labels,
            shoulder_elbow_gap=a.gap.kth())


def _prone(f: FrameObs) -> bool:
    from rtcoach.repcount2 import body_state, gate_ok
    xy = f.img[:, :2]
    torso = float(np.linalg.norm((xy[11] + xy[12]) / 2 - (xy[23] + xy[24]) / 2)) + _EPS
    return bool(gate_ok("prone", body_state(f.img, f.world, torso)))


_ANGLES = ("min_elbow_deg_l", "min_elbow_deg_r", "top_elbow_deg", "max_hip_line_dev_deg", "min_knee_deg")
_RATIOS = ("shoulder_wrist_drop", "shoulder_elbow_gap", "min_keypoint_conf", "frame_conf_frac")


def _rounded(m: RepMetrics) -> RepMetrics:
    for name, nd in [(a, 2) for a in _ANGLES] + [(r, 4) for r in _RATIOS]:
        v = getattr(m, name)
        if v is not None:
            setattr(m, name, round(float(v), nd))
    return m
