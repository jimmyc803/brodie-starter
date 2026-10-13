"""The push-up mirror: the caller's own live video with a form skeleton, a camera-angle status and the rep verdicts.

    pm = PushupMirror()                                   # Brodie the mascot (facetime/mascot.py), fonts (facetime/brand.py)
    st = MirrorState()                                    # what the call knows: valid count, last verdict, cue, timer
    st.rep(valid=True, reasons=[], now=t)                 # a judged rep -> count + "GOOD REP +1" / "NO REP" stamp
    img = pm.render(rgb, landmarks, thr, st, now=t)       # (1280, 720, 3) uint8 RGB; rgb=None -> the idle card

rgb is the frame the pose ran on (any size; never modified, never kept beyond the next call); landmarks the pipeline's
(33, 5) normalised x, y, z, visibility, presence (FramePipeline.last_landmarks) for that frame, or None. thr = the live
judge thresholds (challenge.judge.gates; missing keys fall back to DEFAULT_THRESHOLDS). `now` is any monotonic clock
(seconds) shared with MirrorState's times.

Green on screen == passes the strict judge: the per-frame colours use the judge's own definitions (challenge/judge/
metrics.py: angles in height units P = (x * aspect, y), conf = min(visibility, presence) and 0 outside the image, the
six visible-side keypoints at conf >= min_conf, hip_line_dev_deg, a running median of the last 3 values) and its
thresholds: body line red when dev > hip_line_max_dev_deg (sag) or < -hip_pike_max_dev_deg (pike), legs red when the
knee angle < knee_min_deg; arms green at lockout (elbow >= lockout_min_deg) or at depth (<= depth_elbow_max_deg).
The judge's other per-rep gates (knee floor contact, shoulder drop, timing, the classifier veto) have no per-frame
colour: the rep stamp reports them.

Camera status, per new pose with hysteresis (StatusFilter): CAN'T SEE YOU / STEP BACK (head to feet) / TURN SIDEWAYS
(shoulders wide against the torso: a frontal view) / PHONE SIDEWAYS (the picture is a narrow portrait strip, e.g. the
bridge's pillarboxed frame of an upright phone) / GET IN PLANK / CAMERA ANGLE GOOD.

Look: the website's (pushup-web globals.css: paper, ink, pink + yellow, ink borders, hard shadows, condensed display
type) via facetime/brand.py sprites. Layout respects mirror.SAFE_X / SAFE_TOP / SAFE_BOTTOM (FaceTime Fill crops the
sides, the island covers the top, the self-view the bottom left).
"""
from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from challenge.judge.gates import merged_thresholds
from challenge.judge.metrics import SIDES, angle_deg, hip_line_dev_deg
from facetime import brand
from facetime.brand import CANVAS, INK, PINK, YELLOW, GOOD, BAD, WHITE, SURFACE
from facetime.mirror import W, H, SAFE_X, SAFE_TOP, SAFE_BOTTOM

AA = cv2.LINE_AA
FAINT = (215, 215, 210)
TOPBAR_H = SAFE_TOP + 112                  # the top bar's bottom edge (the picture starts here)
PILL_Y = TOPBAR_H + 26                     # camera status pill top
FLASH_Y = TOPBAR_H + 66                    # rep stamp centre (it covers the status pill while it shows)
MASCOT_H = 236                             # Brodie, bottom right, feet just above the self-view line
MASCOT_CX = W - SAFE_X - 96
MASCOT_FEET = SAFE_BOTTOM - 4
FIT = (SAFE_X + 8, TOPBAR_H + 140, W - SAFE_X - 8, MASCOT_FEET - MASCOT_H + 30)   # the body is fitted inside this rectangle
FLASH_S = 1.5; STAMP_S = 0.3; FADE_S = 0.3
CUE_SHOW_S = 4.0
S_MAX = 1.8                                # never zoom the source more than this (output px per source px)
BOX_TAU_S = 0.45                           # crop smoothing time constant
DEADBAND = 0.06                            # crop target moves only when it changed by more than this (fraction of size)

ST_NONE, ST_BACK, ST_SIDE, ST_PHONE, ST_PLANK, ST_GOOD = 'cant_see', 'step_back', 'turn_sideways', 'phone_sideways', 'get_in_plank', 'good'
STATUS_TEXT = {
    ST_NONE: ("CAN'T SEE YOU", 'GET IN FRONT OF THE CAMERA'),
    ST_BACK: ('STEP BACK', 'HEAD TO FEET IN FRAME'),
    ST_SIDE: ('TURN SIDEWAYS', 'SIDE-ON TO THE CAMERA'),
    ST_PHONE: ('PHONE SIDEWAYS', 'TURN YOUR PHONE LANDSCAPE'),
    ST_PLANK: ('GET IN PLANK', 'HANDS DOWN, LEGS STRAIGHT'),
    ST_GOOD: ('CAMERA ANGLE GOOD', None),
}
FRONTAL_RATIO = 0.75                       # shoulder width / torso length above this (body not upright) = facing the camera
FRONTAL_RATIO_ANY = 1.15                   # ... above this whatever the torso angle (plank seen from the head)
PORTRAIT_ASPECT = 0.9                      # content width / height below this = a portrait strip

REASON_TEXT = {
    'multiple_people': 'ONE PERSON ONLY', 'not_in_frame': 'STAY IN FRAME', 'knees_down': 'KNEES DOWN',
    'hips_sag': 'HIPS SAGGING', 'hips_pike': 'HIPS TOO HIGH', 'too_shallow': 'GO LOWER', 'no_lockout': 'LOCK OUT AT THE TOP',
    'too_fast': 'TOO FAST', 'not_horizontal': 'GET IN PLANK', 'not_judged': 'NOT JUDGED', 'liveness_fail': 'LIVENESS CHECK',
}


# ---------------------------------------------------------------------------------------------------- text helpers
def reason_text(reason: str) -> str:
    r = str(reason)
    if r.startswith('classifier:'):
        lab = r.split(':', 1)[1].lower()
        if 'shallow' in lab or 'insufficient' in lab: return 'GO LOWER'
        if 'elevated' in lab or 'pike' in lab: return 'HIPS TOO HIGH'
        if 'sag' in lab: return 'HIPS SAGGING'
        if 'knee' in lab: return 'KNEES DOWN'
        return 'FIX YOUR FORM'
    return REASON_TEXT.get(r, r.replace('_', ' ').upper())


def verdict_lines(valid: bool, reasons) -> tuple[str, str | None]:
    """The stamp after a judged rep: ('GOOD REP +1', None) or ('NO REP', '<short reason>') (the first reason: C5 priority)."""
    if valid: return 'GOOD REP +1', None
    rs = [r for r in (reasons or []) if r]
    return 'NO REP', (reason_text(rs[0]) if rs else None)


# ---------------------------------------------------------------------------------------------------- per-frame analysis
def content_box(rgb, step=4, lit=24, frac=0.03):
    """(x0, y0, x1, y1) pixel box of the non-black picture (pillarbox / letterbox bars trimmed); the whole frame when
    nothing is lit. Subsampled: columns / rows with >= frac of their samples brighter than `lit`."""
    h, w = rgb.shape[:2]
    m = rgb[::step, ::step].max(axis=2) > lit
    cols = np.flatnonzero(m.mean(axis=0) >= frac); rows = np.flatnonzero(m.mean(axis=1) >= frac)
    if not len(cols) or not len(rows): return (0, 0, w, h)
    return (int(cols[0] * step), int(rows[0] * step), min(w, int(cols[-1] * step + step)), min(h, int(rows[-1] * step + step)))


def is_portrait_strip(box) -> bool:
    x0, y0, x1, y1 = box
    return (x1 - x0) < PORTRAIT_ASPECT * max(1, (y1 - y0))


def _conf(lm):
    """The judge's per-keypoint confidence: min(visibility, presence), NaN -> 0, 0 outside the image."""
    c = lm[:, 3].astype(float)
    if lm.shape[1] >= 5: c = np.minimum(c, lm[:, 4].astype(float))
    c = np.nan_to_num(c, nan=0.0)
    inside = np.all((lm[:, :2] >= 0.0) & (lm[:, :2] <= 1.0), axis=1)
    return np.where(inside, c, 0.0)


def side_visibility(lm):
    """Mean visibility of each side's six judge keypoints (the judge's side choice uses the same per-frame number)."""
    v = np.nan_to_num(lm[:, 3].astype(float), nan=0.0)
    return {s: float(v[list(ix)].mean()) for s, ix in SIDES.items()}


def camera_status(lm, aspect, thr=None, side=None, portrait=False):
    """One frame's raw camera status (module docstring). lm: (33, >=4) normalised or None; aspect = frame w / h;
    side: the body side being judged (None: the more visible one); portrait: the picture is a portrait strip."""
    t = merged_thresholds(thr); mc = float(t['min_conf'])
    st = _raw_status(lm, aspect, mc, side)
    return ST_PHONE if (portrait and st != ST_GOOD) else st


def _raw_status(lm, aspect, mc, side):
    if lm is None: return ST_NONE
    lm = np.asarray(lm, dtype=float)
    if lm.ndim != 2 or lm.shape[0] < 33 or lm.shape[1] < 4: return ST_NONE
    c = _conf(lm)
    if max(min(c[11], c[23]), min(c[12], c[24])) < mc: return ST_NONE           # no torso on either side
    P = lm[:, :2] * np.array([aspect, 1.0])
    if c[11] >= mc and c[12] >= mc and c[23] >= mc and c[24] >= mc:
        sw = float(np.linalg.norm(P[11] - P[12]))
        d = (P[11] + P[12]) / 2 - (P[23] + P[24]) / 2; torso = float(np.linalg.norm(d)) + 1e-9
        upright = math.degrees(math.atan2(abs(d[0]), abs(d[1]))) < 35.0              # torso within 35 deg of vertical
        r = sw / torso
        if r > FRONTAL_RATIO_ANY or (r > FRONTAL_RATIO and not upright): return ST_SIDE
    if side is None:
        sv = side_visibility(lm); side = 'right' if sv['right'] > sv['left'] else 'left'
    if np.any(c[list(SIDES[side])] < mc): return ST_BACK
    if not _prone(lm): return ST_PLANK
    return ST_GOOD


def _prone(lm):
    """The judge's prone gate without world landmarks (rtcoach.repcount2 gate_ok('prone') fallback): the image torso
    line (normalised coords) more than 60 deg from vertical."""
    xy = lm[:, :2]; d = (xy[11] + xy[12]) / 2 - (xy[23] + xy[24]) / 2
    return math.degrees(math.atan2(abs(d[0]), abs(d[1]) + 1e-9)) > 60.0


@dataclass
class Form:
    """One frame's judge signals on the judged side (None when unmeasurable), median-filtered like the judge."""
    side: str
    good: bool                 # all six keypoints confident (a judge 'good' frame)
    elbow: float | None = None
    knee: float | None = None
    dev: float | None = None


class _Med3:
    def __init__(self): self.buf = deque(maxlen=3)
    def add(self, x):
        if x is None or not math.isfinite(x): return None
        self.buf.append(float(x)); return float(np.median(self.buf))
    def clear(self): self.buf.clear()


class StatusFilter:
    """Hysteresis: a new raw status is shown once it was seen on `need` consecutive pose updates (CAMERA ANGLE GOOD
    needs one more, so a single good frame does not flash green). The first status is shown at once."""
    def __init__(self, need=3, need_good=4):
        self.need, self.need_good = need, need_good
        self.shown = None; self.cand = None; self.n = 0

    def update(self, raw):
        if self.shown is None: self.shown = raw
        if raw == self.shown:
            self.cand, self.n = None, 0
        elif raw == self.cand:
            self.n += 1
        else:
            self.cand, self.n = raw, 1
        if self.cand is not None and self.n >= (self.need_good if self.cand == ST_GOOD else self.need):
            self.shown, self.cand, self.n = self.cand, None, 0
        return self.shown


@dataclass
class MirrorState:
    """What the call knows beyond the frame (the worker fills it from rep events and the cue player)."""
    count: int = 0                     # valid reps that count
    verdict_ok: bool | None = None
    verdict_reasons: list = field(default_factory=list)
    verdict_t: float = -1e9
    cue: str | None = None
    cue_t: float = -1e9
    speaking: bool = False
    time_left_s: float | None = None   # the count's remaining seconds (None: no timer)
    title: str = 'PUSH-UP CHALLENGE'

    def rep(self, valid, reasons=(), now=None, counts=True):
        """A judged rep: valid + counts -> count + 1; either way the verdict flash restarts."""
        now = time.monotonic() if now is None else now
        if valid and counts: self.count += 1
        self.verdict_ok = bool(valid); self.verdict_reasons = list(reasons or []); self.verdict_t = now

    def say(self, text, now=None):
        self.cue = text; self.cue_t = time.monotonic() if now is None else now


# ---------------------------------------------------------------------------------------------------- the renderer
class PushupMirror:
    """Stateful (smoothed crop, side choice, signal medians, depth-this-rep, status hysteresis): one per call, used
    from one thread at a time."""

    def __init__(self, mascot=True):
        """mascot: True = Brodie (facetime/mascot.py, his common expressions pre-composed here), False = none."""
        self.mascot = self.idle_mascot = None
        if mascot:
            from facetime.mascot import Mascot
            self.mascot = Mascot(MASCOT_H); self.idle_mascot = Mascot(IDLE_MASCOT_H)
            self.mascot.warm(); self.idle_mascot.warm(reactions=False)
        self._idle = None; self._react_t = None; self._bg = None
        self._topbar = self._make_topbar()
        self.thr = merged_thresholds(None)
        self.reset()

    def reset(self):
        self._last_lm = None; self._last_rgb = None; self._last_shape = None; self._last_seq = None
        self._box = None; self._tgt = None; self._t_last = None
        self._content = None; self._portrait = False
        self.side = None; self._side_vis = None
        self._med = {k: _Med3() for k in ('elbow', 'knee', 'dev')}
        self.form = None; self.status_raw = None; self.status = StatusFilter()
        self.depth_hit = False; self._at_top = False; self.depth_frac = 0.0
        self._draw_lm = None

    # -- per new pose -------------------------------------------------------------------------------------------
    def _observe(self, rgb, lm, t):
        h, w = rgb.shape[:2]; aspect = w / h
        self._content = content_box(rgb); self._portrait = is_portrait_strip(self._content)
        a = None
        if lm is not None:
            a = np.asarray(lm, dtype=float)
            if a.ndim != 2 or a.shape[0] < 33 or a.shape[1] < 4: a = None
        if a is None:
            self.form = None; self._draw_lm = None
            for m in self._med.values(): m.clear()
        else:
            sv = side_visibility(a)                                   # sticky side: EMA of the per-side visibility, 0.05 margin
            if self._side_vis is None: self._side_vis = sv
            else: self._side_vis = {k: self._side_vis[k] + 0.3 * (sv[k] - self._side_vis[k]) for k in sv}
            best = 'right' if self._side_vis['right'] > self._side_vis['left'] else 'left'
            if self.side is None or (best != self.side and abs(self._side_vis['right'] - self._side_vis['left']) > 0.05):
                if self.side is not None:
                    for m in self._med.values(): m.clear()
                self.side = best
            self.form = self._form(a, aspect)
            xy = a[:, :2] * np.array([w, h])                       # drawing positions: light EMA (no jitter, little lag)
            if self._draw_lm is None or self._draw_lm.shape != xy.shape: self._draw_lm = xy
            else: self._draw_lm = self._draw_lm + 0.65 * (xy - self._draw_lm)
            self._draw_c = _conf(a)
        self.status_raw = camera_status(a, aspect, self.thr, self.side, self._portrait)
        self.status.update(self.status_raw)
        self._update_depth()
        self._target(a, w, h)

    def _form(self, a, aspect):
        t = self.thr; mc = float(t['min_conf'])
        ix = SIDES[self.side]; c = _conf(a)[list(ix)]
        P = a[list(ix), :2] * np.array([aspect, 1.0])
        sh, el, wr, hp, kn, an = P
        f = Form(side=self.side, good=bool(np.all(c >= mc)))
        arm_ok = bool(np.all(c[:3] >= mc))
        f.elbow = self._med['elbow'].add(angle_deg(sh, el, wr)) if arm_ok else None
        if f.good:
            f.knee = self._med['knee'].add(angle_deg(hp, kn, an))
            f.dev = self._med['dev'].add(hip_line_dev_deg(sh, hp, an))
        return f

    def _update_depth(self):
        """Depth reached this rep: set when the elbow closes to depth_elbow_max_deg; cleared when a new descent starts
        (the elbow leaves the lockout zone, lockout_min_deg - 10 like the judge's top frames)."""
        f = self.form; t = self.thr
        if f is None or f.elbow is None: return
        top = float(t['lockout_min_deg']) - 10.0; depth = float(t['depth_elbow_max_deg'])
        if f.elbow >= top: self._at_top = True
        elif self._at_top:
            self._at_top = False; self.depth_hit = False
        if f.elbow <= depth: self.depth_hit = True
        ref = max(top + 5.0, depth + 1.0)
        self.depth_frac = float(np.clip((ref - f.elbow) / (ref - depth), 0.0, 1.0))

    def _target(self, a, w, h):
        """The crop target (cx, cy, scale) in source pixels: the body box padded (head room, the floor) fitted in FIT."""
        cx0, cy0, cx1, cy1 = self._content; cw, ch = cx1 - cx0, cy1 - cy0
        fw, fh = FIT[2] - FIT[0], FIT[3] - FIT[1]
        pts = None
        if a is not None:
            c = _conf(a); keep = c > 0.3
            keep[17:23] = False                                   # finger points: noisy, the wrist covers them
            if keep.sum() >= 6: pts = a[keep, :2] * np.array([w, h])
        if pts is None:                                           # no pose: the whole picture, as large as fits the band
            s = min(W / cw, (H - TOPBAR_H) / ch)
            tgt = ((cx0 + cx1) / 2, (cy0 + cy1) / 2, s, True)
        else:
            x0, y0 = pts.min(axis=0); x1, y1 = pts.max(axis=0); bw, bh = x1 - x0, y1 - y0
            x0 -= 0.07 * bw + 0.02 * cw; x1 += 0.07 * bw + 0.02 * cw
            y0 -= 0.22 * bh + 0.04 * ch; y1 += 0.08 * bh + 0.03 * ch
            bw, bh = max(x1 - x0, 0.3 * cw), max(y1 - y0, 0.3 * ch)
            s = min(fw / bw, fh / bh, S_MAX)
            tgt = ((x0 + x1) / 2, (y0 + y1) / 2, s, False)
        if self._tgt is None or self._tgt[3] != tgt[3]:
            self._tgt = tgt
        else:                                                     # dead band: small changes keep the old target
            ox, oy, os_, _ = self._tgt
            size = (fw / os_)
            if abs(tgt[0] - ox) > DEADBAND * size or abs(tgt[1] - oy) > DEADBAND * size or abs(math.log(tgt[2] / os_)) > DEADBAND:
                self._tgt = tgt

    def _smooth_box(self, now):
        if self._tgt is None: return
        if self._box is None or self._t_last is None:
            self._box = list(self._tgt[:3])
        else:
            dt = max(0.0, min(1.0, now - self._t_last)); k = 1.0 - math.exp(-dt / BOX_TAU_S)
            b = self._box; t = self._tgt
            b[0] += k * (t[0] - b[0]); b[1] += k * (t[1] - b[1]); b[2] = math.exp(math.log(b[2]) + k * (math.log(t[2]) - math.log(b[2])))
        self._t_last = now

    # -- render -------------------------------------------------------------------------------------------------
    def render(self, rgb, lm, thr=None, state=None, now=None, seq=None):
        """seq: the pose update's id (the pose runs slower than the render): the per-pose analysis (status, medians,
        crop target) runs once per seq. None: once per new (rgb, landmarks) object pair."""
        now = time.monotonic() if now is None else now
        state = state if state is not None else MirrorState()
        self.thr = merged_thresholds(thr)
        if rgb is None:
            return self.idle_card(now, state)
        rgb = np.asarray(rgb)
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] < 8 or rgb.shape[1] < 8:
            raise ValueError(f'expected an HxWx3 RGB frame, got shape {rgb.shape}')
        if seq is not None: fresh = seq != self._last_seq
        else: fresh = (rgb is not self._last_rgb) or (lm is not self._last_lm)
        if rgb.shape != self._last_shape:                          # new resolution: the crop restarts
            self._box = None; self._tgt = None; fresh = True
        if fresh:
            self._observe(rgb, lm, now)
            self._last_lm = lm; self._last_seq = seq
        self._last_rgb = rgb; self._last_shape = rgb.shape
        self._smooth_box(now)
        img = self._picture(rgb)
        if self._draw_lm is not None and lm is not None: self._skeleton(img)
        self._topbar_draw(img, state, now)
        if not self._verdict(img, state, now): self._status_pill(img)
        self._mascot(img, state, now)
        self._caption(img, state, now)
        return img

    def _map(self, x, y):
        cx, cy, s = self._box
        return (FIT[0] + FIT[2]) / 2 + s * (x - cx), (FIT[1] + FIT[3]) / 2 + s * (y - cy)

    def _picture(self, rgb):
        """The canvas: the website's paper with a faint halftone, and the frame mapped by the smoothed box as a card
        (ink border, hard shadow) in the band below the top bar."""
        if self._bg is None: self._bg = self._make_bg()
        img = self._bg.copy()
        cx0, cy0, cx1, cy1 = self._content
        cx, cy, s = self._box
        ox = (FIT[0] + FIT[2]) / 2 - s * cx; oy = (FIT[1] + FIT[3]) / 2 - s * cy
        sx0 = max(cx0, (0 - ox) / s); sx1 = min(cx1, (W - ox) / s)
        sy0 = max(cy0, (TOPBAR_H - oy) / s); sy1 = min(cy1, (H - oy) / s)
        if sx1 - sx0 < 2 or sy1 - sy0 < 2: return img
        dx0 = max(0, int(round(ox + s * sx0))); dx1 = min(W, int(round(ox + s * sx1)))
        dy0 = max(TOPBAR_H, int(round(oy + s * sy0))); dy1 = min(H, int(round(oy + s * sy1)))
        if dx1 <= dx0 or dy1 <= dy0: return img
        cv2.rectangle(img, (dx0 + 9, dy0 + 9), (min(W, dx1 + 9), min(H, dy1 + 9)), INK, -1)       # hard shadow
        crop = rgb[int(sy0):int(math.ceil(sy1)), int(sx0):int(math.ceil(sx1))]
        img[dy0:dy1, dx0:dx1] = cv2.resize(crop, (dx1 - dx0, dy1 - dy0), interpolation=cv2.INTER_AREA if s < 1.0 else cv2.INTER_LINEAR)
        cv2.rectangle(img, (dx0 - 2, dy0 - 2), (dx1 + 1, dy1 + 1), INK, 4)                         # ink border
        return img

    @staticmethod
    def _make_bg():
        img = np.empty((H, W, 3), np.uint8); img[:] = CANVAS
        dots = np.zeros((H, W), np.uint8)
        for y in range(TOPBAR_H + 7, H, 16):
            for x in range(((y // 16) % 2) * 8, W, 16): cv2.circle(dots, (x, y), 2, 255, -1, AA)
        d = dots[..., None].astype(np.float32) / 255.0 * 0.10
        return (img * (1 - d) + np.array(INK, np.float32) * d).astype(np.uint8)

    # -- skeleton -----------------------------------------------------------------------------------------------
    def _colors(self):
        """(body colour, legs colour, arm colour, hip label, knee label) from the judge thresholds."""
        f = self.form; t = self.thr
        body = legs = arm = WHITE; hip_lab = knee_lab = None
        if f is None or self.status.shown != ST_GOOD:              # no form colours until the camera angle is right:
            return body, legs, arm, hip_lab, knee_lab              # from the front the 2-D angles mean nothing
        if f.dev is not None:
            if f.dev > float(t['hip_line_max_dev_deg']): body = BAD; hip_lab = 'HIPS SAGGING'
            elif f.dev < -float(t['hip_pike_max_dev_deg']): body = BAD; hip_lab = 'HIPS TOO HIGH'
            else: body = GOOD
        if f.knee is not None:
            if f.knee < float(t['knee_min_deg']): legs = BAD; knee_lab = 'LEGS STRAIGHT'
            else: legs = GOOD
        if f.elbow is not None:
            if f.elbow >= float(t['lockout_min_deg']) or f.elbow <= float(t['depth_elbow_max_deg']): arm = GOOD
        return body, legs, arm, hip_lab, knee_lab

    def _skeleton(self, img):
        P = [tuple(int(round(v)) for v in self._map(x, y)) for x, y in self._draw_lm]
        c = self._draw_c; mc = float(self.thr['min_conf'])
        side = self.side or 'left'; other = 'right' if side == 'left' else 'left'
        sh, el, wr, hp, kn, an = SIDES[side]
        osh, oel, owr, ohp, okn, oan = SIDES[other]
        ok = lambda *ix: all(c[i] >= 0.35 for i in ix)
        for a, b in ((osh, oel), (oel, owr), (osh, ohp), (ohp, okn), (okn, oan)):     # the far side: thin and faint
            if ok(a, b): cv2.line(img, P[a], P[b], FAINT, 3, AA)
        body, legs, arm, hip_lab, knee_lab = self._colors()
        if hip_lab and ok(sh, an):                                # where the hips should be: the shoulder-ankle line
            self._dashed(img, P[sh], P[an], WHITE)
        thigh = BAD if BAD in (body, legs) else (GOOD if GOOD in (body, legs) else WHITE)
        bones = [(sh, hp, body), (hp, kn, thigh), (kn, an, legs), (sh, el, arm), (el, wr, arm)]
        ear = 7 if side == 'left' else 8; toe = 31 if side == 'left' else 32
        if ok(ear, sh): bones.insert(0, (ear, sh, WHITE))
        if ok(an, toe): bones.append((an, toe, legs))
        for a, b, col in bones:
            if ok(a, b): cv2.line(img, P[a], P[b], INK, 18, AA)
        for a, b, col in bones:
            if ok(a, b): cv2.line(img, P[a], P[b], col, 11, AA)
        if self.form is not None and self.form.elbow is not None and ok(sh, el, wr):
            self._elbow_arc(img, P[sh], P[el], P[wr], arm)
        for i in (sh, el, wr, hp, kn, an):
            if c[i] >= 0.35:
                cv2.circle(img, P[i], 11, INK, -1, AA); cv2.circle(img, P[i], 7, CANVAS, -1, AA)
        if hip_lab and c[hp] >= mc: self._label(img, hip_lab, P[hp], below=(hip_lab == 'HIPS SAGGING'))
        if knee_lab and c[kn] >= mc and not hip_lab: self._label(img, knee_lab, P[kn], below=True)

    @staticmethod
    def _dashed(img, p, q, color, dash=18, gap=12):
        p, q = np.array(p, float), np.array(q, float); L = float(np.linalg.norm(q - p))
        if L < 1: return
        u = (q - p) / L; d = 0.0
        while d < L:
            a = tuple(int(v) for v in p + u * d); b = tuple(int(v) for v in p + u * min(L, d + dash))
            cv2.line(img, a, b, INK, 7, AA); cv2.line(img, a, b, color, 3, AA)
            d += dash + gap

    def _elbow_arc(self, img, s, e, w, col):
        """The elbow-depth indicator: a translucent wedge between upper arm and forearm with the angle in degrees; a
        green tick chip once depth was reached on this rep."""
        r = 42
        a1 = math.degrees(math.atan2(s[1] - e[1], s[0] - e[0])); a2 = math.degrees(math.atan2(w[1] - e[1], w[0] - e[0]))
        d = (a2 - a1 + 540) % 360 - 180
        x0, y0, n = e[0] - r - 2, e[1] - r - 2, 2 * r + 4
        cy0, cx0, cy1, cx1 = max(0, y0), max(0, x0), min(img.shape[0], y0 + n), min(img.shape[1], x0 + n)
        if cy1 <= cy0 or cx1 <= cx0: return
        roi = img[cy0:cy1, cx0:cx1]; over = roi.copy()
        cv2.ellipse(over, (e[0] - cx0, e[1] - cy0), (r, r), 0, a1, a1 + d, col, -1, AA)
        cv2.addWeighted(over, 0.5, roi, 0.5, 0.0, dst=roi)
        cv2.ellipse(img, e, (r, r), 0, a1, a1 + d, INK, 6, AA); cv2.ellipse(img, e, (r, r), 0, a1, a1 + d, col, 3, AA)
        mid = math.radians(a1 + d / 2 + 180)                    # the number sits opposite the wedge
        rgb, a = brand.pill(((f'{int(round(self.form.elbow))}\N{DEGREE SIGN}', 24, INK),), GOOD if self.depth_hit else CANVAS,
                            icon='check' if self.depth_hit else None, pad=(12, 5), border=2, shadow=3)
        h, w_ = a.shape[:2]
        tx = int(e[0] + math.cos(mid) * (r + 34) - w_ / 2); ty = int(e[1] + math.sin(mid) * (r + 30) - h / 2)
        tx = int(np.clip(tx, SAFE_X, W - SAFE_X - w_)); ty = int(np.clip(ty, TOPBAR_H + 4, H - h))
        brand.blit(img, rgb, a, tx, ty)

    def _label(self, img, s, at, below):
        rgb, a = brand.pill(((s, 26, WHITE),), BAD, icon='bang', pad=(14, 6), border=3, shadow=4)
        h, w_ = a.shape[:2]
        x0 = int(np.clip(at[0] - w_ / 2, SAFE_X, W - SAFE_X - w_))
        y0 = at[1] + 30 if below else at[1] - 30 - h
        y0 = int(np.clip(y0, TOPBAR_H + 100, MASCOT_FEET - h))
        brand.blit(img, rgb, a, x0, y0)

    # -- chrome ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _make_topbar():
        bar = np.empty((TOPBAR_H, W, 3), np.uint8); bar[:] = CANVAS
        cv2.rectangle(bar, (0, TOPBAR_H - 5), (W, TOPBAR_H), INK, -1)
        rgb, a = brand.text('BRODIE', 62, INK)
        brand.blit(bar, rgb, a, SAFE_X, SAFE_TOP + 4)
        return bar

    def _topbar_draw(self, img, state, now):
        img[:TOPBAR_H] = self._topbar
        if state.time_left_s is not None:
            sl = max(0, int(math.ceil(state.time_left_s)))
            chip = brand.pill(((f'{sl // 60}:{sl % 60:02d} LEFT', 26, INK),), BAD if sl <= 10 else YELLOW, pad=(14, 5), border=3, shadow=3)
        else:
            chip = brand.pill(((state.title or 'PUSH-UP CHALLENGE', 24, CANVAS),), INK, pad=(12, 5), border=2, shadow=0, radius=3)
        brand.blit(img, *chip, SAFE_X + 2, TOPBAR_H - chip[1].shape[0] - 8)   # clear of the bar's bottom border
        # the count card, right: yellow; green and popping right after a good rep
        since = now - state.verdict_t
        pop = state.verdict_ok is True and 0 <= since < 0.8
        rgb, a = brand.pill((('VALID REPS', 20, INK), (str(state.count), 64, INK)), GOOD if pop else YELLOW, radius=6,
                            pad=(18, 6), border=4, shadow=6, min_w=150, align='center', gap=6)
        if pop:
            k = max(0.0, 1 - since / 0.3)
            rgb, a = brand.transform(rgb, a, 1.0 + 0.16 * k, -4 * k)
        h, w_ = a.shape[:2]
        brand.blit(img, rgb, a, W - SAFE_X - 156 + (156 - w_) // 2, SAFE_TOP - 4 + (112 - h) // 2)

    def _status_pill(self, img):
        st = self.status.shown or ST_NONE
        title, sub = STATUS_TEXT[st]; good = st == ST_GOOD
        lines = ((title, 34, INK),) + (((sub, 22, INK),) if sub else ())
        rgb, a = brand.pill(lines, GOOD if good else YELLOW, icon='check' if good else 'bang', pad=(20, 9), gap=2)
        brand.blit(img, rgb, a, (W - a.shape[1]) // 2, PILL_Y)

    def _verdict(self, img, state, now):
        since = now - state.verdict_t
        if state.verdict_ok is None or not (0 <= since < FLASH_S): return False
        head, detail = verdict_lines(state.verdict_ok, state.verdict_reasons)
        good = state.verdict_ok
        lines = ((head, 52, WHITE),) + (((detail, 28, WHITE),) if detail else ())
        rgb, a = brand.pill(lines, GOOD if good else BAD, icon='check' if good else 'cross', radius=8, pad=(22, 10), border=4, shadow=7, gap=6)
        u = min(1.0, since / STAMP_S)                             # the website's stamp: 1.6 -> 0.96 -> 1
        scale = 1.6 - 0.64 * (u / 0.7) if u < 0.7 else 0.96 + 0.04 * ((u - 0.7) / 0.3)
        rgb, a = brand.transform(rgb, a, scale, 4.0 if good else -3.0)
        op = min(1.0, (FLASH_S - since) / FADE_S) * min(1.0, since / 0.08 + 0.2)
        h, w_ = a.shape[:2]
        brand.blit(img, rgb, a, (W - w_) // 2, FLASH_Y - h // 2, opacity=op)
        return True

    def _caption(self, img, state, now):
        """The current cue as Brodie's speech bubble, left of him."""
        if not state.cue or not (state.speaking or 0 <= now - state.cue_t <= CUE_SHOW_S): return
        maxw = MASCOT_CX - 70 - SAFE_X
        lines = brand.wrap(str(state.cue).upper(), 30, maxw - 44)
        if len(lines) > 3: lines = lines[:3]; lines[2] = lines[2] + '...'
        rgb, a = brand.bubble(tuple(lines), 30, maxw)
        h, w_ = a.shape[:2]
        x1 = MASCOT_CX - 62; y_tail = MASCOT_FEET - int(MASCOT_H * 0.72)
        brand.blit(img, rgb, a, max(SAFE_X - 10, x1 - w_), y_tail - int((h - 8) * 0.62))

    def _mascot(self, img, state, now):
        if self.mascot is None: return
        if state.verdict_t != self._react_t and state.verdict_ok is not None:
            self._react_t = state.verdict_t
            self.mascot.react('good' if state.verdict_ok else 'bad', state.verdict_t)
        self.mascot.draw(img, MASCOT_CX, MASCOT_FEET, now, speaking=state.speaking)

    # -- idle card ------------------------------------------------------------------------------------------------
    def idle_card(self, now, state=None):
        """No caller frame yet: the website hero. Brodie on a pink halftone sunburst, the title, one instruction."""
        if self._idle is None: self._idle = self._make_idle()
        base, rays_img, rays = self._idle
        ang = (now * 15.0) % 360.0                                # 24 s a turn
        M = cv2.getRotationMatrix2D((rays.shape[1] / 2, rays.shape[0] / 2), ang, 1.0)
        M[0, 2] += W / 2 - rays.shape[1] / 2; M[1, 2] += IDLE_SUN_Y - rays.shape[0] / 2
        mask = cv2.warpAffine(rays, M, (W, H), flags=cv2.INTER_NEAREST)
        img = base.copy()
        cv2.copyTo(rays_img, mask, img)
        img[:IDLE_BAND_Y1] = base[:IDLE_BAND_Y1]                  # the title band does not spin
        speaking = bool(state.speaking) if state is not None else False
        if self.idle_mascot is not None:
            self.idle_mascot.draw(img, W // 2, IDLE_FEET, now, speaking=speaking)
        rgb, a = brand.bubble(('STRICT REPS', 'ONLY, BRO.'), 34, 260, tail='none')
        brand.blit(img, *brand.transform(rgb, a, 1.0, 3.0), SAFE_X - 4, IDLE_BAND_Y1 + 26)
        rgb, a = brand.pill((('PHONE SIDEWAYS. HEAD TO FEET IN FRAME.', 26, INK),), CANVAS, radius=6, pad=(18, 10))
        brand.blit(img, rgb, a, (W - a.shape[1]) // 2, IDLE_FEET + 26)
        return img

    @staticmethod
    def _make_idle():
        base = np.empty((H, W, 3), np.uint8); base[:] = PINK
        dark = (np.array(PINK, float) * 0.78 + np.array(INK, float) * 0.22).astype(np.uint8)
        dots = np.zeros((H, W), np.uint8)                         # halftone: ink dots at 20 %
        for y in range(0, H, 14):
            for x in range((y // 14) % 2 * 7, W, 14):
                cv2.circle(dots, (x, y), 2, 255, -1, AA)
        def halftone(img):
            d = dots[..., None].astype(np.float32) / 255.0 * 0.2
            return (img * (1 - d) + np.array(INK, np.float32) * d).astype(np.uint8)
        base = halftone(base)
        rays_img = np.empty((H, W, 3), np.uint8); rays_img[:] = dark; rays_img = halftone(rays_img)
        R = 1500; rays = np.zeros((2 * R, 2 * R), np.uint8)
        for i in range(18):
            a0 = math.radians(i * 20 - 2.3); a1 = math.radians(i * 20 + 2.3)
            pts = np.array([(R, R), (R + 2 * R * math.cos(a0), R + 2 * R * math.sin(a0)), (R + 2 * R * math.cos(a1), R + 2 * R * math.sin(a1))], np.int32)
            cv2.fillConvexPoly(rays, pts, 255, AA)
        # title band: BRODIE huge, then the ink strip like the website poster
        band = base[:IDLE_BAND_Y1]
        band[:] = CANVAS
        rgb, a = brand.text('BRODIE', 150, INK)
        brand.blit(band, rgb, a, (W - a.shape[1]) // 2, SAFE_TOP - 6)
        y = SAFE_TOP + 6 + a.shape[0]
        cv2.rectangle(band, (0, y + 8), (W, IDLE_BAND_Y1), INK, -1)
        rgb, a = brand.text('PUSH-UP CHALLENGE', 44, CANVAS)
        brand.blit(band, rgb, a, (W - a.shape[1]) // 2, y + 8 + (IDLE_BAND_Y1 - y - 8 - a.shape[0]) // 2)
        cv2.rectangle(band, (0, IDLE_BAND_Y1 - 4), (W, IDLE_BAND_Y1), PINK, -1)
        return base, rays_img, rays


IDLE_BAND_Y1 = SAFE_TOP + 250              # bottom of the idle card's title band
IDLE_FEET = SAFE_BOTTOM - 80               # Brodie's feet on the idle card
IDLE_SUN_Y = (IDLE_BAND_Y1 + IDLE_FEET) // 2 + 20
IDLE_MASCOT_H = 430
