"""Frame prep for the live feed: crop the bridge frame to the caller's picture and turn it upright, before the pose runs.

    prep = FramePrep()                       # one per call; probe pose built lazily (rtcoach.pose.Pose, IMAGE mode)
    up = prep(rgb, now)                      # HxWx3 uint8: the content rect of rgb, rotated by prep.rotation (a new array)
    prep.observe(rgb, lm, now)               # lm: the pose of `up` (or None); may re-check the orientation (<= 1/s)
    prep.apply(rgb)                          # the same crop + rotation for another frame (no state change; None on a
                                             # resolution mismatch), e.g. the mirror's newer frames between poses

Content rect. The Chert bridge captures the Mac's FaceTime window: in a live call the caller's 16:9 picture sat at
x 0.31-0.69, y 0.00-0.38 of the 1280x720 frame (486x274 px, exactly 16:9) and everything else was flat black, i.e.
the window is letterboxed inside the capture, not a dark scene. The pose and the mirror both want only that picture.
content_box() finds the non-black rows / columns of one frame (subsampled, max channel > LIT on >= 1 % of a line's
samples); ContentRect samples it every 0.25 s and moves its rect only when the per-edge median of the last 3 s differs
from it by > 6 % of the frame for 1.5 s in a row, so a dark scene, a fade or a black frame never makes it breathe.

Orientation. A phone in portrait orientation lock held sideways sends its picture rotated 90 deg: the person doing
push-ups stands vertical in the frame and MediaPipe (trained on upright people) finds no plank. While the current
orientation shows no plank-like pose for BAD_S, and the content is portrait-shaped (that phone sends a portrait
picture; a landscape picture is only re-checked after LANDSCAPE_NO_POSE_S with no pose at all, since MediaPipe turns
a standing person on their side into a plausible plank), FramePrep runs the probe
pose (a separate IMAGE-mode landmarker, so the live VIDEO tracker is not disturbed) on the content rotated each other
way, at most once per PROBE_EVERY_S, and scores each with plank_score(). An orientation that scores >= SWITCH_SCORE on
WINS probes in a row (WINS_LANDSCAPE for landscape content) while the current one stays bad becomes the rotation. Once a plank is seen the probes stop; they
come back on their own whenever the current orientation loses the plank, so a wrong lock self-corrects. Nothing here
blocks counting: the pipeline always gets a frame.

plank_score(lm, aspect) (also the mirror's lenient camera check): on the better side, shoulder + elbow + wrist + hip
visible, and a plank-like posture from any reasonable camera angle: the torso within 50 deg of horizontal with the
hands below the shoulders on the floor side (side / diagonal / higher camera), or a foreshortened torso with the
shoulders wide and the hands below them (from the front). Standing (torso vertical, hands at the hips) scores 0, and so
does a plank turned 90 deg (body vertical) or 180 deg (hands above the shoulders).
"""
from __future__ import annotations

import math
from collections import deque

import cv2
import numpy as np

LIT = 12                    # a "black" bar pixel has max channel <= this (H.264 black is 0-4, ringing next to the edge more)
LIT_FRAC = 0.01             # a row / column is content when >= this fraction of its samples are lit
MIN_FRAC = 0.1             # a content rect smaller than this fraction of the frame (either side) is not trusted
SAMPLE_S = 0.25; WINDOW_S = 3.0; SUSTAIN_S = 4.0; CHANGE_FRAC = 0.06
ROTATIONS = (0, 90, 270)    # degrees clockwise applied to the content to make it upright
PROBE_EVERY_S = 1.0; BAD_S = 0.5; WINS = 2
LANDSCAPE_NO_POSE_S = 3.0; WINS_LANDSCAPE = 3   # landscape content: probe only after 3 s without any pose
SWITCH_SCORE = 0.45; GOOD_SCORE = 0.35
PROBE_SHORT = 288           # probe pose input short side (the pipeline's SHORT_SIDE)
SIDE_IX = {'left': (11, 13, 15, 23, 25), 'right': (12, 14, 16, 24, 26)}   # shoulder, elbow, wrist, hip, knee


def content_box(rgb, step=4, lit=LIT, frac=LIT_FRAC):
    """(x0, y0, x1, y1) pixel box of the non-black picture of one frame; the whole frame when nothing is lit or the
    lit box is implausibly small (< MIN_FRAC of a side)."""
    h, w = rgb.shape[:2]
    m = rgb[::step, ::step].max(axis=2) > lit
    cols = np.flatnonzero(m.mean(axis=0) >= frac); rows = np.flatnonzero(m.mean(axis=1) >= frac)
    if not len(cols) or not len(rows): return (0, 0, w, h)
    x0, y0, x1, y1 = int(cols[0] * step), int(rows[0] * step), int(cols[-1] * step) + 1, int(rows[-1] * step) + 1
    if x1 - x0 < MIN_FRAC * w or y1 - y0 < MIN_FRAC * h: return (0, 0, w, h)
    # the exact edges (full resolution within one sample step of each coarse edge): no black line along the picture
    def lit_at(lines):
        return lines.max(axis=-1) > lit
    a = max(0, y0 - step + 1); r = lit_at(rgb[a:y0 + 1, x0:x1:step]).mean(axis=1) >= frac; y0 = a + int(np.argmax(r))
    a = min(h, y1 + step - 1); r = lit_at(rgb[y1 - 1:a, x0:x1:step]).mean(axis=1) >= frac; y1 = y1 - 1 + len(r) - int(np.argmax(r[::-1]))
    a = max(0, x0 - step + 1); r = lit_at(rgb[y0:y1:step, a:x0 + 1]).mean(axis=0) >= frac; x0 = a + int(np.argmax(r))
    a = min(w, x1 + step - 1); r = lit_at(rgb[y0:y1:step, x1 - 1:a]).mean(axis=0) >= frac; x1 = x1 - 1 + len(r) - int(np.argmax(r[::-1]))
    return (x0, y0, x1, y1)


class ContentRect:
    """The slow, robust content rect of a stream of frames (module docstring)."""
    def __init__(self, sample_s=SAMPLE_S, window_s=WINDOW_S, sustain_s=SUSTAIN_S, change_frac=CHANGE_FRAC):
        self.sample_s, self.window_s, self.sustain_s, self.change_frac = sample_s, window_s, sustain_s, change_frac
        self.rect = None; self.shape = None; self.hist = deque(); self.t_sample = -1e9; self.pending_t = None

    def update(self, rgb, now):
        h, w = rgb.shape[:2]
        if self.shape != (h, w):                                   # new resolution: start over
            self.shape = (h, w); self.rect = None; self.hist.clear(); self.t_sample = -1e9; self.pending_t = None
        if now - self.t_sample >= self.sample_s or self.rect is None:
            self.t_sample = now; self.hist.append((now, content_box(rgb)))
            while self.hist and now - self.hist[0][0] > self.window_s: self.hist.popleft()
            med = tuple(int(v) for v in np.median(np.array([b for _, b in self.hist]), axis=0))
            med = ((med[0] + 1) & ~1, (med[1] + 1) & ~1, med[2] & ~1, med[3] & ~1)   # even, rounded inward (no black edge)
            if self.rect is None:
                self.rect = med
            else:
                d = max(abs(med[0] - self.rect[0]) / w, abs(med[2] - self.rect[2]) / w,
                        abs(med[1] - self.rect[1]) / h, abs(med[3] - self.rect[3]) / h)
                if d <= self.change_frac: self.pending_t = None
                elif self.pending_t is None: self.pending_t = now
                elif now - self.pending_t >= self.sustain_s: self.rect = med; self.pending_t = None
        return self.rect


def rotate(img, deg):
    if deg == 90: return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    if deg == 270: return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return img


def _conf(lm):
    c = lm[:, 3].astype(float)
    if lm.shape[1] >= 5: c = np.minimum(c, lm[:, 4].astype(float))
    c = np.nan_to_num(c, nan=0.0)
    inside = np.all((lm[:, :2] >= 0.0) & (lm[:, :2] <= 1.0), axis=1)
    return np.where(inside, c, 0.0)


def plank_score(lm, aspect, min_conf=0.5):
    """0..1: how plausible a plank / push-up the pose is from any camera angle (module docstring). 0 = not one."""
    if lm is None: return 0.0
    lm = np.asarray(lm, dtype=float)
    if lm.ndim != 2 or lm.shape[0] < 33 or lm.shape[1] < 4: return 0.0
    c = _conf(lm); P = lm[:, :2] * np.array([aspect, 1.0])
    best = 0.0
    for side, (sh, el, wr, hp, kn) in SIDE_IX.items():                   # side / diagonal / higher camera
        if min(c[sh], c[hp]) < min_conf or min(c[el], c[wr]) < 0.7 * min_conf: continue   # far-side hands are often half-hidden
        d = P[hp] - P[sh]; L = float(np.linalg.norm(d))
        if L < 1e-3: continue
        u = d / L
        if math.degrees(math.atan2(abs(d[1]), abs(d[0]))) >= 50.0: continue   # 0 = horizontal torso, 90 = vertical
        ua, fa = float(np.linalg.norm(P[el] - P[sh])) / L, float(np.linalg.norm(P[wr] - P[el])) / L
        if not (0.2 < ua < 1.3 and 0.2 < fa < 1.3): continue           # arm segments the size of an arm
        head = [i for i in ((7, 0) if sh == 11 else (8, 0)) if c[i] >= min_conf]
        if head and float((P[head[0]] - P[sh]) @ u) / L > 0.15: continue   # the head is on the far side from the hips
        v = P[wr] - P[sh]
        below = v[1] / L                                               # image y grows down: + = hand below the shoulder
        along = float(v @ u) / L                                       # where the hand is along the torso (0 = at the shoulder)
        if not (below > 0.3 and -0.9 < along < 0.75): continue
        vis = float(np.mean([c[sh], c[el], c[wr], c[hp]]))
        best = max(best, vis * (0.85 + 0.15 * float(c[kn] >= min_conf)))
    if best > 0: return best
    # from the front (camera ahead of the head): both shoulders, the torso foreshortened under a wide shoulder line that
    # runs across the image, the hips below the shoulders and the hands below them too
    if min(c[11], c[12]) < min_conf or max(c[23], c[24]) < min_conf: return 0.0
    hips = [i for i in (23, 24) if c[i] >= min_conf]
    ms = (P[11] + P[12]) / 2; mh = P[hips].mean(axis=0)
    q = P[12] - P[11]; sw = float(np.linalg.norm(q)); L = float(np.linalg.norm(mh - ms))
    if sw < 1e-3 or abs(q[1]) > 0.5 * abs(q[0]) or mh[1] <= ms[1] or sw / max(L, 1e-3) < 0.95: return 0.0
    hands = [(e, w) for e, w in ((13, 15), (14, 16)) if min(c[e], c[w]) >= 0.7 * min_conf]
    if not hands or not any(P[w][1] - ms[1] > 0.25 * sw for _, w in hands): return 0.0
    e, w = max(hands, key=lambda h: c[h[1]])
    vis = float(np.mean([c[11], c[12], c[e], c[w]] + [c[i] for i in hips]))
    knees = any(c[k] >= min_conf for k in (25, 26))
    return vis * (0.85 + 0.15 * float(knees))


class FramePrep:
    """Content crop + orientation lock for one call's feed (module docstring). Used from the feed thread; apply() may
    run on another thread (it reads one immutable tuple)."""

    def __init__(self, probe=None, pose_variant='full', probe_every_s=PROBE_EVERY_S, bad_s=BAD_S, wins=WINS):
        """probe: callable(rgb) -> (33, 5) landmarks or None for an upright frame; None = an IMAGE-mode rtcoach Pose
        of `pose_variant`, built on first use."""
        self._probe = probe; self.pose_variant = pose_variant; self._pose = None
        self.probe_every_s, self.bad_s, self.wins = probe_every_s, bad_s, wins
        self.content = ContentRect()
        self.rotation = 0
        self.geom = None                 # (source (h, w), rect, rotation): what apply() uses
        self.score = 0.0                 # plank_score of the last observed pose
        self.t_good = None               # last time the current orientation showed a plank
        self.t_any = None                # last time any orientation showed a usable (plank-like) pose
        self.t_pose = None               # last time the current orientation had any pose
        self.t_probe = -1e9; self.streak = {}; self.n_probes = 0; self.n_switches = 0
        self.last_probe = {}             # rotation -> score of the last probe

    # -- the frame ------------------------------------------------------------------------------------------------
    def __call__(self, rgb, now):
        rect = self.content.update(rgb, now)
        self.geom = (rgb.shape[:2], rect, self.rotation)
        return self._cut(rgb, rect, self.rotation)

    def apply(self, rgb):
        g = self.geom
        if g is None or rgb.shape[:2] != g[0]: return None
        return self._cut(rgb, g[1], g[2])

    @staticmethod
    def _cut(rgb, rect, rot):
        x0, y0, x1, y1 = rect
        sub = rgb[y0:y1, x0:x1]
        return rotate(sub, rot) if rot else np.ascontiguousarray(sub)

    @property
    def portrait(self):
        r = self.content.rect
        return r is not None and (r[3] - r[1]) > 1.15 * (r[2] - r[0])

    # -- the orientation lock ----------------------------------------------------------------------------------------
    def observe(self, rgb, lm, now):
        """After the pose ran on self(rgb, now): update the lock; maybe probe the other orientations (<= 1 / probe_every_s)."""
        if self.t_good is None: self.t_good = now
        if self.t_pose is None or lm is not None: self.t_pose = now
        up = self.geom
        h, w = (up[1][3] - up[1][1], up[1][2] - up[1][0]) if up is not None else rgb.shape[:2]
        if self.rotation in (90, 270): h, w = w, h
        self.score = plank_score(lm, w / max(1, h))
        if self.score >= GOOD_SCORE:
            self.t_good = self.t_any = now; self.streak.clear(); return None
        portrait = self.portrait
        if now - self.t_good < self.bad_s or now - self.t_probe < self.probe_every_s: return None
        if not portrait and now - self.t_pose < LANDSCAPE_NO_POSE_S: return None   # a pose in a landscape picture: upright
        wins = self.wins if portrait else max(self.wins, WINS_LANDSCAPE)
        self.t_probe = now; rect = self.content.rect or (0, 0, rgb.shape[1], rgb.shape[0])
        x0, y0, x1, y1 = rect; sub = rgb[y0:y1, x0:x1]
        s = min(sub.shape[:2])
        if s > PROBE_SHORT:
            f = PROBE_SHORT / s; sub = cv2.resize(sub, (max(1, round(sub.shape[1] * f)), max(1, round(sub.shape[0] * f))), interpolation=cv2.INTER_AREA)
        scores = {}
        for rot in ROTATIONS:
            if rot == self.rotation: continue
            img = np.ascontiguousarray(rotate(sub, rot))
            plm = self._run_probe(img); self.n_probes += 1
            scores[rot] = plank_score(plm, img.shape[1] / img.shape[0])
        self.last_probe = scores
        for rot in ROTATIONS:
            if rot != self.rotation and scores.get(rot, 0.0) >= SWITCH_SCORE and scores[rot] >= max(scores.values()):
                self.streak[rot] = self.streak.get(rot, 0) + 1; self.t_any = now
            else:
                self.streak.pop(rot, None)
        for rot, n in self.streak.items():
            if n >= wins:
                old = self.rotation; self.rotation = rot; self.n_switches += 1
                self.streak.clear(); self.t_good = now
                return old, rot
        return None

    def _run_probe(self, img):
        if self._probe is not None: return self._probe(img)
        if self._pose is None:
            from rtcoach.pose import Pose
            self._pose = Pose(self.pose_variant, video=False)
        a, _ = self._pose(img, 0)
        return a

    def no_pose_s(self, now):
        """Seconds since any orientation last showed a plank-like pose (since the first observe when never)."""
        ref = self.t_any if self.t_any is not None else self.t_good
        return 0.0 if ref is None else max(0.0, now - ref)

    def diag(self):
        r = self.content.rect; sh = self.content.shape
        box = f'content x {r[0] / sh[1]:.2f}-{r[2] / sh[1]:.2f} y {r[1] / sh[0]:.2f}-{r[3] / sh[0]:.2f} ({r[2] - r[0]}x{r[3] - r[1]})' if r and sh else 'content n/a'
        pr = ' '.join(f'{k}:{v:.2f}' for k, v in sorted(self.last_probe.items()))
        return f'{box}; rot {self.rotation} (plank {self.score:.2f}, switches {self.n_switches}, probes {self.n_probes}{"; last " + pr if pr else ""})'

    def close(self):
        if self._pose is not None:
            try: self._pose.close()
            finally: self._pose = None
