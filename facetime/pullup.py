"""Pull-ups: a rule counter on the MediaPipe pose, and the mirror overlay that shows when the chin clears the bar.

No training: a pull-up is geometric. The hands hold the bar, so the bar is the line through the knuckles (index and pinky
landmarks; the wrists plus a fifth of the forearm when the hands are not seen). A rep counts the moment the chin goes over that
line, and the next one only after the arms straighten again (a dead hang, elbows > HANG_DEG), the way a coach judges it.

    pc = PullupCounter(target=5)
    st = pc.update(landmarks, t)     # landmarks: (33, >=4) normalised x, y, z, visibility (FramePipeline.last_landmarks) or None
    st.count, st.cleared, st.progress, st.bar_y, st.events   # events: ('rep', n) / ('fault', label) / ('cue', text) this frame

compose_pullup(rgb, lm, st, ...) draws it (facetime/mirror.py look): the bar as a line across the frame, a height meter from
dead hang to the bar, and on a clear the bar and the skeleton turn green with a CLEARED tick and the count popping. A pull that
stalls under the bar flashes red with "Chin over the bar".
"""
import math
from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from facetime import mirror
from facetime.mirror import W, H, BLACK, WHITE, VOLT, VIS

GREEN = (34, 197, 94); RED = (239, 68, 68)
NOSE, MOUTH_L, MOUTH_R = 0, 9, 10
SH_L, SH_R, EL_L, EL_R, WR_L, WR_R = 11, 12, 13, 14, 15, 16
HAND = (17, 18, 19, 20)                    # pinkies and index knuckles
HANG_DEG = 130.0                           # elbows straighter than this = dead hang (arms the next rep)
PULL_DEG = 115.0                           # elbows bent under this = a pull has started
PULL_END_DEG = 125.0                       # straighter than this again = the pull is over
STALL_ELBOW = 100.0                        # a pull that bent the elbows this far but never cleared = "Chin over the bar"
STALL_PROGRESS = 0.3                       # ... and lifted the chin at least this far (not a shrug or a wobble)
HANG_HOLD_S = 0.2                         # the first dead hang after getting on the bar must last this long
TOP_PROGRESS = 0.85                        # chin this far from the hang height to the bar = over the bar
TOP_ELBOW = 50.0                           # or elbows fully bent ...
LOOSE_PROGRESS = 0.55                      # ... with the chin at least this far up
TOP_EXIT_PROGRESS = 0.7; TOP_EXIT_ELBOW = 80.0
OFF_GRACE_S = 0.6                          # pose dropouts shorter than this keep the state
FLASH_S = 0.8
FAULT_CHIN = 'pull ups - chin over the bar'
FAULT_HANG = 'pull ups - full hang at the bottom'
CUE_FOR = {FAULT_CHIN: 'Chin over the bar', FAULT_HANG: 'Full hang at the bottom'}
COUNT_WORDS = ['One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
               'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen', 'Twenty']


def _angle(a, b, c):
    v1, v2 = a - b, c - b
    d = np.linalg.norm(v1) * np.linalg.norm(v2)
    return 180.0 if d < 1e-9 else math.degrees(math.acos(float(np.clip(np.dot(v1, v2) / d, -1, 1))))


@dataclass
class PullupState:
    count: int = 0
    target: int = 0
    on_bar: bool = False
    cleared: bool = False
    progress: float = 0.0                  # 0 = dead hang, 1 = chin at the bar
    bar_y: Optional[float] = None                    # normalised
    chin: Optional[tuple] = None                     # normalised (x, y)
    elbow_deg: float = 180.0
    clear_t: float = -1e9                  # last clear (count pop / green flash)
    fault_t: float = -1e9                  # last no-rep (red flash)
    fault_cue: Optional[str] = None
    events: list = field(default_factory=list)


class PullupCounter:
    """A pull is one elbow cycle: from a hang (elbows > HANG_DEG) the elbows bend under PULL_DEG, then straighten again.
    The pull is a rep when its top clears the bar: the chin at TOP_PROGRESS of the way from its dead-hang height to the bar,
    or the elbows fully bent (< TOP_ELBOW) with the chin past LOOSE_PROGRESS (a low camera puts the bar above a chin that is
    over it). The elbows are the clean signal on every view (front, back, side); the chin estimate is noisier from behind."""

    def __init__(self, target=0, alpha=0.6):
        self.st = PullupState(target=target)
        self.alpha = alpha
        self._bar = None; self._chin = None; self._elbow = None; self._hang_chin = None
        self._armed = False                # a dead hang since the last rep; the first needs a settled hang (not the jump to the bar)
        self._hang_since = None; self._settled = False
        self._pulling = False; self._top = False; self._counted = False
        self._off_since = None
        self.pulls = []                    # diagnostics: one dict per pull (min elbow, max progress, counted, fault)

    def _ema(self, old, new, a=None):
        a = self.alpha if a is None else a
        return new if old is None else old + a * (new - old)

    def _off(self, t):
        st = self.st
        if self._off_since is None: self._off_since = t
        if t - self._off_since >= OFF_GRACE_S:
            st.on_bar = False; st.cleared = False; self._top = False; self._pulling = False; self._armed = False
            self._hang_since = None; self._settled = False
        return st

    def update(self, lm, t):
        st = self.st; st.events = []
        if lm is None:
            return self._off(t)
        lm = np.asarray(lm, np.float32); vis = lm[:, 3] if lm.shape[1] > 3 else np.ones(len(lm))
        p = lm[:, :2]
        if min(vis[WR_L], vis[WR_R], vis[EL_L], vis[EL_R], vis[SH_L], vis[SH_R]) < VIS:
            return self._off(t)
        wr_y = (p[WR_L, 1] + p[WR_R, 1]) / 2; el_y = (p[EL_L, 1] + p[EL_R, 1]) / 2
        if not wr_y < el_y:                # hands over the elbows on the bar, hanging or at the top; not when standing
            return self._off(t)
        self._off_since = None; st.on_bar = True
        # the bar: knuckles if seen, else wrists raised by a fifth of the forearm; it does not move, so slow smoothing
        hand = [p[i, 1] for i in HAND if vis[i] > VIS]
        if len(hand) >= 2:
            bar = float(np.mean(hand))
        else:
            fore = (np.linalg.norm(p[EL_L] - p[WR_L]) + np.linalg.norm(p[EL_R] - p[WR_R])) / 2
            bar = float(wr_y - 0.2 * fore)
        self._bar = self._ema(self._bar, bar, 0.3)
        # the chin: under the mouth by the nose-to-mouth distance
        mouth = (p[MOUTH_L] + p[MOUTH_R]) / 2
        chin = mouth + (mouth - p[NOSE]) * 1.0
        self._chin = chin if self._chin is None else self._chin + self.alpha * (chin - self._chin)
        st.bar_y = self._bar; st.chin = (float(self._chin[0]), float(self._chin[1]))
        el = (_angle(p[SH_L], p[EL_L], p[WR_L]) + _angle(p[SH_R], p[EL_R], p[WR_R])) / 2
        self._elbow = self._ema(self._elbow, el); st.elbow_deg = self._elbow
        hanging = self._elbow > HANG_DEG
        if hanging:                        # the dead-hang chin height (follows the hang; drifts up slowly)
            self._hang_chin = self._chin[1] if self._hang_chin is None else max(self._chin[1], self._hang_chin - 0.002)
        ref = self._hang_chin if self._hang_chin is not None else self._chin[1] + 0.15
        span = max(1e-3, ref - self._bar)
        st.progress = float(np.clip((ref - self._chin[1]) / span, 0.0, 1.2))

        if not self._pulling and self._elbow < PULL_DEG:          # a pull starts
            self._pulling = True; self._counted = False
            self.pulls.append({'t': round(t, 1), 'min_elbow': 180.0, 'max_progress': 0.0, 'counted': False, 'fault': None})
        if self._pulling:
            d = self.pulls[-1]; d['min_elbow'] = round(min(d['min_elbow'], self._elbow), 1); d['max_progress'] = round(max(d['max_progress'], st.progress), 2)
        at_top = st.progress >= TOP_PROGRESS or (self._elbow < TOP_ELBOW and st.progress >= LOOSE_PROGRESS)
        if self._pulling and at_top and not self._top:            # the top of the pull: over the bar
            self._top = True
            if self._counted and self._settled:                   # back over the bar from a half-way drop: not a rep
                st.fault_t = t; st.fault_cue = CUE_FOR[FAULT_HANG]; self.pulls[-1]['fault'] = FAULT_HANG
                st.events += [('fault', FAULT_HANG), ('cue', CUE_FOR[FAULT_HANG])]
            elif not self._counted:
                if self._armed:
                    st.count += 1; st.clear_t = t; self._armed = False; self._counted = True; self.pulls[-1]['counted'] = True
                    st.events += [('rep', st.count), ('cue', COUNT_WORDS[st.count - 1] if st.count <= len(COUNT_WORDS) else str(st.count))]
                elif self._settled:                               # over again without straightening the arms
                    self._counted = True; st.fault_t = t; st.fault_cue = CUE_FOR[FAULT_HANG]; self.pulls[-1]['fault'] = FAULT_HANG
                    st.events += [('fault', FAULT_HANG), ('cue', CUE_FOR[FAULT_HANG])]
        if self._top and st.progress < TOP_EXIT_PROGRESS and self._elbow > TOP_EXIT_ELBOW:
            self._top = False
        st.cleared = self._top
        if self._pulling and self._elbow > PULL_END_DEG:          # the arms straightened: the pull is over
            d = self.pulls[-1]
            if not self._counted and self._settled and d['min_elbow'] < STALL_ELBOW and d['max_progress'] >= STALL_PROGRESS:   # a real pull that never got over the bar
                st.fault_t = t; st.fault_cue = CUE_FOR[FAULT_CHIN]; self.pulls[-1]['fault'] = FAULT_CHIN
                st.events += [('fault', FAULT_CHIN), ('cue', CUE_FOR[FAULT_CHIN])]
            self._pulling = False; self._top = False; st.cleared = False
        if hanging:
            if self._hang_since is None: self._hang_since = t
            if t - self._hang_since >= HANG_HOLD_S - 1e-6: self._settled = True
            if self._settled: self._armed = True
        else:
            self._hang_since = None
        return st


# ---- the overlay ----

def _skeleton(img, pts, color):
    for a, b in mirror.CONNECTIONS:
        if pts[a][2] > VIS and pts[b][2] > VIS:
            cv2.line(img, pts[a][:2], pts[b][:2], BLACK, 9, cv2.LINE_AA); cv2.line(img, pts[a][:2], pts[b][:2], color, 4, cv2.LINE_AA)
    for x, y, v in pts[11:]:
        if v > VIS: cv2.circle(img, (x, y), 8, BLACK, -1, cv2.LINE_AA); cv2.circle(img, (x, y), 5, color, -1, cv2.LINE_AA)


def _dashed(img, y, color, x0=0, x1=W, dash=26, gap=14, thick=5):
    x = x0
    while x < x1:
        cv2.line(img, (x, y), (min(x + dash, x1), y), BLACK, thick + 4, cv2.LINE_AA)
        cv2.line(img, (x, y), (min(x + dash, x1), y), color, thick, cv2.LINE_AA); x += dash + gap


def _tick(img, cx, cy, r, color):
    cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)
    pts = np.array([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)], np.int32)
    cv2.polylines(img, [pts], False, WHITE, max(3, r // 6), cv2.LINE_AA)


def _badge(img, text, color, y, scale=1.3):
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 3)
    pad = 18; r = th // 2 + pad; w = tw + 2 * pad + (2 * r if color == GREEN else 0)
    x0 = (W - w) // 2
    cv2.rectangle(img, (x0, y - th - pad), (x0 + w, y + pad), color, -1)
    tx = x0 + pad
    if color == GREEN: _tick(img, x0 + pad + r - 6, y - th // 2, r - 8, (21, 128, 61)); tx += 2 * r
    cv2.putText(img, text, (tx, y), cv2.FONT_HERSHEY_DUPLEX, scale, WHITE, 3, cv2.LINE_AA)


def _meter(img, st, now, x=None):
    """Left edge: how high the chin is between the dead hang (bottom) and the bar (the line at the top)."""
    x = mirror.SAFE_X - 22 if x is None else x
    top, bot, wdt = int(H * 0.30), int(H * 0.70), 22
    cv2.rectangle(img, (x - 3, top - 3), (x + wdt + 3, bot + 3), BLACK, -1)
    fill = int((bot - top) * min(1.0, st.progress))
    col = GREEN if st.cleared or now - st.clear_t < FLASH_S else (RED if now - st.fault_t < FLASH_S else VOLT)
    cv2.rectangle(img, (x, bot - fill), (x + wdt, bot), col, -1)
    cv2.line(img, (x - 10, top), (x + wdt + 10, top), WHITE, 3)              # the bar on the meter


def compose_pullup(rgb, lm, st, cue=None, cue_t=0.0, face=None, now=0.0):
    """mirror.compose for pull-ups: the same crop, bars and face, plus the bar line, the meter and the clear / no-rep flashes."""
    full_h, full_w = rgb.shape[:2]
    img, box = mirror.crop_portrait(rgb, lm)
    img = np.ascontiguousarray(img)
    green = st.cleared or now - st.clear_t < FLASH_S
    red = not green and now - st.fault_t < FLASH_S
    if green:                                                            # a green wash on a clear
        img[:] = (img * 0.82 + np.array(GREEN) * 0.18).astype(np.uint8)
    if lm is not None:
        pts = mirror._map(lm, box, full_w, full_h)
        if st.bar_y is not None and st.on_bar:
            by = int((st.bar_y * full_h - box[1]) * H / box[3])
            if green: cv2.line(img, (0, by), (W, by), BLACK, 14, cv2.LINE_AA); cv2.line(img, (0, by), (W, by), GREEN, 8, cv2.LINE_AA)
            else: _dashed(img, by, RED if red else WHITE)
            if st.chin is not None:                                      # the chin marker and its gap to the bar
                cx = int((st.chin[0] * full_w - box[0]) * W / box[2]); cy = int((st.chin[1] * full_h - box[1]) * H / box[3])
                if not green and cy > by: cv2.line(img, (cx, cy), (cx, by), WHITE, 2, cv2.LINE_AA)
                cv2.circle(img, (cx, cy), 13, BLACK, -1, cv2.LINE_AA); cv2.circle(img, (cx, cy), 9, GREEN if green else (RED if red else WHITE), -1, cv2.LINE_AA)
        _skeleton(img, pts, GREEN if green else (RED if red else VOLT))
    state = 'active' if st.on_bar else ('done' if st.target and st.count >= st.target else 'wait')
    target = st.target if st.target and st.count <= st.target else None      # past the target: just the count
    mirror.bars(img, 'pull ups', st.count, target, state if target or not st.count else None, cue, cue_t, now)
    if target is None and st.count: mirror.text(img, str(st.count), (mirror.SAFE_X, mirror.SAFE_TOP + 88), 1.5, VOLT, 3, outline=False)
    if st.on_bar: _meter(img, st, now)
    if green: _badge(img, f'CLEARED  {st.count}', GREEN, mirror.SAFE_TOP + 190)
    elif red: _badge(img, (st.fault_cue or 'Chin over the bar').upper(), RED, mirror.SAFE_TOP + 190, 1.0)
    mirror.inset(img, face)
    return img
