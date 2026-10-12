"""Per-rep metric accumulation from per-frame pose landmarks (CONTRACTS C5 / C2 reps columns).

Input: FrameObs per frame. `img` is the MediaPipe (33,5) image-landmark array (x, y, z, visibility, presence), x and y
normalised to [0,1] by frame width / height, y growing DOWNWARD. `aspect` = frame width / height (C5 addition, default
16/9). All geometry is done in "height units": P = (x * aspect, y), i.e. pixels / frame height, so angles are true
image angles regardless of aspect ratio. `world` (33,3) metres, y down, is only used for the torso fallback.

Keypoints per side (MediaPipe): left = shoulder 11, elbow 13, wrist 15, hip 23, knee 25, ankle 27; right = 12, 14, 16,
24, 26, 28. conf(k) = min(visibility, presence) (presence = 1 when the column is absent), NaN -> 0, and 0 when the
landmark lies outside the image ([0,1] in x or y).

Rep window: frames since the previous close_rep (or reset / counting start) with t <= t_fire, further limited to the
last `max_window_s` seconds before t_fire (so setup time before the first rep does not pollute it). Frames with
t > t_fire (rep event delivered late) are carried into the next window.

Metric definitions (n = frames in the window, "good" frames = visible-side frames with all six keypoints at
conf >= min_conf; torso_len = median over good frames of |shoulder - hip| in height units):
  side                  'left'|'right': side whose six keypoints have the higher mean visibility over the window
                        (ties -> left); 'none' when no frame has landmarks.
  frame_conf_frac       (# good frames) / n. 0 when n == 0.
  min_keypoint_conf     min over all window frames of the min visible-side keypoint conf (frames without landmarks = 0).
  persons_in_frame      largest k such that two consecutive frames both report >= k persons (one-frame detector
                        glitches are ignored); the single frame's count when n == 1; 0 when n == 0.
  min_elbow_deg_l / _r  min over frames where that side's shoulder, elbow and wrist are confident of the elbow angle
                        (shoulder-elbow-wrist, degrees, aspect-corrected). Raw per-frame values (no smoothing) so a
                        brief bottom position is not eroded at low fps.
  top_elbow_deg         max visible-side elbow angle over good frames (raw) - the lockout around the rep.
  min_knee_deg          min over good frames of the visible-side hip-knee-ankle angle, after a 3-frame running
                        median (knee/hip/floor are sustained-condition gates, so smoothing only removes jitter).
  max_hip_line_dev_deg  signed hip-line deviation with the largest magnitude over good frames (3-frame median):
                        dev = 180 - angle(shoulder, hip, ankle), signed + when the hip lies below the shoulder-ankle
                        line (larger image y, toward the floor = sag) and - when above (pike).
  knee_floor_contact    floor line = line through the median visible-side wrist point and the median visible-side
                        ankle point over good frames (both rest on the floor in a plank; medians make it robust).
                        knee height = signed distance of the knee from that line, + on the upward side, / torso_len,
                        3-frame median. True iff min knee height < knee_floor_margin. None if the floor line is
                        degenerate (wrist and ankle medians coincide).
  shoulder_elbow_gap    min over good frames of (elbow_y - shoulder_y) / torso_len (raw). <= 0 means the shoulder
                        reached elbow height (the SPEC §6 depth criterion; contract amendment).
  shoulder_wrist_drop   min over good frames of (wrist_y - shoulder_y) / torso_len (raw). Informational only.
  rep_duration_s        t_fire - window start (previous fire, or first frame after reset), not limited by max_window_s.
  cadence_rpm           C5 addition: 60 * 5 / (sum of the last 5 rep durations, this one included) once 5 reps were
                        closed since reset; None before.
  torso_ok              given by the caller (RepCounter2 prone gate) or, when None, computed with
                        rtcoach.repcount2.body_state + gate_ok('prone') per good frame: True iff >= 80% of good frames
                        pass (False when there are no good frames).
Every measured metric is None when no good frame exists (gates.judge_rep then reports not_in_frame).
Angles are rounded to 0.01 deg and ratios to 1e-4 (below float32 `real` storage precision, so re-judging stored
metrics reproduces the live verdict and an exact 90.000 deg bottom is not lost to float error).
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from challenge.judge.gates import merged_thresholds

SIDES = {"left": (11, 13, 15, 23, 25, 27), "right": (12, 14, 16, 24, 26, 28)}
SH, EL, WR, HP, KN, AN = range(6)
CADENCE_REPS = 5
TORSO_OK_FRAC = 0.8
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
    """Angle a-b-c at b in degrees (0..180)."""
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


def _med3(x: np.ndarray) -> np.ndarray:
    if len(x) < 3:
        return x
    p = np.concatenate([x[:1], x, x[-1:]])
    return np.median(np.stack([p[:-2], p[1:-1], p[2:]]), axis=0)


def _sustained_persons(p: list[int]) -> int:
    if not p:
        return 0
    if len(p) == 1:
        return int(p[0])
    return int(max(min(a, b) for a, b in zip(p[:-1], p[1:])))


def _torso_ok_auto(frames: list[FrameObs]) -> bool:
    from rtcoach.repcount2 import body_state, gate_ok
    if not frames:
        return False
    ok = 0
    for f in frames:
        xy = f.img[:, :2]
        torso = float(np.linalg.norm((xy[11] + xy[12]) / 2 - (xy[23] + xy[24]) / 2)) + _EPS
        ok += bool(gate_ok("prone", body_state(f.img, f.world, torso)))
    return ok >= TORSO_OK_FRAC * len(frames)


class RepMetricsAccumulator:
    """Collects frames for the current rep window and turns them into RepMetrics at close_rep. Deterministic."""

    def __init__(self, thr: dict | None = None, max_window_s: float = 6.0):
        self.thr = merged_thresholds(thr)
        self.max_window_s = float(max_window_s)
        self.reset()

    def reset(self) -> None:
        self._frames: list[FrameObs] = []
        self._t_start: float | None = None
        self._durations: deque[float] = deque(maxlen=CADENCE_REPS)

    def add_frame(self, f: FrameObs) -> None:
        if self._t_start is None:
            self._t_start = float(f.t)
        self._frames.append(f)
        horizon = float(f.t) - 2.0 * self.max_window_s   # memory bound; close_rep applies the exact window
        if self._frames[0].t < horizon:
            self._frames = [x for x in self._frames if x.t >= horizon]

    def close_rep(self, t_fire: float, labels: list[str], torso_ok: bool | None = None) -> RepMetrics:
        t_fire = float(t_fire)
        win = [f for f in self._frames if t_fire - self.max_window_s <= f.t <= t_fire]
        self._frames = [f for f in self._frames if f.t > t_fire]
        t0 = self._t_start if self._t_start is not None else t_fire
        duration = max(0.0, t_fire - t0)
        self._t_start = t_fire
        self._durations.append(duration)
        cadence = None
        if len(self._durations) == CADENCE_REPS:
            tot = sum(self._durations)
            cadence = 60.0 * CADENCE_REPS / tot if tot > _EPS else float("inf")
        m = self._metrics(win, list(labels or []), torso_ok)
        m.rep_duration_s = round(duration, 4)
        m.cadence_rpm = None if cadence is None else round(cadence, 4)
        return _rounded(m)

    def _metrics(self, win: list[FrameObs], labels: list[str], torso_ok: bool | None) -> RepMetrics:
        min_conf = float(self.thr["min_conf"])
        posed = [f for f in win if f.img is not None]
        vis = {s: [float(np.nanmean(f.img[list(ix), 3])) for f in posed] for s, ix in SIDES.items()}
        if posed:
            ml, mr = float(np.nanmean(vis["left"])), float(np.nanmean(vis["right"]))
            side = "right" if mr > ml else "left"
        else:
            side = "none"
        ix = SIDES.get(side, SIDES["left"])
        confs = [(_conf(f.img, ix) if f.img is not None else np.zeros(6)) for f in win]
        good = [f for f, c in zip(win, confs) if f.img is not None and bool(np.all(c >= min_conf))]
        n = len(win)
        out = RepMetrics(
            min_elbow_deg_l=self._side_min_elbow(posed, "left", min_conf),
            min_elbow_deg_r=self._side_min_elbow(posed, "right", min_conf),
            top_elbow_deg=None, max_hip_line_dev_deg=None, min_knee_deg=None, knee_floor_contact=None,
            shoulder_wrist_drop=None,
            min_keypoint_conf=float(min(float(c.min()) for c in confs)) if confs else 0.0,
            frame_conf_frac=len(good) / n if n else 0.0,
            persons_in_frame=_sustained_persons([int(f.persons) for f in win]),
            rep_duration_s=0.0,
            torso_ok=bool(torso_ok) if torso_ok is not None else _torso_ok_auto(good),
            side=side, classifier_labels=labels)
        if not good:
            return out
        P = np.stack([f.img[list(ix), :2].astype(float) * np.array([f.aspect, 1.0]) for f in good])  # (g,6,2)
        torso = float(np.median(np.linalg.norm(P[:, SH] - P[:, HP], axis=1)))
        if torso < _EPS:
            return out
        elbow = np.array([angle_deg(p[SH], p[EL], p[WR]) for p in P])
        knee = np.array([angle_deg(p[HP], p[KN], p[AN]) for p in P])
        dev = np.array([hip_line_dev_deg(p[SH], p[HP], p[AN]) for p in P])
        out.top_elbow_deg = _nanext(elbow, np.nanmax)
        out.min_knee_deg = _nanext(_med3(knee), np.nanmin)
        dev_s = _med3(dev)
        if not np.all(np.isnan(dev_s)):
            out.max_hip_line_dev_deg = float(dev_s[int(np.nanargmax(np.abs(dev_s)))])
        out.shoulder_elbow_gap = float(np.min((P[:, EL, 1] - P[:, SH, 1]) / torso))
        out.shoulder_wrist_drop = float(np.min((P[:, WR, 1] - P[:, SH, 1]) / torso))
        w0 = np.median(P[:, WR], axis=0)
        a0 = np.median(P[:, AN], axis=0)
        d = a0 - w0
        L = float(np.linalg.norm(d))
        if L > _EPS:
            nrm = np.array([-d[1], d[0]]) / L
            if nrm[1] > 0:
                nrm = -nrm                   # point up the image (away from the floor)
            h = _med3(((P[:, KN] - w0) @ nrm) / torso)
            out.knee_floor_contact = bool(float(np.min(h)) < float(self.thr["knee_floor_margin"]))
        return out

    @staticmethod
    def _side_min_elbow(posed: list[FrameObs], side: str, min_conf: float) -> float | None:
        s, e, w = SIDES[side][:3]
        vals = []
        for f in posed:
            if np.all(_conf(f.img, (s, e, w)) >= min_conf):
                p = f.img[[s, e, w], :2].astype(float) * np.array([f.aspect, 1.0])
                vals.append(angle_deg(p[0], p[1], p[2]))
        return _nanext(np.array(vals), np.nanmin) if vals else None


_ANGLES = ("min_elbow_deg_l", "min_elbow_deg_r", "top_elbow_deg", "max_hip_line_dev_deg", "min_knee_deg")
_RATIOS = ("shoulder_wrist_drop", "shoulder_elbow_gap", "min_keypoint_conf", "frame_conf_frac")


def _rounded(m: RepMetrics) -> RepMetrics:
    for name, nd in [(a, 2) for a in _ANGLES] + [(r, 4) for r in _RATIOS]:
        v = getattr(m, name)
        if v is not None:
            setattr(m, name, round(float(v), nd))
    return m


def _nanext(x: np.ndarray, fn) -> float | None:
    if x.size == 0 or np.all(np.isnan(x)):
        return None
    return float(fn(x))
