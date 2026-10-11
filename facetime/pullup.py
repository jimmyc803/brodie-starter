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
HANG_DEG = 145.0                           # elbows straighter than this = dead hang
PULL_START = 0.25                          # progress above this = a pull has started
STALL_DROP = 0.15                          # a pull that falls this far under its peak without clearing = no rep
CLEAR_MARGIN = 0.004                       # hysteresis on the bar line (normalised y)
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
    def __init__(self, target=0, alpha=0.6):
        self.st = PullupState(target=target)
        self.alpha = alpha
        self._bar = None; self._chin = None; self._hang_chin = None
        self._armed = True                 # a dead hang since the last rep (the first rep starts from the hang)
        self._peak = 0.0; self._was_cleared = False

    def _ema(self, old, new):
        return new if old is None else old + self.alpha * (new - old)

    def update(self, lm, t):
        st = self.st; st.events = []
        if lm is None:
            st.on_bar = False; st.cleared = False; return st
        lm = np.asarray(lm, np.float32); vis = lm[:, 3] if lm.shape[1] > 3 else np.ones(len(lm))
        p = lm[:, :2]
        if min(vis[WR_L], vis[WR_R], vis[SH_L], vis[SH_R]) < VIS:
            st.on_bar = False; st.cleared = False; return st
        sh_y = (p[SH_L, 1] + p[SH_R, 1]) / 2
        st.on_bar = bool(p[WR_L, 1] < sh_y and p[WR_R, 1] < sh_y)          # both hands over the shoulders
        if not st.on_bar:
            st.cleared = False; return st
        # the bar: knuckles if seen, else wrists raised by a fifth of the forearm
        hand = [p[i, 1] for i in HAND if vis[i] > VIS]
        if len(hand) >= 2:
            bar = float(np.mean(hand))
        else:
            fore = (np.linalg.norm(p[EL_L] - p[WR_L]) + np.linalg.norm(p[EL_R] - p[WR_R])) / 2
            bar = float((p[WR_L, 1] + p[WR_R, 1]) / 2 - 0.2 * fore)
        # the chin: under the mouth by the nose-to-mouth distance
        mouth = (p[MOUTH_L] + p[MOUTH_R]) / 2
        chin = mouth + (mouth - p[NOSE]) * 1.0
        self._bar = self._ema(self._bar, bar) if not self._was_cleared else self._bar   # hold the bar still while over it
        self._chin = chin if self._chin is None else self._chin + self.alpha * (chin - self._chin)
        st.bar_y = self._bar; st.chin = (float(self._chin[0]), float(self._chin[1]))
        st.elbow_deg = (_angle(p[SH_L], p[EL_L], p[WR_L]) + _angle(p[SH_R], p[EL_R], p[WR_R])) / 2
        hanging = st.elbow_deg > HANG_DEG
        if hanging:                                                      # the dead-hang chin height (lowest seen recently)
            self._hang_chin = self._chin[1] if self._hang_chin is None else max(self._chin[1], self._hang_chin - 0.002)
        ref = self._hang_chin if self._hang_chin is not None else self._chin[1] + 0.15
        span = max(1e-3, ref - self._bar)
        st.progress = float(np.clip((ref - self._chin[1]) / span, 0.0, 1.2))
        # over the bar, with hysteresis
        cy = self._chin[1]
        st.cleared = cy < self._bar - CLEAR_MARGIN if not self._was_cleared else cy < self._bar + CLEAR_MARGIN
        if st.cleared and not self._was_cleared:
            if self._armed:
                st.count += 1; st.clear_t = t; self._armed = False
                st.events += [('rep', st.count), ('cue', COUNT_WORDS[st.count - 1] if st.count <= len(COUNT_WORDS) else str(st.count))]
            else:                                                        # over again without straightening the arms
                st.fault_t = t; st.fault_cue = CUE_FOR[FAULT_HANG]
                st.events += [('fault', FAULT_HANG), ('cue', CUE_FOR[FAULT_HANG])]
            self._peak = 0.0
        self._was_cleared = st.cleared
        if hanging and not self._armed:
            self._armed = True
        # a pull that stalls under the bar
        if not st.cleared and self._armed:
            self._peak = max(self._peak, st.progress)
            if self._peak > PULL_START and st.progress < self._peak - STALL_DROP and self._peak < 1.0:
                st.fault_t = t; st.fault_cue = CUE_FOR[FAULT_CHIN]
                st.events += [('fault', FAULT_CHIN), ('cue', CUE_FOR[FAULT_CHIN])]
                self._peak = 0.0
            if hanging: self._peak = 0.0 if st.progress < 0.05 else self._peak
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
    mirror.bars(img, 'pull ups', st.count, st.target or None, state, cue, cue_t, now)
    if st.on_bar: _meter(img, st, now)
    if green: _badge(img, f'CLEARED  {st.count}', GREEN, mirror.SAFE_TOP + 190)
    elif red: _badge(img, (st.fault_cue or 'Chin over the bar').upper(), RED, mirror.SAFE_TOP + 190, 1.0)
    mirror.inset(img, face)
    return img
