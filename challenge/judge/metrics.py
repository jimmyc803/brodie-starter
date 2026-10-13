"""Per-rep metric accumulation from per-frame pose landmarks (CONTRACTS C5 / C2 reps columns).

Input: FrameObs per frame. `img` is the MediaPipe (33,5) image-landmark array (x, y, z, visibility, presence), x and y
normalised to [0,1] by frame width / height, y growing DOWNWARD. `aspect` = frame width / height (C5 addition, default
16/9). All geometry is done in "height units": P = (x * aspect, y), i.e. pixels / frame height, so angles are true
image angles regardless of aspect ratio. `world` (33,3) metres, y down, is only used for the torso fallback.

Keypoints per side (MediaPipe): left = shoulder 11, elbow 13, wrist 15, hip 23, knee 25, ankle 27; right = 12, 14, 16,
24, 26, 28. conf(k) = min(visibility, presence) (presence = 1 when the column is absent), NaN -> 0, and 0 when the
landmark lies outside the image ([0,1] in x or y).

Rep window: every frame since the previous close_rep, or since reset() (= counting start), with t <= t_fire. The
window's per-frame (median-filtered) values are buffered until close_rep (memory O(frames in the rep); a 180 s call
at 30 fps is ~5k small records). Frames newer than t_fire (rep event delivered late) stay in a short pending tail
(frames within `max_lag_s` of the newest frame, not yet folded) and go to the next window.

Judged frames (j2, real-footage calibration): RepCounter2 fires near the bottom / early ascent, so a window holds the
previous rep's ascent + lockout, this rep's descent and bottom, and for the first rep the whole setup. A "top" frame
has a filtered visible-side elbow >= lockout_min_deg - TOP_SLACK_DEG; s = the last top frame before the window's last
non-top frame (where this rep's descent starts), a = the first top frame.
  * first rep since reset: frames [s, n) (setup before the last lockout, e.g. kneeling down, is not judged);
  * later reps: frames [0, a] (the previous rep's ascent up to its lockout) and [s, n) (this rep's descent);
    the lockout hold between a and s is skipped, so walking the hands in or shifting during a held top is not judged;
  * no top or no non-top frame: the whole window.
Every metric below is taken over the judged frames ("sel") except top_elbow_deg, persons_in_frame and side, which
use the whole window (a lockout or a second person anywhere in the rep counts).

Evidence rule (D-16): no single frame decides a gate in either direction.
  * Geometric signals (elbow, knee, dev, kc, gap, drop) first pass a running median of the last 3 eligible frames
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
  kc       knee contact height: kh = knee height above the floor line / torso_len, + upward. Floor line = line
           through the per-side EMAs (alpha 0.1, over good frames, carried across reps) of the wrist and ankle
           points, which rest on the floor in a plank. kc = kh while the knee is bent (knee < KNEE_CONTACT_MAX_DEG),
           else max(kh, CONTACT_OFF): with straight legs the wrist-ankle line is not the floor under the knee
           (camera perspective, hands on raised handles), so a straight knee is judged by the pivot test
           instead (knee_floor_contact). None while the two EMA points coincide.
  sup      support-line tilt (deg) = atan2(ankle_y - wrist_y, |wrist_x - ankle_x|): + when the wrists are higher
           in the image than the ankles (incline, hands on a bench), - decline (feet raised). Not median-filtered.
  gap      (elbow_y - shoulder_y) / torso_len; <= 0 means the shoulder is at or below elbow height.
  drop     (wrist_y - shoulder_y) / torso_len.
Metric definitions (sel = judged frames, see above; n = len(sel)):
  side                  'left'|'right': side whose six keypoints have the higher mean visibility over the window
                        (ties -> left); 'none' when no frame has landmarks.
  frame_conf_frac       (# good frames in sel) / n; 0 when n == 0.
  min_keypoint_conf     min over sel of the min visible-side keypoint conf (frames without landmarks = 0).
  persons_in_frame      2nd-highest per-frame person count: > 1 iff >= 2 frames of the rep report more than one person.
  min_elbow_deg_l / _r  2nd-lowest filtered elbow angle of that side over frames where its shoulder, elbow and wrist
                        are confident.
  top_elbow_deg         2nd-highest visible-side elbow angle over the whole window's good frames (the lockout).
  min_knee_deg          2nd-lowest visible-side knee angle over good frames.
  max_hip_line_dev_deg  hi = 2nd-highest and lo = 2nd-lowest dev over good frames, each judged against its own limit:
                        the stored value is hi if hi - hip_line_max_dev_deg >= -lo - hip_pike_max_dev_deg, else lo
                        (the side that exceeds its limit by more), so the live verdict reports hips_sag iff >= 2
                        frames sag beyond the sag limit (unless the pike violation is larger) and likewise for pike.
                        One column (C2), so a rejudge with different hip limits uses the stored side only. First rep since
                        reset: the pike side (2nd-lowest) counts from the first judged frame with
                        dev >= -hip_pike_max_dev_deg (hips coming down from the walk-in excluded); all judged frames if
                        there is none. The sag side always uses every judged frame.
  knee_floor_contact    2nd-lowest kc < knee_floor_margin (>= 2 bent-knee frames within the margin of the floor) OR
                        the knee is planted (_knee_pivot): it is near the floor line and the hips show no plank
                        co-movement (knee height does not follow hip height, or the hips barely move). Catches knees
                        resting on the floor at any knee angle; translation-invariant (one per-rep origin and scale).
  shoulder_elbow_gap    2nd-lowest gap over good frames. Informational only since j2.
  shoulder_wrist_drop   j2: (2nd-lowest drop) / (2nd-highest drop) over good frames = the shoulder's height above
                        the wrist at the bottom as a fraction of that at the lockout (90 deg elbow ~ 0.55, 125 deg
                        ~ 0.85); None when the 2nd-highest drop <= 0. Depth gate (depth_drop_max).
  rep_duration_s        t_fire - window start (previous fire, or first frame after reset).
  cadence_rpm           C5 addition: 60 * 5 / (sum of the last 5 rep durations, this one included) once 5 reps were
                        closed since reset; None before.
  torso_ok              given by the caller (RepCounter2 prone gate) or, when None, computed with
                        rtcoach.repcount2.body_state + gate_ok('prone') per good frame: True iff >= 80% of good frames
                        pass (False when there are no good frames); in both cases AND -decline_max_deg <= median(sup)
                        <= incline_max_deg when any sup exists.
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
TOP_SLACK_DEG = 10.0      # rep-start rule: a "top" frame has filtered elbow >= lockout_min_deg - TOP_SLACK_DEG
CONTACT_OFF = 1.0         # kc of a frame whose knee is not bent (above any knee_floor_margin)
KNEE_PIVOT_SLOPE = 0.2       # knee-height / hip-height slope below which the knee does not ride with the hips
KNEE_PIVOT_MIN_HIP = 0.2     # hip travel (smoothed range, torso lengths) needed for plank evidence; below = planted
KNEE_PIVOT_MIN_FRAMES = 6
KNEE_PIVOT_MAX_KF = 0.1       # ...and the knee must be low: 2nd-lowest height above the wrist-ankle floor line (torso)
KNEE_CONTACT_MAX_DEG = 160.0  # knee angle below which a knee near the floor line counts as contact (CALIBRATION.md)
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


def _kth_low(vals: list[float | None], k: int = EVIDENCE_FRAMES) -> float | None:
    """The k-th smallest finite value (the largest one when fewer than k exist); None when there is none."""
    v = sorted(float(x) for x in vals if x is not None and math.isfinite(x))
    return v[min(k, len(v)) - 1] if v else None


def _kth_high(vals: list[float | None], k: int = EVIDENCE_FRAMES) -> float | None:
    x = _kth_low([None if a is None else -a for a in vals], k)
    return None if x is None else -x


class _Ema:
    __slots__ = ("v",)

    def __init__(self) -> None:
        self.v: np.ndarray | float | None = None

    def add(self, x):
        self.v = x if self.v is None else self.v + EMA_ALPHA * (x - self.v)
        return self.v


@dataclass
class _SideFrame:
    """Per-frame scalars for one body side: raw at add_frame (with the EMAs current at that frame), replaced by their
    median-filtered values when the frame is folded into the window."""
    vis: float | None
    conf_min: float
    good: bool
    elbow_side: float | None          # elbow angle when shoulder/elbow/wrist are confident
    elbow: float | None = None        # the rest only for good frames
    knee: float | None = None
    dev: float | None = None
    kc: float | None = None
    gap: float | None = None
    drop: float | None = None
    sup: float | None = None          # support-line tilt (deg), not median-filtered (the rep uses its median)
    yk: float | None = None           # raw image y of knee / hip / ankle and the torso length (same units), not
    yh: float | None = None           # median-filtered: the knee's motion relative to the hip tells a knee resting on
    ya: float | None = None           # the floor from a plank (_knee_features)
    tor: float | None = None
    kf: float | None = None           # raw knee height above the floor line (kh before the bent-knee rule)
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


_SIGNALS = ("elbow_side", "elbow", "knee", "dev", "kc", "gap", "drop")
_GOOD_SIGNALS = ("elbow", "knee", "dev", "kc", "gap", "drop")


@dataclass
class _Rec:
    t: float
    persons: int
    sides: dict[str, _SideFrame]


class RepMetricsAccumulator:
    """Buffers the current rep window (median-filtered per-frame values) and turns it into RepMetrics at close_rep.
    Deterministic."""

    def __init__(self, thr: dict | None = None, max_lag_s: float = 2.0):
        self.thr = merged_thresholds(thr)
        self.max_lag_s = float(max_lag_s)
        self.reset()

    def reset(self) -> None:
        """Counting start: drops the window, pending frames, cadence history and the floor / torso estimates."""
        self._pending: deque[_Rec] = deque()
        self._t_start: float | None = None
        self._durations: deque[float] = deque(maxlen=CADENCE_REPS)
        self._closed = 0
        self._ema = {s: {"torso": _Ema(), "wr": _Ema(), "an": _Ema()} for s in SIDES}
        self._med = {s: {k: _Med() for k in _SIGNALS} for s in SIDES}
        self._new_window()

    def _new_window(self) -> None:
        self._persons: list[float] = []
        self._win: dict[str, list[_SideFrame]] = {s: [] for s in SIDES}

    def _fold(self, r: _Rec) -> None:
        self._persons.append(float(r.persons))
        for s, sf in r.sides.items():
            med = self._med[s]
            sf.elbow_side = med["elbow_side"].add(sf.elbow_side)
            if sf.good:
                for k in _GOOD_SIGNALS:
                    setattr(sf, k, med[k].add(getattr(sf, k)))
            self._win[s].append(sf)

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
        self._closed += 1
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
        dx = abs(float(P[WR, 0] - P[AN, 0]))
        if dx > _EPS or abs(float(P[AN, 1] - P[WR, 1])) > _EPS:
            sf.sup = math.degrees(math.atan2(float(P[AN, 1] - P[WR, 1]), dx))
        if torso > _EPS:
            sf.gap = float((P[EL, 1] - P[SH, 1]) / torso)
            sf.drop = float((P[WR, 1] - P[SH, 1]) / torso)
            d = a0 - w0
            L = float(np.linalg.norm(d))
            if L > _EPS:
                nrm = np.array([-d[1], d[0]]) / L
                if nrm[1] > 0:
                    nrm = -nrm                   # point up the image (away from the floor)
                kh = float((P[KN] - w0) @ nrm) / torso
                sf.yk, sf.yh, sf.ya, sf.tor = float(P[KN, 1]), float(P[HP, 1]), float(P[AN, 1]), torso
                sf.kf = kh
                bent = math.isfinite(sf.knee) and sf.knee < KNEE_CONTACT_MAX_DEG
                sf.kc = kh if bent else max(kh, CONTACT_OFF)
        sf.prone = _prone(f)
        return sf

    # -- per rep -----------------------------------------------------------------------------------------------
    def _select(self, F: list[_SideFrame]) -> list[int]:
        """Indices of the window frames the rep is judged on (module docstring, rep window)."""
        n = len(F)
        thr = float(self.thr["lockout_min_deg"]) - TOP_SLACK_DEG
        e = [f.elbow_side for f in F]
        tops = [i for i, v in enumerate(e) if v is not None and v >= thr]
        lows = [i for i, v in enumerate(e) if v is not None and v < thr]
        if not tops or not lows:
            return list(range(n))
        starts = [i for i in tops if i < lows[-1]]
        if not starts:
            return list(range(n))
        s, a = starts[-1], tops[0]
        if self._closed == 0:
            return list(range(s, n))
        return list(range(n)) if a >= s else list(range(a + 1)) + list(range(s, n))

    def _metrics(self, labels: list[str], torso_ok: bool | None) -> RepMetrics:
        wl, wr = self._win["left"], self._win["right"]
        vl = [f.vis for f in wl if f.vis is not None]
        vr = [f.vis for f in wr if f.vis is not None]
        if not vl and not vr:
            side = "none"
        else:
            ml = sum(vl) / len(vl) if vl else -1.0
            mr = sum(vr) / len(vr) if vr else -1.0
            side = "right" if mr > ml else "left"
        F = self._win.get(side, wl)
        sel = self._select(F)
        S = [F[i] for i in sel]
        G = [f for f in S if f.good]
        persons = _kth_high(self._persons)
        if torso_ok is None:
            torso_ok = bool(G) and sum(f.prone for f in G) >= TORSO_OK_FRAC * len(G)
        sups = [f.sup for f in G if f.sup is not None]
        if sups:
            sup = float(np.median(sups))
            torso_ok = bool(torso_ok) and -float(self.thr["decline_max_deg"]) <= sup <= float(self.thr["incline_max_deg"])
        devs = [f.dev for f in G if f.dev is not None]
        sag_lim, pike_lim = float(self.thr["hip_line_max_dev_deg"]), float(self.thr["hip_pike_max_dev_deg"])
        pike_devs = devs
        if self._closed == 0:
            # first rep: hips still coming DOWN from walking into the plank are not pike evidence; the pike side counts
            # from the first frame with dev >= -pike limit (plank established). Never there = every frame counts (a
            # piked rep fails). Sag evidence always uses every frame.
            pike_devs = devs[next((i for i, v in enumerate(devs) if v >= -pike_lim), 0):]
        # sag (+) and pike (-) are judged independently, each against its own limit: the stored value is the side that
        # exceeds its limit by more (or is closer to it), so an allowed pike can never hide a sag and vice versa.
        hi, lo = _kth_high(devs), _kth_low(pike_devs)
        dev = None
        if hi is not None and lo is not None:
            dev = hi if (hi - sag_lim) >= (-lo - pike_lim) else lo
        kc = _kth_low([f.kc for f in G])
        pivot = _knee_pivot(G)
        contact = None if kc is None else bool(kc < float(self.thr["knee_floor_margin"]) or pivot)
        d_lo, d_hi = _kth_low([f.drop for f in G]), _kth_high([f.drop for f in G])
        drop = d_lo / d_hi if (d_lo is not None and d_hi is not None and d_hi > _EPS) else None
        return RepMetrics(
            min_elbow_deg_l=_kth_low([wl[i].elbow_side for i in sel]),
            min_elbow_deg_r=_kth_low([wr[i].elbow_side for i in sel]),
            top_elbow_deg=_kth_high([f.elbow for f in F if f.good]), max_hip_line_dev_deg=dev,
            min_knee_deg=_kth_low([f.knee for f in G]),
            knee_floor_contact=contact,
            shoulder_wrist_drop=drop,
            min_keypoint_conf=min(f.conf_min for f in S) if (S and side != "none") else 0.0,
            frame_conf_frac=len(G) / len(S) if S else 0.0,
            persons_in_frame=int(persons) if persons is not None else 0,
            rep_duration_s=0.0, torso_ok=bool(torso_ok), side=side, classifier_labels=labels,
            shoulder_elbow_gap=_kth_low([f.gap for f in G]))


def _knee_features(G: list[_SideFrame]) -> dict | None:
    """Knee evidence over the judged good frames (heights up the image, in one per-rep torso length, from the median
    ankle: translation of the whole body in the frame does not change them).
    slope: least-squares d(knee height) / d(hip height) after a 3-frame moving average; travel: range (max - min) of
    the smoothed hip height, so a bottom hold does not shrink it (both None under KNEE_PIVOT_MIN_FRAMES frames);
    low: 2nd-lowest knee height above the wrist-ankle floor line."""
    pts = [(f.ya, f.yh, f.yk, f.tor) for f in G if f.yk is not None]
    if not pts:
        return None
    A = np.array(pts, dtype=float)
    scale = max(float(np.median(A[:, 3])), _EPS)
    o = float(np.median(A[:, 0]))
    x, y = (o - A[:, 1]) / scale, (o - A[:, 2]) / scale
    out = {"slope": None, "travel": None, "low": _kth_low([f.kf for f in G])}
    if len(x) >= KNEE_PIVOT_MIN_FRAMES:
        k = np.ones(3) / 3.0                     # 3-frame moving average: per-frame jitter would flatten the slope
        xs, ys = np.convolve(x, k, mode="valid"), np.convolve(y, k, mode="valid")
        out["travel"] = float(xs.max() - xs.min())
        out["slope"] = float(np.cov(xs, ys)[0, 1] / max(float(np.var(xs, ddof=1)), _EPS))
    return out


def _knee_pivot(G: list[_SideFrame]) -> bool:
    """True when the knee is planted on the floor (knee push-up), whatever the knee angle. Only a knee near the floor
    line counts (2nd-lowest height above the wrist-ankle line < KNEE_PIVOT_MAX_KF; straight plank legs over raised
    handles or seen from a low camera can sit near it too). Such a knee is cleared only by plank evidence: in a plank
    the pivot is the toes and the knee rides on the ankle-hip line, so its height follows the hip height at about its
    fraction of the leg (slope ~0.5; real clean reps 0.46-0.72 where the knee is near the line; real knee push-ups
    -0.94..-0.73). Planted iff the slope is < KNEE_PIVOT_SLOPE, or it cannot be measured: fewer than
    KNEE_PIVOT_MIN_FRAMES frames or hip travel < KNEE_PIVOT_MIN_HIP (stationary hips with the torso pivoting at the hip
    give no plank evidence, so they do not pass; real clean reps travel >= 0.26)."""
    ft = _knee_features(G)
    if ft is None or ft["low"] is None or ft["low"] >= KNEE_PIVOT_MAX_KF:
        return False
    if ft["slope"] is None or ft["travel"] < KNEE_PIVOT_MIN_HIP:
        return True
    return ft["slope"] < KNEE_PIVOT_SLOPE


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
