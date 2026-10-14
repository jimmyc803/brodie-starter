"""Per-rep metric accumulation from per-frame pose landmarks (CONTRACTS C5 / C2 reps columns).

Input: FrameObs per frame. `img` is the MediaPipe (33,5) image-landmark array (x, y, z, visibility, presence), x and y
normalised to [0,1] by frame width / height, y growing DOWNWARD. `aspect` = frame width / height (C5 addition, default
16/9). All geometry is done in "height units": P = (x * aspect, y), i.e. pixels / frame height, so angles are true
image angles regardless of aspect ratio. `world` (33,3) metres, y down (MediaPipe world landmarks: metric 3-D, so their
angles do not depend on the camera view) is used for the torso fallback and, since j4, for the knee, hip line and
lockout readings (see "j4" below).

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

Per-frame values, all median-filtered as above. j3 (lenient, docs/challenge/CALIBRATION.md "j3 lenient"): each value
needs only its own keypoints at conf >= min_conf, so feet / ankles / knees outside the frame or an occluded far side
never make the arm signals unmeasurable; a value whose keypoints are missing is None and its gate is skipped. Knee and
ankle need conf >= leg_min_conf (higher than min_conf: pose models extrapolate legs outside the frame at about 0.4-0.6,
real visible-side legs read >= 0.8).
torso_len = per-side exponential moving average (alpha 0.1, carried across reps until reset) of |shoulder - hip| in
height units over frames with both confident (its last value is used while the hip is not visible):
  elbow    angle shoulder-elbow-wrist (deg)                          [shoulder, elbow, wrist]
  knee     angle hip-knee-ankle (deg)                                [hip, knee*, ankle*]   (* = leg_min_conf)
  dev      180 - angle(shoulder, hip, ankle), + when the hip lies below the shoulder-ankle line (larger image y,
           toward the floor = sag), - above (pike). Ankle not confident: the shoulder-hip-knee line instead.
  kc       knee contact height: kh = knee height above the floor line / torso_len, + upward. Floor line = line
           through the per-side EMAs (alpha 0.1, carried across reps) of the wrist and ankle points, which rest on
           the floor in a plank; None in a frame without a confident knee and ankle.
           kc = kh, except max(kh, CONTACT_OFF) when the knee angle is measured >= KNEE_CONTACT_MAX_DEG (a straight
           leg is not resting on its knee; camera perspective / raised handles can put it near the line).
  sup      support-line tilt (deg) = atan2(ankle_y - wrist_y, |wrist_x - ankle_x|): + when the wrists are higher
           in the image than the ankles (incline, hands on a bench), - decline (feet raised). Not median-filtered.
  gap      (elbow_y - shoulder_y) / torso_len; <= 0 means the shoulder is at or below elbow height.
  drop     wrist_y - shoulder_y (height units; the shoulder's height above the wrist)   [shoulder, elbow, wrist]
  j4 (docs/challenge/CALIBRATION.md "j4"), with world landmarks present (each reading falls back to the image alone):
  knee     the world angle when it is straighter than the image one by more than KNEE_WORLD_GAP_DEG (a foreshortened
           straight leg), else the image angle.
  dev      image and world (world_hip_dev_deg: 3-D angle, sign from the hip's offset along world y) combined by
           _agree: the smaller magnitude when both have the same sign, 0 when they disagree (a perspective bend).
  elbow_w  world shoulder-elbow-wrist angle. top_elbow_deg is the larger of the image and world 2nd-highest
           values; j5: min_elbow_deg_l/_r take the world angle when it is straighter than the image one by more
           than ELBOW_WORLD_GAP_DEG (the same _straighter rule as the knee: a phone in front of the lifter
           foreshortens arms pointing at it, so a locked-out arm can read as a deep bend in the image).
Metric definitions (sel = judged frames, see above; n = len(sel)):
  side                  'left'|'right': side whose six keypoints have the higher mean visibility over the window
                        (ties -> left); 'none' when no frame has landmarks.
  frame_conf_frac       j3: (# sel frames whose shoulder, elbow and wrist are confident on at least one side) / n;
                        0 when n == 0 (the upper body only: legs outside the frame do not lower it).
  min_keypoint_conf     min over sel of the min visible-side keypoint conf (frames without landmarks = 0).
  persons_in_frame      2nd-highest per-frame person count: > 1 iff >= 2 frames of the rep report more than one person.
  min_elbow_deg_l / _r  2nd-lowest filtered elbow angle of that side over frames where its shoulder, elbow and wrist
                        are confident (the depth gate uses the better side). j5: each frame's angle is the image
                        one, replaced by the world one when that is straighter by more than ELBOW_WORLD_GAP_DEG,
                        so the stored depth does not depend on where the camera stands.
  top_elbow_deg         2nd-highest visible-side elbow angle over the whole window (the lockout); the other side's
                        when the visible side's arm is never confident.
  min_knee_deg          2nd-lowest visible-side knee angle (None without a confident hip, knee and ankle).
  max_hip_line_dev_deg  hi = 2nd-highest and lo = 2nd-lowest dev, each judged against its own limit:
                        the stored value is hi if hi - hip_line_max_dev_deg >= -lo - hip_pike_max_dev_deg, else lo
                        (the side that exceeds its limit by more), so the live verdict reports hips_sag iff >= 2
                        frames sag beyond the sag limit (unless the pike violation is larger) and likewise for pike.
                        One column (C2), so a rejudge with different hip limits uses the stored side only. First rep since
                        reset: the pike side (2nd-lowest) counts from the first judged frame with
                        dev >= -hip_pike_max_dev_deg (hips coming down from the walk-in excluded); all judged frames if
                        there is none. The sag side always uses every judged frame.
  knee_floor_contact    2nd-lowest kc < knee_floor_margin (>= 2 frames with the knee within the margin of the floor);
                        None when the knee is never measurable. j3: no pivot heuristic (judge: knees_down also needs
                        a measured knee angle < knee_min_deg when there is one).
  shoulder_elbow_gap    2nd-lowest gap. Informational only since j2.
  shoulder_wrist_drop   (2nd-lowest drop) / (2nd-highest drop) = the shoulder's height above the wrist at the bottom
                        as a fraction of that at the lockout (90 deg elbow ~ 0.55, 125 deg ~ 0.85); None when the
                        2nd-highest drop <= 0. View-robust depth evidence (a front or diagonal view foreshortens the
                        elbow angle, not the shoulder's travel toward the hands).
  rep_duration_s        t_fire - window start (previous fire, or first frame after reset).
  cadence_rpm           C5 addition: 60 * 5 / (sum of the last 5 rep durations, this one included) once 5 reps were
                        closed since reset; None before.
  torso_ok              given by the caller or, when None, computed with rtcoach.repcount2.body_state +
                        gate_ok('prone') per sel frame with a confident shoulder and hip (all sel frames with landmarks
                        when there is none): True iff >= TORSO_OK_FRAC of them pass (False without any); in both cases
                        AND -decline_max_deg <= median(sup) <= incline_max_deg when any sup exists.
Every geometric metric is None when its keypoints are never confident (gates.judge_rep then skips its gate; no arm
signal at all reports not_in_frame).
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
TORSO_OK_FRAC = 0.6
EVIDENCE_FRAMES = 2       # a gate is decided by the k-th most extreme frame (D-16)
TOP_SLACK_DEG = 10.0      # rep-start rule: a "top" frame has filtered elbow >= lockout_min_deg - TOP_SLACK_DEG
CONTACT_OFF = 1.0         # kc of a frame whose knee is not bent (above any knee_floor_margin)
KNEE_CONTACT_MAX_DEG = 160.0  # knee angle below which a knee near the floor line counts as contact (CALIBRATION.md)
KNEE_WORLD_GAP_DEG = 15.0     # j4: the world knee angle replaces the image one when it is straighter by more than this
ELBOW_WORLD_GAP_DEG = 15.0    # j5: likewise for the depth elbow (a front view foreshortens a straight arm into a bend)
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
    elbow_side: float | None          # elbow angle when shoulder/elbow/wrist are confident
    elbow: float | None = None        # each one only when its keypoints are confident
    knee: float | None = None
    dev: float | None = None
    kc: float | None = None
    gap: float | None = None
    drop: float | None = None
    sup: float | None = None          # support-line tilt (deg), not median-filtered (the rep uses its median)
    tilt: float | None = None         # world support-line tilt (deg), not median-filtered (the rep uses its median)
    elbow_w: float | None = None      # j4: world-landmark elbow angle (lockout evidence that foreshortening cannot shrink)
    arm: bool = False                 # shoulder, elbow and wrist confident (upper body measurable)
    torso: bool = False               # shoulder and hip confident (torso_ok evidence)
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


_SIGNALS = ("elbow_side", "elbow", "knee", "dev", "kc", "gap", "drop", "elbow_w")


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
            for k in _SIGNALS:
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
        """j3: each signal is computed from the keypoints it needs only, so a cut-off or occluded lower body leaves the
        arm signals (elbow, drop) measurable and the leg signals None (their gates are then skipped)."""
        if f.img is None:
            return _SideFrame(vis=None, conf_min=0.0, elbow_side=None)
        ix = SIDES[side]
        min_conf = float(self.thr["min_conf"])
        conf = _conf(f.img, ix)
        vis = float(np.nan_to_num(np.mean(np.nan_to_num(f.img[list(ix), 3].astype(float), nan=0.0))))
        P = f.img[list(ix), :2].astype(float) * np.array([f.aspect, 1.0])
        ok = conf >= min_conf
        leg = conf >= float(self.thr["leg_min_conf"])   # knee / ankle: pose models extrapolate legs out of frame
        arm_ok = bool(ok[SH] and ok[EL] and ok[WR])
        sf = _SideFrame(vis=vis, conf_min=float(conf.min()),
                        elbow_side=angle_deg(P[SH], P[EL], P[WR]) if arm_ok else None)
        sf.arm, sf.torso = arm_ok, bool(ok[SH] and ok[HP])
        sf.prone = _prone(f)
        e = self._ema[side]
        torso = None
        if sf.torso:
            torso = float(e["torso"].add(float(np.linalg.norm(P[SH] - P[HP]))))
        elif e["torso"].v is not None:
            torso = float(e["torso"].v)
        w0 = e["wr"].add(P[WR].copy()) if ok[WR] else e["wr"].v
        a0 = e["an"].add(P[AN].copy()) if leg[AN] else None
        W = _world_side(f.world, ix)
        if arm_ok:
            sf.elbow = sf.elbow_side
            sf.drop = float(P[WR, 1] - P[SH, 1])     # shoulder height above the wrist (height units; only its ratio counts)
            if W is not None:
                sf.elbow_w = _finite(angle_deg(W[SH], W[EL], W[WR]))
        if ok[HP] and leg[KN] and leg[AN]:
            # j4: foreshortening (legs pointing toward or away from the camera) makes a straight leg look bent in the
            # image; the world angle is view-independent, so it wins when it is clearly straighter (_straighter).
            sf.knee = _straighter(angle_deg(P[HP], P[KN], P[AN]),
                                  None if W is None else angle_deg(W[HP], W[KN], W[AN]))
        far = AN if leg[AN] else (KN if leg[KN] else None)   # ankles out of frame: the shoulder-hip-knee line
        if ok[SH] and ok[HP] and far is not None:
            # j4: the image deviation, shrunk to the world deviation when that is smaller (0 when they disagree on the
            # side): an off-angle camera inflates the image hip angle, the world angle does not change with the view
            sf.dev = _agree(hip_line_dev_deg(P[SH], P[HP], P[far]),
                            None if W is None else world_hip_dev_deg(W[SH], W[HP], W[far]))
        if ok[WR] and leg[AN]:
            sf.tilt = _world_tilt(f.world, ix[WR], ix[AN])
            dx = abs(float(P[WR, 0] - P[AN, 0]))
            if dx > _EPS or abs(float(P[AN, 1] - P[WR, 1])) > _EPS:
                sf.sup = math.degrees(math.atan2(float(P[AN, 1] - P[WR, 1]), dx))
        if torso is not None and torso > _EPS:
            if ok[SH] and ok[EL]:
                sf.gap = float((P[EL, 1] - P[SH, 1]) / torso)
            if leg[KN] and w0 is not None and a0 is not None:
                d = a0 - w0
                L = float(np.linalg.norm(d))
                if L > _EPS:
                    nrm = np.array([-d[1], d[0]]) / L
                    if nrm[1] > 0:
                        nrm = -nrm                   # point up the image (away from the floor)
                    kh = float((P[KN] - w0) @ nrm) / torso
                    knee_ok = sf.knee is not None and math.isfinite(sf.knee)
                    sf.kc = max(kh, CONTACT_OFF) if knee_ok and sf.knee >= KNEE_CONTACT_MAX_DEG else kh
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
        persons = _kth_high(self._persons)
        if torso_ok is None:
            T = [f for f in S if f.torso] or [f for f in S if f.vis is not None]
            torso_ok = bool(T) and sum(f.prone for f in T) >= TORSO_OK_FRAC * len(T)
        # j3: the incline / decline limit is judged on the support line in world landmarks (metres: a front or
        # diagonal view does not tilt it the way perspective tilts the image line); the image line without world
        sups = [f.tilt for f in S if f.tilt is not None] or [f.sup for f in S if f.sup is not None]
        if sups:
            sup = float(np.median(sups))
            torso_ok = bool(torso_ok) and -float(self.thr["decline_max_deg"]) <= sup <= float(self.thr["incline_max_deg"])
        devs = [f.dev for f in S if f.dev is not None]
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
        kc = _kth_low([f.kc for f in S])
        contact = None if kc is None else bool(kc < float(self.thr["knee_floor_margin"]))
        d_lo, d_hi = _kth_low([f.drop for f in S]), _kth_high([f.drop for f in S])
        drop = d_lo / d_hi if (d_lo is not None and d_hi is not None and d_hi > _EPS) else None
        top, TF = _kth_high([f.elbow for f in F]), F
        if top is None:                              # visible side's arm never confident: the other arm's lockout
            cand = [(v, Fs) for Fs in (wl, wr) if (v := _kth_high([f.elbow for f in Fs])) is not None]
            if cand:
                top, TF = max(cand, key=lambda c: c[0])
        top_w = _kth_high([f.elbow_w for f in TF])
        if top is not None and top_w is not None and top_w > top:
            top = top_w                              # j4: a foreshortened lockout reads straight in world landmarks
        arm_frames = sum(1 for i in sel if wl[i].arm or wr[i].arm)
        return RepMetrics(
            min_elbow_deg_l=_kth_low([_straighter(wl[i].elbow_side, wl[i].elbow_w, ELBOW_WORLD_GAP_DEG)
                                      for i in sel if wl[i].elbow_side is not None]),
            min_elbow_deg_r=_kth_low([_straighter(wr[i].elbow_side, wr[i].elbow_w, ELBOW_WORLD_GAP_DEG)
                                      for i in sel if wr[i].elbow_side is not None]),
            top_elbow_deg=top, max_hip_line_dev_deg=dev,
            min_knee_deg=_kth_low([f.knee for f in S]),
            knee_floor_contact=contact,
            shoulder_wrist_drop=drop,
            min_keypoint_conf=min(f.conf_min for f in S) if (S and side != "none") else 0.0,
            frame_conf_frac=arm_frames / len(sel) if sel else 0.0,
            persons_in_frame=int(persons) if persons is not None else 0,
            rep_duration_s=0.0, torso_ok=bool(torso_ok), side=side, classifier_labels=labels,
            shoulder_elbow_gap=_kth_low([f.gap for f in S]))


def world_hip_dev_deg(s: np.ndarray, h: np.ndarray, a: np.ndarray) -> float | None:
    """Signed hip-line deviation in world landmarks (metres, y down; MediaPipe world is in the camera's orientation):
    180 - the 3-D angle shoulder-hip-ankle, + when the hip lies below the shoulder-ankle line (its offset from the line
    points down), - above. None for a degenerate line."""
    ang = angle_deg(s, h, a)
    u = a - s
    L = float(np.linalg.norm(u))
    if not math.isfinite(ang) or L < _EPS:
        return None
    u = u / L
    off = (h - s) - float((h - s) @ u) * u
    return (180.0 - ang) * (1.0 if off[1] > 0 else -1.0 if off[1] < 0 else 0.0)


def _world_side(world: np.ndarray | None, ix: tuple[int, ...]) -> np.ndarray | None:
    if world is None:
        return None
    W = np.asarray(world, float)[list(ix)]
    return W if np.all(np.isfinite(W)) else None


def _finite(x: float | None) -> float | None:
    return x if x is not None and math.isfinite(x) else None


def _straighter(img: float | None, world: float | None, gap: float = KNEE_WORLD_GAP_DEG) -> float | None:
    """A joint angle: the image reading, or the world reading when that is straighter by more than `gap`
    (a foreshortened limb; small image-world differences are pose noise and keep the image value)."""
    img_v = img if img is not None and math.isfinite(img) else None
    w = world if world is not None and math.isfinite(world) else None
    if img_v is None:
        return w
    return w if w is not None and w - img_v > gap else img_v


def _agree(img: float, world: float | None) -> float | None:
    """Hip deviation: the image value when there is no world value; else the smaller magnitude of the two on the side
    both agree on, 0 when they disagree (no evidence of a fault on either side)."""
    if not math.isfinite(img):
        return None
    if world is None or not math.isfinite(world):
        return img
    if img * world <= 0:
        return 0.0
    return math.copysign(min(abs(img), abs(world)), img)


def _world_tilt(world: np.ndarray | None, wr: int, an: int) -> float | None:
    """Support-line tilt in world landmarks (deg; y down): + wrist higher than the ankle (incline), - lower (decline),
    against the horizontal distance in x/z. None without world landmarks or for a degenerate / non-finite line."""
    if world is None:
        return None
    d = world[an] - world[wr]
    h = math.hypot(float(d[0]), float(d[2]))
    if not (math.isfinite(h) and math.isfinite(float(d[1]))) or (h < _EPS and abs(float(d[1])) < _EPS):
        return None
    return math.degrees(math.atan2(float(d[1]), h))


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
