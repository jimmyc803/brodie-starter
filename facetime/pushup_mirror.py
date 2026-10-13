"""The push-up mirror: the caller's own live video with a form skeleton, a camera-angle status and the rep verdicts.

    pm = PushupMirror()                                   # Brodie the mascot (facetime/mascot.py), fonts (facetime/brand.py)
    st = MirrorState()                                    # what the call knows: valid count, last verdict, cue, timer
    st.rep(valid=True, reasons=[], now=t)                 # a judged rep -> count + "GOOD REP +1" / "NO REP" stamp
    img = pm.render(rgb, landmarks, thr, st, now=t)       # (1280, 720, 3) uint8 RGB; rgb=None -> the idle card
    img = pm.render(rgb, landmarks, thr, st, now=t, landscape=True)   # (720, 1280, 3): the caller's phone is sideways

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

Camera status, per new pose with hysteresis (StatusFilter), lenient: CAMERA ANGLE GOOD whenever on one side the
shoulder, elbow, wrist, hip and knee are visible and the pose is plank-like from any reasonable angle (side, diagonal,
front-ish, a higher camera: facetime.frameprep.plank_score); feet may be out of frame. Otherwise SHOW HANDS TO KNEES
(part of that chain missing), GET IN PLANK (all there, not a plank) or CAN'T SEE YOU (no pose). The orientation is
fixed upstream (facetime/frameprep.py turns a sideways portrait-locked phone upright before the pose), so there is no
"turn your phone" nagging.

Layout (720x1280, FaceTime fills the screen with it): an ink header (BRODIE + the timer), the caller's video full-bleed
under it (VID_Y0 down, PANEL_MIN..PANEL_MAX tall) framed by a stable virtual camera (Framer), the status pill and the verdict stamp floating on
the video, and on the paper below the big overprinted valid-rep count with Brodie small on the right, his speech bubble
over the video only while he talks. Look and tokens: the website (pushup-web/app/globals.css: paper, ink, pink + blue
overprint, yellow tickets, ink borders, hard shadows, Anton + Space Mono) via facetime/brand.py sprites. Everything
respects mirror.SAFE_X / SAFE_TOP / SAFE_BOTTOM (FaceTime Fill crops the sides, the island covers the top, the
self-view the bottom left).

Landscape (render(..., landscape=True); the worker's choice when the caller's phone is sideways = its picture needed
turning, see frameprep's orientation lock / OrientationGate): a 1280x720 canvas. The worker never ships it as a
landscape track any more: live calls (2026-10-13) showed FaceTime mangling a track whose size changes mid-call, and a
phone on the floor never rotates its screen, so the card goes pre-turned (frameprep.unrotate, the inverse of the
caller's rotation) on the constant 720x1280 track, which FaceTime fills; the physical turn of the phone reads it upright. The caller's whole
picture, upright, fitted large on an ink panel on the left (no zoom, no pan, whatever follow is), the status pill / stamp
at its top centre; on paper in a right column the BRODIE wordmark + timer, the overprinted count, Brodie small at the
bottom left of the column with his bubble over the picture's corner. Safe area: the LS_* constants (fill crop ~65 px top
and bottom, the island on a short edge, the self-view in a bottom corner). The idle card is always portrait.

Framing (Framer): live (follow=False, the default) the caller's whole picture, never zoomed or moved. With follow=True: the person's keypoint box (head to knees = "core"; with the feet = "full") is collected per pose over
the last WINDOW_S seconds and reduced per edge to its 10th / 90th percentile, so a rep or a jittery landmark does not
move it. The crop is the panel's aspect around that region (padded; head room; feet included only when that costs no
picture height), never zoomed beyond S_MAX output px per source px. The first framing (LOCK_SAMPLES poses) is a cut and
sets the zoom for good: later the crop only pans, when the region leaves the inner safe area of the current crop,
sustained SUSTAIN_S, easing there in EASE_S (it widens only if the person no longer fits; it never zooms in again).
No pose: the last framing holds. The picture is warped once per frame (cubic, a mild unsharp mask on the small source
crop when upscaling, area-averaged when downscaling); the skeleton and overlays are drawn afterwards at output
resolution.
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
from facetime.brand import CANVAS, INK, INK2, PINK, BLUE, YELLOW, GOOD, BAD, WHITE, SURFACE, SITE_GOOD, SITE_BAD, LIVE
from facetime.frameprep import plank_score
from facetime.mirror import W, H, SAFE_X, SAFE_TOP, SAFE_BOTTOM

AA = cv2.LINE_AA
FAINT = (215, 215, 210)
HEAD_H = 150                               # the ink header (the island sits in it)
VID_Y0 = HEAD_H                            # the video panel: full width, from here down PANEL_MIN..PANEL_MAX px (the
PANEL_W = W                                # picture's height at the framing's zoom; a landscape source rarely fills a
PANEL_MIN, PANEL_MAX = 400, 700            # portrait panel, so the panel shrinks to it instead of showing ink bars)
PANEL_ASPECT = PANEL_W / PANEL_MAX
PILL_X, PILL_Y = SAFE_X - 6, VID_Y0 + 22   # camera status pill (top left of the video)
MASCOT_H = 250                             # Brodie, bottom right: his head pops MASCOT_POP px over the video's bottom edge,
MASCOT_POP = 46                            # his feet no lower than MASCOT_FEET (the self-view line)
MASCOT_CX = W - SAFE_X - 118              # (his art + shadow end inside the side margin, so FaceTime's fill crop never cuts him)
MASCOT_FEET = SAFE_BOTTOM - 8
COUNT_X = SAFE_X - 4                       # the count: eyebrow at vid_y1 + 22, the numerals under it
COUNT_PX = (120, 260)                      # the numerals fill the score zone's height, in steps of 10
COUNT_MAX_W = 310                          # ... and never run into Brodie
FLASH_S = 1.5; STAMP_S = 0.55; FADE_S = 0.3
CUE_MIN_S = 1.2                            # a cue bubble shows at least this long (then only while he talks)
S_MAX = 2.0                                # never zoom the source more than this (output px per source px; sharper)
WINDOW_S = 4.0                             # framing: the person's region over this many seconds
SUSTAIN_S = 0.8                            # ... must want a move this long before the camera moves
EASE_S = 1.0                               # ... which then takes this long
SAFE_IN = 0.05                             # the inner safe area: the crop shrunk by this fraction per side
LOCK_SAMPLES = 3                           # poses before the first framing (a cut; the zoom then never changes)
# Landscape (render(..., landscape=True)): the caller holds the phone sideways, so FaceTime shows our track upright on a
# landscape screen and fills it. A 1280x720 (16:9) track on a ~19.5:9 iPhone screen keeps the full width and loses
# LS_CROP_Y = (720 - 1280 * 9 / 19.5) / 2 ~ 65 px top and bottom. The camera island sits mid-way along one short edge
# (left or right, by the way the phone is turned; rounded corners there too) -> LS_SAFE_X on both sides. FaceTime's
# self-view tile sits in a bottom corner of the visible area (~120 x 90 pt + inset on a ~900 x 420 pt screen) ->
# LS_PIP_W x LS_PIP_H keep-out boxes in both bottom corners. All text and key UI (count, status pill, stamp, Brodie,
# timer) stay inside LS_SAFE_X..LW - LS_SAFE_X, LS_SAFE_TOP..LS_SAFE_BOTTOM and out of the keep-outs; the caller's
# picture stays inside the visible band (it may run under the island's edge and the self-view: it is only video).
LW, LH = 1280, 720
LS_CROP_Y = 65
LS_SAFE_X = 72
LS_SAFE_TOP = LS_CROP_Y + 15               # 80
LS_SAFE_BOTTOM = LH - LS_CROP_Y - 15       # 640
LS_PIP_W, LS_PIP_H = 220, 170              # self-view keep-out: x < LS_PIP_W or x > LW - LS_PIP_W, y > LH - LS_CROP_Y - LS_PIP_H
LS_PANEL_X1 = 852                          # the ink video panel: x 0..LS_PANEL_X1, full height
LS_PIC_BOX = (24, LS_SAFE_TOP, LS_PANEL_X1 - 16, LS_SAFE_BOTTOM)   # the picture, whole and upright, fitted (no zoom, no pan)
LS_COL_X0, LS_COL_X1 = LS_PANEL_X1 + 16, LW - LS_SAFE_X             # the right column: header, count, Brodie
LS_MASCOT_H = 180
LS_MASCOT_CX = LS_COL_X0 + 92              # bottom left of the column (his art + shadow end before the self-view keep-out)
LS_MASCOT_FEET = LS_SAFE_BOTTOM
LS_COUNT_PX = (110, 220)
CORE = [i for i in range(0, 17)] + [23, 24, 25, 26]       # head, arms, hips, knees
FULL = CORE + [27, 28, 29, 30, 31, 32]                   # + ankles, heels, toes

ST_NONE, ST_BACK, ST_PLANK, ST_GOOD = 'cant_see', 'step_back', 'get_in_plank', 'good'
STATUS_TEXT = {
    ST_NONE: ("CAN'T SEE YOU", 'GET IN FRAME'),
    ST_BACK: ('SHOW HANDS TO KNEES', 'PHONE A BIT FURTHER AWAY'),
    ST_PLANK: ('GET IN PLANK', 'HANDS DOWN, LEGS STRAIGHT'),
    ST_GOOD: ('CAMERA ANGLE GOOD', None),
}

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


def camera_status(lm, aspect, thr=None, side=None):
    """One frame's raw camera status (module docstring). lm: (33, >=4) normalised or None; aspect = frame w / h;
    side: unused (kept for callers; the check takes whichever side shows the whole chain)."""
    t = merged_thresholds(thr); mc = float(t['min_conf'])
    if lm is None: return ST_NONE
    lm = np.asarray(lm, dtype=float)
    if lm.ndim != 2 or lm.shape[0] < 33 or lm.shape[1] < 4: return ST_NONE
    c = _conf(lm)
    if max(min(c[11], c[23]), min(c[12], c[24])) < mc: return ST_NONE           # no torso on either side
    chain = [(11, 13, 15, 23, 25), (12, 14, 16, 24, 26)]
    if not any(all(c[i] >= mc for i in ix) for ix in chain): return ST_BACK
    return ST_GOOD if plank_score(lm, aspect, mc) > 0 else ST_PLANK


def side_view(lm, aspect):
    """The torso runs across the picture (more than 60 deg from vertical, the judge's prone gate): 2-D body-line and
    knee angles mean something. From the front they do not, so the mirror colours them only from the side."""
    xy = np.asarray(lm, dtype=float)[:, :2] * np.array([aspect, 1.0]); d = (xy[11] + xy[12]) / 2 - (xy[23] + xy[24]) / 2
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


# ---------------------------------------------------------------------------------------------------- the framing
def _smooth(u):
    u = min(1.0, max(0.0, u)); return u * u * (3 - 2 * u)


class Framer:
    """The stable virtual camera (module docstring). Works in source pixels of one frame size: view = (cx, cy, cw),
    the crop centre and width; the crop height is min(cw / PANEL_ASPECT, source height)."""

    def __init__(self, src_w, src_h, follow=False):
        self.w, self.h = float(src_w), float(src_h)
        self.follow = follow                      # False (live default): always the caller's whole picture, never moved
        self.hist = deque()                       # (t, core box, full box or None)
        self.target = self._whole()               # no pose yet: the whole picture
        self.view = self.target
        self.ease = None                          # (t0, from view, to view)
        self.want_t = None                        # since when a move has been wanted
        self.locked = False                       # the zoom is set (first framing)

    def _whole(self):
        cw = max(self.w, self.h * PANEL_ASPECT)   # the whole picture fits the panel (ink beside a tall one)
        return (self.w / 2, self.h / 2, cw)

    def crop_h(self, cw):
        return min(cw / PANEL_ASPECT, self.h)

    def add(self, lm, t):
        """One pose (normalised (33, >=4) landmarks of this frame size, or None: nothing recorded, the framing holds)."""
        if not self.follow: return
        if lm is not None:
            a = np.asarray(lm, dtype=float); c = _conf(a)
            core = [i for i in CORE if c[i] > 0.5]
            if len(core) >= 5:
                P = a[:, :2] * np.array([self.w, self.h])
                cb = (*P[core].min(axis=0), *P[core].max(axis=0))
                full = [i for i in FULL if c[i] > 0.5]
                fb = (*P[full].min(axis=0), *P[full].max(axis=0))
                self.hist.append((t, cb, fb))
        while self.hist and t - self.hist[0][0] > WINDOW_S: self.hist.popleft()
        if not self.hist: return
        if not self.locked:                                          # the first framing: a cut, then the zoom is fixed
            if len(self.hist) < LOCK_SAMPLES: return
            self.target = self.view = self._want(); self.ease = None; self.locked = True; return
        want = self._want()
        cur = self.target
        move = self._outside(cur)
        if not move:
            self.want_t = None; return
        if self.want_t is None: self.want_t = t
        if t - self.want_t >= SUSTAIN_S:                             # frame where the person is now: drop the samples
            while len(self.hist) > 3 and self.hist[0][0] < self.want_t: self.hist.popleft()   # from before the change
            want = self._want(); cw = max(cur[2], want[2])         # a pan at the locked zoom (wider only if the person
            want = self._place(want[0], want[1], cw)                 # no longer fits): it never zooms in again
            self.ease = (t, self.view, want); self.target = want; self.want_t = None

    def _region(self, k):
        b = np.array([h[k] for h in self.hist])
        return (float(np.percentile(b[:, 0], 10)), float(np.percentile(b[:, 1], 10)),
                float(np.percentile(b[:, 2], 90)), float(np.percentile(b[:, 3], 90)))

    def _outside(self, view):
        """The robust core region leaves the inner safe area of `view`."""
        x0, y0, x1, y1 = self._region(1)
        cx, cy, cw = view; ch = self.crop_h(cw)
        mx, my = SAFE_IN * cw, SAFE_IN * ch
        vx0, vx1 = max(0.0, cx - cw / 2) + mx, min(self.w, cx + cw / 2) - mx
        vy0, vy1 = max(0.0, cy - ch / 2) + my, min(self.h, cy + ch / 2) - my
        return x0 < vx0 or x1 > vx1 or y0 < vy0 or y1 > vy1

    def _want(self):
        x0, y0, x1, y1 = self._region(1); bw, bh = x1 - x0, y1 - y0
        x0 -= 0.10 * bw + 0.03 * self.w; x1 += 0.10 * bw + 0.03 * self.w
        y0 -= 0.30 * bh + 0.03 * self.h; y1 += 0.15 * bh + 0.03 * self.h
        cw = max(x1 - x0, (y1 - y0) * PANEL_ASPECT)
        fx0, _, fx1, _ = self._region(2)
        fw = (fx1 - fx0) * 1.08 + 0.04 * self.w
        fill = self.h * PANEL_ASPECT                                 # widest crop that still fills the panel height
        if fw <= max(cw, fill):                                      # the feet too, when that costs no picture height
            cw = max(cw, fw); x0, x1 = min(x0, fx0 - 0.02 * self.w), max(x1, fx1 + 0.02 * self.w)
        cw = max(min(cw, max(self.w, (y1 - y0) * PANEL_ASPECT)), PANEL_W / S_MAX)   # wider than the source only for height
        return self._place((x0 + x1) / 2, (y0 + y1) / 2, cw)

    def _place(self, cx, cy, cw):
        """(cx, cy, cw) clamped so the crop stays on the picture."""
        ch = self.crop_h(cw)
        cx = min(max(cx, cw / 2), self.w - cw / 2) if cw <= self.w else self.w / 2
        cy = min(max(cy, ch / 2), self.h - ch / 2)
        return (cx, cy, cw)

    def update(self, now):
        """The view at `now` (eased toward the target)."""
        if self.ease is None: self.view = self.target; return self.view
        t0, a, b = self.ease; u = _smooth((now - t0) / EASE_S)
        if u >= 1.0: self.ease = None; self.view = b; return b
        self.view = (a[0] + u * (b[0] - a[0]), a[1] + u * (b[1] - a[1]), math.exp(math.log(a[2]) + u * (math.log(b[2]) - math.log(a[2]))))
        return self.view

    def matrix(self, view=None):
        """(2x3 affine source px -> output px, the panel's bottom row) for `view`."""
        cx, cy, cw = view or self.view; ch = self.crop_h(cw); s = PANEL_W / cw
        ph = ch * s; panel = min(PANEL_MAX, max(PANEL_MIN, ph)); oy = VID_Y0 + (panel - ph) / 2
        M = np.array([[s, 0.0, -s * (cx - cw / 2)], [0.0, s, oy - s * (cy - ch / 2)]], np.float64)
        return M, int(round(VID_Y0 + panel))


# ---------------------------------------------------------------------------------------------------- the renderer
class PushupMirror:
    """Stateful (framing, side choice, signal medians, depth-this-rep, status hysteresis): one per call, used from one
    thread at a time."""

    def __init__(self, mascot=True, follow=False):
        self.follow = follow                                         # True: the person-following crop (Framer)
        """mascot: True = Brodie (facetime/mascot.py, his common expressions pre-composed here), False = none."""
        self.mascot = self.idle_mascot = self.ls_mascot = None
        if mascot:
            from facetime.mascot import Mascot
            self.mascot = Mascot(MASCOT_H); self.idle_mascot = Mascot(IDLE_MASCOT_H); self.ls_mascot = Mascot(LS_MASCOT_H)
            self.mascot.warm(); self.idle_mascot.warm(reactions=False); self.ls_mascot.warm()
        self._idle = None; self._react_t = None; self._paper = None; self._head = None; self.vid_y1 = VID_Y0 + PANEL_MAX
        self._ls_base = None                                         # landscape: (picture box, cached static canvas)
        self.boxes = {}                                              # the last frame's element boxes (x0, y0, x1, y1), output px
        self._clip = (0, VID_Y0, W, self.vid_y1); self._xlim = (SAFE_X, W - SAFE_X); self._label_y0 = PILL_Y + 80
        self.thr = merged_thresholds(None)
        self.reset()

    def reset(self):
        self._last_lm = None; self._last_rgb = None; self._last_shape = None; self._last_seq = None
        self.framer = None
        self.side = None; self._side_vis = None; self._side_view = False
        self._med = {k: _Med3() for k in ('elbow', 'knee', 'dev')}
        self.form = None; self.status_raw = None; self.status = StatusFilter()
        self.depth_hit = False; self._at_top = False; self.depth_frac = 0.0
        self._draw_lm = None; self._draw_c = None; self._shown_cue_t = None

    # -- per new pose -------------------------------------------------------------------------------------------
    def _observe(self, rgb, lm, t):
        h, w = rgb.shape[:2]; aspect = w / h
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
            self._side_view = side_view(a, aspect)
            xy = a[:, :2] * np.array([w, h])                       # drawing positions: light EMA (no jitter, little lag)
            if self._draw_lm is None or self._draw_lm.shape != xy.shape: self._draw_lm = xy
            else: self._draw_lm = self._draw_lm + 0.65 * (xy - self._draw_lm)
            self._draw_c = _conf(a)
        self.status_raw = camera_status(a, aspect, self.thr, self.side)
        self.status.update(self.status_raw)
        self._update_depth()
        self.framer.add(a, t)

    def _form(self, a, aspect):
        t = self.thr; mc = float(t['min_conf'])
        ix = SIDES[self.side]; c = _conf(a)[list(ix)]
        P = a[list(ix), :2] * np.array([aspect, 1.0])
        sh, el, wr, hp, kn, an = P
        f = Form(side=self.side, good=bool(np.all(c >= mc)))
        arm_ok = bool(np.all(c[:3] >= mc))
        f.elbow = self._med['elbow'].add(angle_deg(sh, el, wr)) if arm_ok else None
        if bool(np.all(c[[0, 3, 4]] >= mc)):                        # body line + knee need shoulder, hip, knee (+ ankle)
            if c[5] >= mc:
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

    # -- render -------------------------------------------------------------------------------------------------
    def render(self, rgb, lm, thr=None, state=None, now=None, seq=None, landscape=False):
        """seq: the pose update's id (the pose runs slower than the render): the per-pose analysis (status, medians,
        framing) runs once per seq. None: once per new (rgb, landmarks) object pair. rgb may be a newer frame of the
        same size than the one the landmarks came from (the skeleton then lags it by a frame). landscape: the caller's
        phone is sideways -> a (LH, LW, 3) = (720, 1280, 3) canvas (the idle card stays portrait)."""
        now = time.monotonic() if now is None else now
        state = state if state is not None else MirrorState()
        self.thr = merged_thresholds(thr)
        self.boxes = {}
        if rgb is None:
            return self.idle_card(now, state)
        rgb = np.asarray(rgb)
        if rgb.ndim != 3 or rgb.shape[2] != 3 or rgb.shape[0] < 8 or rgb.shape[1] < 8:
            raise ValueError(f'expected an HxWx3 RGB frame, got shape {rgb.shape}')
        if seq is not None: fresh = seq != self._last_seq
        else: fresh = (rgb is not self._last_rgb) or (lm is not self._last_lm)
        if rgb.shape != self._last_shape or self.framer is None:     # new picture size: the framing restarts
            self.framer = Framer(rgb.shape[1], rgb.shape[0], self.follow); fresh = True; self._draw_lm = None
        if fresh:
            self._observe(rgb, lm, now)
            self._last_lm = lm; self._last_seq = seq
        self._last_rgb = rgb; self._last_shape = rgb.shape
        self.framer.update(now)
        if landscape: return self._render_landscape(rgb, lm, state, now)
        M, self.vid_y1 = self.framer.matrix()
        self._clip = (0, VID_Y0, W, self.vid_y1); self._xlim = (SAFE_X, W - SAFE_X); self._label_y0 = PILL_Y + 80
        img = self._base()
        self._picture(img, rgb, M)
        h, w = rgb.shape[:2]; c = M @ np.array([[0, 0, 1], [w, h, 1]], float).T
        self.boxes['picture'] = (max(0, int(c[0, 0])), max(VID_Y0, int(c[1, 0])), min(W, int(math.ceil(c[0, 1]))), min(self.vid_y1, int(math.ceil(c[1, 1]))))
        if self._draw_lm is not None and lm is not None: self._skeleton(img, M)
        self._header(img, state, now)
        self._count(img, state, now)
        self._mascot(img, state, now)
        if not self._verdict(img, state, now): self._status_pill(img)
        self._caption(img, state, now)
        return img

    def _base(self):
        """The static layers for this frame's panel height: paper everywhere, the ink header, the ink panel ground and
        the ink rule under it."""
        if self._paper is None: self._paper, self._head = self._make_paper(), self._make_header()
        img = self._paper.copy(); y1 = self.vid_y1
        img[:HEAD_H] = self._head; img[HEAD_H:y1] = INK; img[y1:y1 + 5] = INK
        return img

    def _picture(self, img, rgb, M, rect=None):
        """The framed video into the panel (ink where the picture does not reach), with the source -> output affine M.
        rect: the output box (x0, y0, x1, y1) it may cover (default: the portrait panel)."""
        s = M[0, 0]
        X0, Y0, X1, Y1 = rect if rect is not None else (0, VID_Y0, PANEL_W, self.vid_y1)
        h, w = rgb.shape[:2]
        # the source rows / columns the panel needs (+ a margin for the filter taps)
        x0 = max(0, int(math.floor((X0 - M[0, 2]) / s)) - 3); x1 = min(w, int(math.ceil((X1 - M[0, 2]) / s)) + 3)
        y0 = max(0, int(math.floor((Y0 - M[1, 2]) / s)) - 3); y1 = min(h, int(math.ceil((Y1 - M[1, 2]) / s)) + 3)
        if x1 - x0 < 2 or y1 - y0 < 2: return
        src = rgb[y0:y1, x0:x1]
        A = M.copy(); A[0, 2] += s * x0 - X0; A[1, 2] += s * y0 - Y0      # roi px -> panel px
        if s < 0.95:                                                  # downscale: area-average first, then place sub-pixel
            nw, nh = max(2, int(round(src.shape[1] * s))), max(2, int(round(src.shape[0] * s)))
            fx, fy = nw / src.shape[1], nh / src.shape[0]
            src = cv2.resize(src, (nw, nh), interpolation=cv2.INTER_AREA)
            A[0, 0] /= fx; A[1, 1] /= fy
            flags = cv2.INTER_LINEAR
        else:
            if s > 1.25:                                              # mild unsharp mask on the small source crop
                blur = cv2.GaussianBlur(src, (0, 0), 1.0)
                src = cv2.addWeighted(src, 1.6, blur, -0.6, 0)
            flags = cv2.INTER_CUBIC
        panel = img[Y0:Y1, X0:X1]
        if panel.flags['C_CONTIGUOUS']:
            cv2.warpAffine(src, A, (X1 - X0, Y1 - Y0), dst=panel, flags=flags, borderMode=cv2.BORDER_TRANSPARENT)
        else:                                                         # a column band (landscape): OpenCV needs contiguous dst
            out = np.ascontiguousarray(panel)
            cv2.warpAffine(src, A, (X1 - X0, Y1 - Y0), dst=out, flags=flags, borderMode=cv2.BORDER_TRANSPARENT)
            panel[:] = out

    @staticmethod
    def _make_paper():
        """The score zone's paper (the site's .stage: pink and blue ink bleeds, a faint halftone), full canvas size."""
        top = VID_Y0 + PANEL_MIN
        img = np.empty((H, W, 3), np.uint8); img[:] = CANVAS
        z = np.empty((H - top, W, 3), np.float32); z[:] = CANVAS
        yy, xx = np.mgrid[0:H - top, 0:W].astype(np.float32)
        def bleed(cx, cy, rx, ry, col, k):
            d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            a = (np.clip(1 - d / 0.62, 0, 1) * k)[..., None]
            return a, np.array(col, np.float32)
        for cx, cy, rx, ry, col, k in ((W * 1.08, -40, 760, 520, PINK, 0.16), (-0.12 * W, 300, 640, 460, BLUE, 0.09)):
            a, c = bleed(cx, cy, rx, ry, col, k); z = z * (1 - a) + c * a
        dots = np.zeros((H - top, W), np.uint8)
        for y in range(5, H - top, 10):
            for x in range(((y // 10) % 2) * 5, W, 10): cv2.circle(dots, (x, y), 1, 255, -1, AA)
        d = dots[..., None].astype(np.float32) / 255.0 * 0.07
        z = z * (1 - d) + np.array(INK, np.float32) * d
        img[top:] = np.clip(z, 0, 255).astype(np.uint8)
        return img

    @staticmethod
    def _make_header():
        img = np.empty((HEAD_H, W, 3), np.uint8); img[:] = INK
        rgb, a = brand.text('BRODIE', 58, CANVAS)
        brand.blit(img, rgb, a, SAFE_X - 2, HEAD_H - 22 - a.shape[0] - 18)
        rgb, a = brand.text('PUSH-UP CHALLENGE', 13, PINK, face='mono')
        brand.blit(img, rgb, a, SAFE_X, HEAD_H - 22 - a.shape[0] + 2)
        cv2.rectangle(img, (0, HEAD_H - 4), (W, HEAD_H), PINK, -1)
        return img

    # -- skeleton -----------------------------------------------------------------------------------------------
    def _colors(self):
        """(body colour, legs colour, arm colour, hip label, knee label) from the judge thresholds."""
        f = self.form; t = self.thr
        body = legs = arm = WHITE; hip_lab = knee_lab = None
        if f is None or self.status.shown != ST_GOOD:              # no form colours until the camera angle is right
            return body, legs, arm, hip_lab, knee_lab
        if self._side_view:                                        # body line and knee: only meaningful from the side
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

    def _skeleton(self, img, M):
        S = 4                                                      # sub-pixel drawing (shift = 2 bits)
        xy = self._draw_lm @ M[:, :2].T + M[:, 2]
        P = [(int(round(x * S)), int(round(y * S))) for x, y in xy]
        Pi = [(int(round(x)), int(round(y))) for x, y in xy]
        c = self._draw_c; mc = float(self.thr['min_conf'])
        side = self.side or 'left'; other = 'right' if side == 'left' else 'left'
        sh, el, wr, hp, kn, an = SIDES[side]
        osh, oel, owr, ohp, okn, oan = SIDES[other]
        ok = lambda *ix: all(c[i] >= 0.35 for i in ix)
        cx0, cy0, cx1, cy1 = self._clip
        clip = img[cy0:cy1, cx0:cx1]                               # the skeleton stays on the video
        Q = [(x - cx0 * S, y - cy0 * S) for x, y in P]
        for a, b in ((osh, oel), (oel, owr), (osh, ohp), (ohp, okn), (okn, oan)):     # the far side: thin and faint
            if ok(a, b): cv2.line(clip, Q[a], Q[b], FAINT, 3, AA, 2)
        body, legs, arm, hip_lab, knee_lab = self._colors()
        if hip_lab and ok(sh, an):                                # where the hips should be: the shoulder-ankle line
            self._dashed(clip, (Pi[sh][0] - cx0, Pi[sh][1] - cy0), (Pi[an][0] - cx0, Pi[an][1] - cy0), WHITE)
        thigh = BAD if BAD in (body, legs) else (GOOD if GOOD in (body, legs) else WHITE)
        bones = [(sh, hp, body), (hp, kn, thigh), (kn, an, legs), (sh, el, arm), (el, wr, arm)]
        ear = 7 if side == 'left' else 8; toe = 31 if side == 'left' else 32
        if ok(ear, sh): bones.insert(0, (ear, sh, WHITE))
        if ok(an, toe): bones.append((an, toe, legs))
        for a, b, col in bones:
            if ok(a, b): cv2.line(clip, Q[a], Q[b], INK, 16, AA, 2)
        for a, b, col in bones:
            if ok(a, b): cv2.line(clip, Q[a], Q[b], col, 9, AA, 2)
        if self.form is not None and self.form.elbow is not None and ok(sh, el, wr):
            self._elbow_arc(img, Pi[sh], Pi[el], Pi[wr], arm)
        for i in (sh, el, wr, hp, kn, an):
            if c[i] >= 0.35:
                cv2.circle(clip, Q[i], 10 * S, INK, -1, AA, 2); cv2.circle(clip, Q[i], 6 * S, CANVAS, -1, AA, 2)
        if hip_lab and c[hp] >= mc: self._label(img, hip_lab, Pi[hp], below=(hip_lab == 'HIPS SAGGING'))
        if knee_lab and c[kn] >= mc and not hip_lab: self._label(img, knee_lab, Pi[kn], below=True)

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
        """The elbow-depth indicator: a translucent wedge between upper arm and forearm (green at lockout or depth); a
        DEEP tick chip once depth was reached on this rep."""
        r = 40
        px0, py0, px1, py1 = self._clip
        if not (py0 + r < e[1] < py1 - r and px0 + r < e[0] < px1 - r): return
        a1 = math.degrees(math.atan2(s[1] - e[1], s[0] - e[0])); a2 = math.degrees(math.atan2(w[1] - e[1], w[0] - e[0]))
        d = (a2 - a1 + 540) % 360 - 180
        x0, y0, n = e[0] - r - 2, e[1] - r - 2, 2 * r + 4
        cy0, cx0, cy1, cx1 = max(0, y0), max(0, x0), min(img.shape[0], y0 + n), min(img.shape[1], x0 + n)
        if cy1 <= cy0 or cx1 <= cx0: return
        roi = img[cy0:cy1, cx0:cx1]; over = roi.copy()
        cv2.ellipse(over, (e[0] - cx0, e[1] - cy0), (r, r), 0, a1, a1 + d, col, -1, AA)
        cv2.addWeighted(over, 0.45, roi, 0.55, 0.0, dst=roi)
        cv2.ellipse(img, e, (r, r), 0, a1, a1 + d, INK, 6, AA); cv2.ellipse(img, e, (r, r), 0, a1, a1 + d, col, 3, AA)
        if not self.depth_hit: return
        mid = math.radians(a1 + d / 2 + 180)                    # depth reached this rep: a DEEP tick chip opposite the wedge
        rgb, a = brand.pill((('DEEP', 22, INK),), GOOD, icon='check', radius=4, pad=(10, 4), border=2, shadow=3)
        h, w_ = a.shape[:2]
        tx = int(e[0] + math.cos(mid) * (r + 30) - w_ / 2); ty = int(e[1] + math.sin(mid) * (r + 26) - h / 2)
        tx = int(np.clip(tx, self._xlim[0], self._xlim[1] - w_)); ty = int(np.clip(ty, py0 + 4, py1 - h - 4))
        brand.blit(img, rgb, a, tx, ty)

    def _label(self, img, s, at, below):
        rgb, a = brand.pill(((s, 26, WHITE),), SITE_BAD, radius=4, pad=(12, 5), border=3, shadow=4)
        h, w_ = a.shape[:2]
        x0 = int(np.clip(at[0] - w_ / 2, self._xlim[0], self._xlim[1] - w_))
        y0 = at[1] + 30 if below else at[1] - 30 - h
        y0 = int(np.clip(y0, self._label_y0, self._clip[3] - h - 8))
        brand.blit(img, rgb, a, x0, y0)

    # -- chrome ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _timer_chip(state):
        """The timer ticket (yellow; red in the last 10 s) or the site's LIVE chip: a sprite."""
        if state.time_left_s is not None:
            sl = max(0, int(math.ceil(state.time_left_s)))
            chip = brand.pill(((f'{sl // 60}:{sl % 60:02d}', 40, INK), ('LEFT', 12, INK, 'mono')), SITE_BAD if sl <= 10 else YELLOW,
                              radius=4, pad=(14, 6), border=3, shadow=0, gap=4, align='center')
            return brand.transform(*chip, 1.0, 2.0)
        return brand.pill((('LIVE', 20, INK, 'mono'),), CANVAS, icon='dot', icon_fill=LIVE, icon_px=18, radius=2,
                          pad=(14, 9), border=3, shadow=0)

    def _blit(self, img, name, rgb, a, x, y, opacity=1.0):
        """brand.blit + the element's box in self.boxes (the layout tests read them)."""
        brand.blit(img, rgb, a, x, y, opacity=opacity)
        h, w_ = a.shape[:2]; self.boxes[name] = (int(x), int(y), int(x) + w_, int(y) + h)

    def _header(self, img, state, now):
        """The header's right side: the timer ticket or the LIVE chip."""
        chip = self._timer_chip(state)
        h, w_ = chip[1].shape[:2]
        self._blit(img, 'timer', *chip, W - SAFE_X - w_ + 4, HEAD_H - 20 - h)

    def _count(self, img, state, now):
        """The valid-rep count under the video (portrait)."""
        cy = self.vid_y1 + 24
        self._count_at(img, state, now, COUNT_X, cy, (MASCOT_FEET - cy - 36) / 0.9, COUNT_PX, COUNT_MAX_W)

    def _count_at(self, img, state, now, x, cy, fit_px, px_range, max_w):
        """The valid-rep count: the site's overprint numerals (pink, blue misregistration) under a mono eyebrow at (x, cy);
        numerals of fit_px clamped to px_range (steps of 10), narrower than max_w; a valid rep pops it and stamps a +1."""
        rgb, a = brand.text('VALID REPS', 15, INK2, face='mono')
        brand.blit(img, rgb, a, x + 4, cy)
        since = now - state.verdict_t
        pop = state.verdict_ok is True and 0 <= since < 0.6
        px = int(min(px_range[1], max(px_range[0], fit_px)) // 10 * 10)
        while px > px_range[0] and brand.text_size(str(state.count), px)[0] > max_w: px -= 10
        rgb, a = brand.text(str(state.count), px, PINK, offset=(px / 24, px / 28), offset_color=BLUE)
        y = cy + 26
        if pop:
            k = _smooth(1 - since / 0.6)
            rgb, a = brand.transform(rgb, a, 1.0 + 0.14 * k, 0.0)
            y -= int(0.07 * k * a.shape[0])
        self._blit(img, 'count', rgb, a, x, y)
        if pop:
            plus = brand.pill((('+1', 34, INK),), YELLOW, radius=4, pad=(10, 2), border=3, shadow=4)
            plus = brand.transform(*plus, 1.0, -6.0)
            brand.blit(img, *plus, x + a.shape[1] + 8, y + 10 - int(20 * min(1.0, since / 0.6)), opacity=min(1.0, (0.6 - since) / 0.2))

    def _pill_sprite(self):
        st = self.status.shown or ST_NONE
        title, sub = STATUS_TEXT[st]; good = st == ST_GOOD
        lines = ((title, 30, INK),) + (((sub, 12, INK2, 'mono'),) if sub else ())
        return brand.pill(lines, SURFACE if good else YELLOW, icon='dot', icon_fill=GOOD if good else (LIVE if st == ST_NONE else YELLOW),
                          icon_px=16, radius=4, pad=(14, 8), border=3, shadow=5, gap=5)

    def _status_pill(self, img):
        self._blit(img, 'pill', *self._pill_sprite(), PILL_X, PILL_Y)

    def _stamp_sprite(self, state, now):
        """The verdict stamp now: (rgb, alpha, opacity), or None outside its flash."""
        since = now - state.verdict_t
        if state.verdict_ok is None or not (0 <= since < FLASH_S): return None
        head, detail = verdict_lines(state.verdict_ok, state.verdict_reasons)
        good = state.verdict_ok
        lines = ((head, 54, WHITE),) + (((detail, 15, WHITE, 'mono'),) if detail else ())
        rgb, a = brand.pill(lines, SITE_GOOD if good else SITE_BAD, radius=4, pad=(22, 10), border=4, shadow=7, gap=8, align='center')
        u = min(1.0, since / STAMP_S)                             # the site's stamp: 1.6 -> 0.96 -> 1, rotated
        scale = 1.6 - 0.64 * (u / 0.7) if u < 0.7 else 0.96 + 0.04 * ((u - 0.7) / 0.3)
        rgb, a = brand.transform(rgb, a, scale, 6.0 if good else -6.0)
        op = min(1.0, (FLASH_S - since) / FADE_S) * min(1.0, since / 0.08 + 0.2)
        return rgb, a, op

    def _verdict(self, img, state, now):
        s = self._stamp_sprite(state, now)
        if s is None: return False
        rgb, a, op = s; h, w_ = a.shape[:2]
        self._blit(img, 'stamp', rgb, a, (W - w_) // 2, PILL_Y + 40 - h // 2 + 16, opacity=op)
        return True

    @staticmethod
    def _cue_lines(state, px, max_w):
        lines = brand.wrap(str(state.cue).upper(), px, max_w)
        if len(lines) > 3: lines = lines[:3]; lines[2] = lines[2] + '...'
        return tuple(lines)

    @staticmethod
    def _cue_on(state, now):
        return bool(state.cue) and (state.speaking or 0 <= now - state.cue_t <= CUE_MIN_S)

    def _caption(self, img, state, now):
        """The current cue as Brodie's speech bubble above him (over the bottom of the video), its tail at his head;
        only while he talks (at least CUE_MIN_S)."""
        if not self._cue_on(state, now): return
        maxw = W - 2 * SAFE_X + 12
        rgb, a = brand.bubble(self._cue_lines(state, 30, maxw - 44), 30, maxw, tail='down', radius=4, tail_at=0.8)
        h, w_ = a.shape[:2]
        x = min(W - SAFE_X - w_ + 12, MASCOT_CX - int(0.8 * w_))
        self._blit(img, 'bubble', rgb, a, max(SAFE_X - 6, x), self._mascot_feet() - MASCOT_H - h + 2)

    def _mascot(self, img, state, now, m=None, cx=MASCOT_CX, feet=None):
        """Brodie (m: which mascot, default the portrait one) centred on cx, feet on feet; both mascots react to a verdict."""
        if self.mascot is None: return
        if state.verdict_t != self._react_t and state.verdict_ok is not None:
            self._react_t = state.verdict_t
            for mm in (self.mascot, self.ls_mascot):
                if mm is not None: mm.react('good' if state.verdict_ok else 'bad', state.verdict_t)
        m = m or self.mascot; feet = self._mascot_feet() if feet is None else feet
        m.draw(img, cx, feet, now, speaking=state.speaking)
        hw = m.art_w / 2; self.boxes['mascot'] = (int(cx - hw), int(feet - m.height), int(math.ceil(cx + hw)), int(feet))

    def _mascot_feet(self):
        return min(MASCOT_FEET, self.vid_y1 + MASCOT_H - MASCOT_POP)

    # -- landscape (the caller's phone held sideways) ----------------------------------------------------------------
    def _ls_fit(self, rgb):
        """The source -> output affine that fits the whole picture, upright, into LS_PIC_BOX (centred; no zoom past the
        box, no pan), and the picture's output box."""
        h, w = rgb.shape[:2]; bx0, by0, bx1, by1 = LS_PIC_BOX
        s = min((bx1 - bx0) / w, (by1 - by0) / h)
        pw, ph = int(round(w * s)), int(round(h * s))
        x0 = bx0 + (bx1 - bx0 - pw) // 2; y0 = by0 + (by1 - by0 - ph) // 2
        M = np.array([[s, 0.0, float(x0)], [0.0, s, float(y0)]], np.float64)
        return M, (x0, y0, x0 + pw, y0 + ph)

    def _ls_make_base(self, pic):
        """The static landscape canvas for a picture box: paper (the site's bleeds + halftone), the ink video panel with a
        pink rule, the column's wordmark + eyebrow and an ink rule under them."""
        img = np.empty((LH, LW, 3), np.uint8); img[:] = CANVAS
        z = np.empty((LH, LW - LS_PANEL_X1, 3), np.float32); z[:] = CANVAS
        yy, xx = np.mgrid[0:LH, 0:LW - LS_PANEL_X1].astype(np.float32)
        for cx, cy, rx, ry, col, k in ((LW - LS_PANEL_X1 + 60, -20, 560, 520, PINK, 0.16), (-60, LH + 40, 520, 460, BLUE, 0.09)):
            d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
            al = (np.clip(1 - d / 0.62, 0, 1) * k)[..., None]; z = z * (1 - al) + np.array(col, np.float32) * al
        dots = np.zeros(z.shape[:2], np.uint8)
        for y in range(5, LH, 10):
            for x in range(((y // 10) % 2) * 5, z.shape[1], 10): cv2.circle(dots, (x, y), 1, 255, -1, AA)
        dd = dots[..., None].astype(np.float32) / 255.0 * 0.07
        img[:, LS_PANEL_X1:] = np.clip(z * (1 - dd) + np.array(INK, np.float32) * dd, 0, 255).astype(np.uint8)
        img[:, :LS_PANEL_X1] = INK
        img[:, LS_PANEL_X1:LS_PANEL_X1 + 5] = PINK
        rgb, a = brand.text('BRODIE', 56, INK, offset=(2.5, 2.0), offset_color=PINK)
        brand.blit(img, rgb, a, LS_COL_X0 - 2, LS_SAFE_TOP + 4)
        ey = LS_SAFE_TOP + 8 + a.shape[0]
        rgb, a = brand.text('PUSH-UP CHALLENGE', 13, PINK, face='mono')
        brand.blit(img, rgb, a, LS_COL_X0, ey + 4)
        self._ls_rule_y = ey + 4 + a.shape[0] + 12
        img[self._ls_rule_y:self._ls_rule_y + 4, LS_COL_X0:LS_COL_X1] = INK
        return img

    def _render_landscape(self, rgb, lm, state, now):
        M, pic = self._ls_fit(rgb)
        if self._ls_base is None or self._ls_base[0] != pic: self._ls_base = (pic, self._ls_make_base(pic))
        img = self._ls_base[1].copy()
        self._clip = pic; self._xlim = (pic[0] + 8, pic[2] - 8)
        self._picture(img, rgb, M, pic)
        self.boxes['picture'] = pic
        # the status pill / stamp: top centre of the picture (away from every corner)
        pill = self._pill_sprite(); ph, pw = pill[1].shape[:2]
        py = max(LS_SAFE_TOP, pic[1] + 14); px = (pic[0] + pic[2]) // 2 - pw // 2
        self._label_y0 = py + ph + 8
        if self._draw_lm is not None and lm is not None: self._skeleton(img, M)
        # the column: timer at the top right, the count under the rule, Brodie bottom left
        chip = self._timer_chip(state); h, w_ = chip[1].shape[:2]
        self._blit(img, 'timer', *chip, LS_COL_X1 - w_, LS_SAFE_TOP + 4)
        cy = self._ls_rule_y + 16
        fit = (LS_MASCOT_FEET - LS_MASCOT_H - 10 - cy - 26) / 0.9
        self._count_at(img, state, now, LS_COL_X0 - 4, cy, fit, LS_COUNT_PX, LS_COL_X1 - LS_COL_X0 - 20)
        if self.ls_mascot is not None: self._mascot(img, state, now, self.ls_mascot, LS_MASCOT_CX, LS_MASCOT_FEET)
        s = self._stamp_sprite(state, now)
        if s is not None:
            srgb, sa, op = s; h, w_ = sa.shape[:2]
            self._blit(img, 'stamp', srgb, sa, (pic[0] + pic[2]) // 2 - w_ // 2, py + ph // 2 - h // 2 + 16, opacity=op)
        else:
            self._blit(img, 'pill', *pill, px, py)
        if self._cue_on(state, now) and self.ls_mascot is not None:   # his bubble: left of him, over the picture's corner
            maxw = 440
            rgb_, a = brand.bubble(self._cue_lines(state, 28, maxw - 44), 28, maxw, tail='right', radius=4)
            h, w_ = a.shape[:2]
            x = LS_MASCOT_CX - int(0.42 * self.ls_mascot.art_w) - w_
            y = min(LS_SAFE_BOTTOM - h, LS_MASCOT_FEET - int(0.62 * LS_MASCOT_H) - int(0.62 * h))
            self._blit(img, 'bubble', rgb_, a, max(LS_SAFE_X, x), max(LS_SAFE_TOP, y))
        return img

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
        rgb, a = brand.pill((('PROP YOUR PHONE. HANDS TO KNEES IN VIEW.', 26, INK),), CANVAS, radius=4, pad=(18, 10))
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
