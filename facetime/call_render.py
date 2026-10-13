"""Render a recorded pull-up set as a Brodie FaceTime call: the recording full screen with a sleek tracking HUD, Brodie's
face in a picture-in-picture tile, and Brodie's voice counting the reps and critiquing the form (cue bank clips, lip-synced).

Same analysis as facetime/annotate_video.py (MediaPipe pose on every frame, PullupCounter at the live 10 fps), then:
  - HUD: glowing skeleton, the bar line (solid on a clear), a chin marker with its gap to the bar, a height rail, an elbow
    angle tag, a rep counter with one dot per pull (clean / half), rep and half-rep toasts, a form-note card per critique;
  - call chrome: Brodie + call timer, live tracking readout, FaceTime controls, Brodie's tile with a speaking ring and his line;
  - a "connecting / calibrating" pre-roll and a set summary at the end.
The spoken script is picked from the pulls (height, half reps, recovery) and scheduled like the live one-slot player.

Run:  PYTHONPATH=src .venv/bin/python -m facetime.call_render --video my_pullups.mov [--out my_pullups.call.mp4]
"""
import argparse, json, math, os, subprocess, tempfile, wave
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from facetime import SAMPLE_RATE
from facetime.audio_out import CueBank
from facetime.avatar import Avatar
from facetime.pipeline import FPS, to_short_side
from facetime.pullup import PullupCounter, COUNT_WORDS
from rtcoach.pose import Pose

OW, OH = 1080, 1920
VOLT = (217, 255, 61); RED = (255, 69, 58); GREEN = (48, 209, 88); WHITE = (245, 245, 247); GREY = (152, 152, 160)
PRE, POST = 2.2, 3.6                       # pre-roll (connecting / calibrating) and the summary hold, seconds
SANS = '/System/Library/Fonts/SFNS.ttf'; MONO = '/System/Library/Fonts/SFNSMono.ttf'
BONES = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28)]
JOINTS = [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]
VIS = 0.5

_fonts = {}
def font(size, weight='Semibold', mono=False):
    k = (size, weight, mono)
    if k not in _fonts:
        f = ImageFont.truetype(MONO if mono else SANS, size)
        try: f.set_variation_by_name(weight)
        except Exception: pass
        _fonts[k] = f
    return _fonts[k]

def ease(x): x = min(1.0, max(0.0, x)); return 1 - (1 - x) ** 3
def back(x):
    x = min(1.0, max(0.0, x)) - 1; c = 1.8
    return 1 + (c + 1) * x ** 3 + c * x ** 2


# ---- analysis --------------------------------------------------------------------------------------------------------

def analyse(path, variant):
    """Pose on every frame + the live counter. Returns per-frame landmarks (smoothed for drawing), per-frame counter state,
    the events and the pulls."""
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; step = max(1, round(fps / FPS))
    pose = Pose(variant, video=True); pc = PullupCounter()
    lms, states, events, i, last_ms, sm, miss = [], [], [], 0, -1, None, 0
    while True:
        ok, bgr = cap.read()
        if not ok: break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); t = i / fps
        ms = max(last_ms + 1, int(t * 1000)); last_ms = ms
        lm, _ = pose(to_short_side(rgb), ms)
        if i % step == 0:
            st = pc.update(lm, t)
            for kind, val in st.events:
                if kind in ('rep', 'fault'): events.append((t, kind, val))
        st = pc.st
        states.append(dict(count=st.count, on_bar=st.on_bar, cleared=st.cleared, progress=st.progress, bar_y=st.bar_y,
                           chin=st.chin, clear_t=st.clear_t, fault_t=st.fault_t))
        if lm is not None:                                          # EMA for drawing only (the counter saw the raw pose)
            a = np.asarray(lm, np.float32)[:, [0, 1, 3]]
            sm = a if sm is None else np.where(a[:, 2:3] > VIS, sm + 0.55 * (a - sm), sm); miss = 0
        else:
            miss += 1
            if miss > 6: sm = None
        lms.append(None if sm is None else sm.copy()); i += 1
    cap.release(); pose.close()
    return dict(fps=fps, n=i, lms=lms, states=states, events=events, pulls=pc.pulls)


def script(an, bank):
    """Brodie's lines on the output timeline: (start_s, text, kind, note). Counts and faults always speak; praise and
    critique are dropped when they would push the next count late (the live player's one slot, in time)."""
    pulls = [p for p in an['pulls'] if p['counted'] or p['fault']]
    clean = iter([p for p in pulls if p['counted']])
    want, faults_seen, after_fault, praised_height = [], 0, False, False
    want.append((PRE - 1.75, "Let's do pull ups", 'must', None))
    for t, kind, val in an['events']:
        T = PRE + t + 0.05
        if kind == 'rep':
            p = next(clean, {}); want.append((T, COUNT_WORDS[val - 1] if val <= len(COUNT_WORDS) else str(val), 'must',
                                               dict(kind='clean', rep=val, pull=p)))
            if after_fault: want.append((T + 0.01, 'Looking strong', 'opt', dict(kind='recover', rep=val, pull=p))); after_fault = False
            elif p.get('max_progress', 0) >= 1.15 and not praised_height:
                want.append((T + 0.01, 'Excellent height', 'opt', dict(kind='praise', rep=val, pull=p))); praised_height = True
        else:
            line = ['Chin over the bar, not near it', 'Half reps, half results', 'Full range, not a preview'][min(faults_seen, 2)]
            if 'hang' in val: line = 'Dead hang first, then we talk'
            p = next((q for q in pulls if q['fault'] and abs(q['t'] - t) < 1.5), {})
            want.append((T, line, 'must', dict(kind='half', pull=p))); faults_seen += 1; after_fault = True
    end = PRE + an['n'] / an['fps'] + 0.45
    want.append((end, 'Not bad. Not good either. Same time tomorrow' if faults_seen else 'All done, great session', 'must', None))
    want.sort(key=lambda w: w[0])
    out, free = [], 0.0
    for k, (t, text, kind, note) in enumerate(want):
        d = bank.duration(text)
        if d is None: continue
        start = max(t, free)
        if kind == 'opt':
            nxt = next((w[0] for w in want[k + 1:] if w[2] == 'must'), 1e9)
            if start > t + 0.5 or start + d + 0.12 > nxt + 0.25: continue
        out.append((start, text, d, note)); free = start + d + 0.12
    return out


def mix(lines, bank, total, path):
    n = int(total * SAMPLE_RATE) + SAMPLE_RATE; buf = np.zeros(n, np.int32)
    for start, text, _, _ in lines:
        pcm = bank.get(text)
        if pcm is None: continue
        i = int(start * SAMPLE_RATE); j = min(n, i + len(pcm)); buf[i:j] += pcm[:j - i]
    w = wave.open(path, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
    w.writeframes(np.clip(buf, -32768, 32767).astype(np.int16).tobytes()); w.close()


# ---- drawing helpers -------------------------------------------------------------------------------------------------

_masks = {}
def rmask(w, h, r):
    """Anti-aliased rounded-rect mask (float 0..1), drawn at 4x and downsampled."""
    k = (w, h, r)
    if k not in _masks:
        m = Image.new('L', (w * 4, h * 4), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 4 - 1, h * 4 - 1), r * 4, fill=255)
        _masks[k] = (np.asarray(m.resize((w, h), Image.LANCZOS), np.float32) / 255.0)[..., None]
    return _masks[k]

def glass(img, x, y, w, h, r, tint=(16, 16, 20), alpha=0.5, blur=22):
    """Frosted panel: blur what's behind, darken, then a hairline border is drawn by the caller on the overlay."""
    x, y = int(x), int(y); x0, y0, x1, y1 = max(0, x), max(0, y), min(OW, x + w), min(OH, y + h)
    if x1 <= x0 or y1 <= y0: return
    reg = img[y0:y1, x0:x1].astype(np.float32)
    b = cv2.GaussianBlur(reg, (0, 0), blur) * (1 - alpha) + np.array(tint, np.float32) * alpha
    m = rmask(w, h, r)[y0 - y:y1 - y, x0 - x:x1 - x]
    img[y0:y1, x0:x1] = (reg * (1 - m) + b * m).astype(np.uint8)

def hairline(d, x, y, w, h, r, a=46):
    d.rounded_rectangle((x, y, x + w, y + h), r, outline=(255, 255, 255, a), width=2)

def text(d, xy, s, size, fill=WHITE, weight='Semibold', mono=False, anchor='la', a=255, spacing=0):
    f = font(size, weight, mono); col = (*fill[:3], a)
    if spacing:
        x, y = xy
        if anchor[0] in 'mr':
            tw = sum(d.textlength(c, font=f) + spacing for c in s) - spacing
            x -= tw / 2 if anchor[0] == 'm' else tw
        for c in s:
            d.text((x, y), c, font=f, fill=col, anchor='l' + anchor[1]); x += d.textlength(c, font=f) + spacing
    else:
        d.text(xy, s, font=f, fill=col, anchor=anchor)

def vignette():
    yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
    r = np.sqrt(((xx - OW / 2) / (OW * 0.62)) ** 2 + ((yy - OH * 0.47) / (OH * 0.62)) ** 2)
    return np.clip(1.08 - 0.5 * np.clip(r - 0.35, 0, 1) ** 1.4, 0.45, 1.0)[..., None].astype(np.float32)


class Renderer:
    def __init__(self, an, lines, src_w, src_h):
        self.an, self.lines = an, lines
        s = max(OW / src_w, OH / src_h); self.s = s
        self.ox, self.oy = (OW - src_w * s) / 2, (OH - src_h * s) / 2
        self.sw, self.sh = src_w, src_h
        self.vig = vignette(); self.av = Avatar(); self.av._next_blink = 1e18
        self.tile = (OW - 36 - 286, 1188, 286, 470)        # Brodie's PiP
        self.pulls = [p for p in an['pulls'] if p['counted'] or p['fault']]
        self.notes = [(st, txt, d, nt) for st, txt, d, nt in lines if nt and nt['kind'] in ('praise', 'half', 'recover')]
        self.reps = [(PRE + t, v) for t, k, v in an['events'] if k == 'rep']
        self.halves = [PRE + t for t, k, _ in an['events'] if k == 'fault']
        self.dur = an['n'] / an['fps']; self.blink_at = 2.0

    def px(self, x, y): return (self.ox + x * self.sw * self.s, self.oy + y * self.sh * self.s)

    def speaking(self, T):
        for st, txt, d, _ in self.lines:
            if st <= T < st + d: return txt, T - st, d
        return None

    def frame(self, src_rgb, T):
        an = self.an
        s_t = T - PRE; idx = int(min(max(s_t, 0), self.dur - 1e-3) * an['fps'])
        img = cv2.resize(src_rgb, (int(self.sw * self.s), int(self.sh * self.s)), interpolation=cv2.INTER_AREA)
        img = img[int(-self.oy):int(-self.oy) + OH, int(-self.ox):int(-self.ox) + OW] if (self.ox < 0 or self.oy < 0) else img
        img = cv2.resize(img, (OW, OH)) if img.shape[:2] != (OH, OW) else img
        f = img.astype(np.float32)
        f = (f - 128) * 1.08 + 122                                            # contrast, a touch darker
        f = f * np.array([0.97, 1.0, 1.04], np.float32) * self.vig
        pre = T < PRE; post = s_t > self.dur
        if pre or post:                                                       # blur in / out around the set
            k = 1 - ease((T - (PRE - 0.7)) / 0.7) if pre else ease((s_t - self.dur) / 0.8)
            if k > 0.01: f = cv2.GaussianBlur(f, (0, 0), 1 + 26 * k) * (1 - 0.45 * k)
        img = np.clip(f, 0, 255).astype(np.uint8)
        st = an['states'][idx]; lm = an['lms'][idx]
        live = not pre and not post
        green = live and (st['cleared'] or s_t - st['clear_t'] < 0.45)
        red = live and not green and s_t - st['fault_t'] < 0.6
        if live: img = self.hud_layer(img, st, lm, green, red, s_t)
        if red:                                                               # red edge pulse on a half rep
            a = 0.35 * (1 - (s_t - st['fault_t']) / 0.6)
            img = np.clip(img.astype(np.float32) * (1 - a * (1 - self.vig) * 1.6) + np.array(RED, np.float32) * a * (1 - self.vig) * 1.6, 0, 255).astype(np.uint8)
        return self.chrome(img, T, st, lm, live, green, red, s_t)

    # glowing skeleton, bar line, chin marker
    def hud_layer(self, img, st, lm, green, red, s_t):
        col = GREEN if green else RED if red else VOLT
        layer = np.zeros_like(img)
        P = None
        if lm is not None:
            P = [(int(x), int(y)) for x, y in (self.px(a, b) for a, b, _ in lm)]
            for a, b in BONES:
                if lm[a, 2] > VIS and lm[b, 2] > VIS: cv2.line(layer, P[a], P[b], col, 6, cv2.LINE_AA)
        by = None
        if st['on_bar'] and st['bar_y'] is not None:
            by = int(self.px(0.5, st['bar_y'])[1])
            if green: cv2.line(layer, (0, by), (OW, by), col, 5, cv2.LINE_AA)
        glow = cv2.GaussianBlur(layer, (0, 0), 14)
        img = cv2.add(img, (glow.astype(np.float32) * 1.35).clip(0, 255).astype(np.uint8))
        if by is not None:
            if green: cv2.line(img, (0, by), (OW, by), (235, 255, 200), 3, cv2.LINE_AA)
            else:
                for x in range(0, OW, 34): cv2.line(img, (x, by), (min(OW, x + 18), by), (230, 230, 235), 2, cv2.LINE_AA)
        if P is not None:
            for a, b in BONES:
                if lm[a, 2] > VIS and lm[b, 2] > VIS: cv2.line(img, P[a], P[b], tuple(int(c * 0.35 + 255 * 0.65) for c in col), 2, cv2.LINE_AA)
            for j in JOINTS:
                if lm[j, 2] > VIS:
                    cv2.circle(img, P[j], 9, (10, 10, 12), -1, cv2.LINE_AA); cv2.circle(img, P[j], 9, col, 2, cv2.LINE_AA)
                    cv2.circle(img, P[j], 3, WHITE, -1, cv2.LINE_AA)
        if st['chin'] is not None and by is not None:
            cx, cy = (int(v) for v in self.px(*st['chin']))
            if not green and cy > by:
                for y in range(by + 6, cy - 14, 14): cv2.line(img, (cx, y), (cx, min(cy - 14, y + 6)), (240, 240, 245), 2, cv2.LINE_AA)
            cv2.circle(img, (cx, cy), 15, col, 3, cv2.LINE_AA)
            if green: cv2.circle(img, (cx, cy), 8, col, -1, cv2.LINE_AA)
        return img

    def chrome(self, img, T, st, lm, live, green, red, s_t):
        pre, post = T < PRE, s_t > self.dur
        # frosted panels first (numpy), then all text / outlines on one overlay
        glass(img, 36, 64, 330, 70, 35)                                       # call pill
        cx0, cy0, cw, ch = OW - 36 - 268, 64, 268, 250                       # rep counter card
        if live: glass(img, cx0, cy0, cw, ch, 34)
        if live: glass(img, 36, 640, 74, 600, 37)                            # height rail
        glass(img, 60, OH - 200, OW - 120, 140, 70, alpha=0.42)              # FaceTime controls
        tx, ty, tw, th = self.tile
        note = self.current_note(T)
        if note and live: glass(img, 36, 1468, 640, 190, 30)
        toast = self.current_toast(T) if live else None
        if toast: glass(img, (OW - toast[3]) // 2, toast[4], toast[3], 116, 58)
        if pre: glass(img, (OW - 640) // 2, 760, 640, 300, 40, alpha=0.55)
        if post: glass(img, 90, 520, OW - 180, 820, 48, alpha=0.6)
        im = Image.fromarray(img).convert('RGBA'); ov = Image.new('RGBA', im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)

        # call pill: live dot, name, timer
        pulse = 0.6 + 0.4 * math.sin(T * 4)
        d.ellipse((60, 89, 80, 109), fill=(*GREEN, int(255 * pulse)))
        text(d, (96, 99), 'Brodie', 30, weight='Semibold', anchor='lm')
        secs = int(47 + T); text(d, (350, 99), f'{secs // 60}:{secs % 60:02d}', 26, GREY, 'Medium', mono=True, anchor='rm')
        hairline(d, 36, 64, 330, 70, 35)
        text(d, (40, 162), '● POSE TRACKING' if live else ('● CALIBRATING' if pre else '● SET COMPLETE'), 18,
             VOLT if live else GREY, 'Semibold', mono=True, a=230, spacing=2)
        if live: text(d, (40, 190), f'33 PTS · {int(round(self.an["fps"]))} FPS · {"ON BAR" if st["on_bar"] else "SEARCHING"}', 18, GREY, 'Medium', mono=True, a=200, spacing=1)

        if live:
            self.counter(d, cx0, cy0, cw, ch, T, st)
            self.rail(d, st, s_t)
            if lm is not None: self.elbow_tag(d, lm, green, red)
            if toast: self.draw_toast(d, toast)
            if note: self.draw_note(d, note, T)
        if pre: self.preroll(d, T)
        if post: self.summary(d, s_t - self.dur)
        self.controls(d)
        self.brodie(im, d, T)
        im = Image.alpha_composite(im, ov)
        return np.asarray(im.convert('RGB'))

    def counter(self, d, x, y, w, h, T, st):
        text(d, (x + 28, y + 40), 'PULL-UPS', 20, GREY, 'Semibold', mono=True, anchor='lm', spacing=3)
        n = sum(1 for t, _ in self.reps if t <= T); last = max([t for t, _ in self.reps if t <= T], default=-9)
        pop = 1 + 0.28 * (1 - ease((T - last) / 0.35))
        col = GREEN if T - last < 0.5 else WHITE
        text(d, (x + 28, y + 150), f'{n:02d}', int(132 * pop), col, 'Bold', anchor='lm')
        halves = sum(1 for t in self.halves if t <= T)
        text(d, (x + w - 28, y + 40), f'{halves} HALF' if halves else 'CLEAN', 18, RED if halves else VOLT, 'Semibold', mono=True, anchor='rm', spacing=2)
        # one dot per pull so far: clean / half
        done = sorted([(t, 'c') for t, _ in self.reps if t <= T] + [(t, 'h') for t in self.halves if t <= T])
        for i, (_, k) in enumerate(done[-9:]):
            cx = x + 36 + i * 25; cy = y + h - 34
            d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=(*(VOLT if k == 'c' else RED), 255))
        hairline(d, x, y, w, h, 34)

    def rail(self, d, st, s_t):
        x, y, w, h = 36, 640, 74, 600
        text(d, (x + w / 2, y - 22), 'HEIGHT', 16, GREY, 'Semibold', mono=True, anchor='mm', spacing=2)
        p = max(0.0, min(1.0, st['progress'] or 0.0)) if st['on_bar'] else 0.0
        top, bot = y + 60, y + h - 26; fy = bot - (bot - top) * p
        d.rounded_rectangle((x + 30, top, x + 44, bot), 7, fill=(255, 255, 255, 40))
        col = GREEN if p >= 0.999 else VOLT
        if p > 0.02: d.rounded_rectangle((x + 30, fy, x + 44, bot), 7, fill=(*col, 255))
        d.line((x + 18, top, x + 56, top), fill=(255, 255, 255, 200), width=3)
        text(d, (x + w / 2, y + 30), f'{int(round((st["progress"] or 0) * 100)) if st["on_bar"] else 0}', 26, WHITE, 'Bold', anchor='mm')
        hairline(d, x, y, w, h, 37)

    def elbow_tag(self, d, lm, green, red):
        best = None
        for sh, el, wr in ((11, 13, 15), (12, 14, 16)):
            if min(lm[sh, 2], lm[el, 2], lm[wr, 2]) > VIS and (best is None or lm[el, 2] > lm[best[1], 2]): best = (sh, el, wr)
        if best is None: return
        a, b, c = (np.array(self.px(lm[i, 0], lm[i, 1])) for i in best)
        v1, v2 = a - b, c - b
        ang = math.degrees(math.acos(np.clip(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-6), -1, 1)))
        side = -1 if b[0] < OW / 2 else 1
        x = b[0] + side * 46; y = b[1]
        s = f'ELBOW {int(ang):3d}°'; f = font(22, 'Semibold', True); tw = d.textlength(s, font=f) + 32
        x0 = x if side > 0 else x - tw
        col = GREEN if green else RED if red else VOLT
        d.rounded_rectangle((x0, y - 22, x0 + tw, y + 22), 22, fill=(12, 12, 14, 200), outline=(*col, 220), width=2)
        text(d, (x0 + 16, y), s, 22, WHITE, 'Semibold', mono=True, anchor='lm')
        d.line((b[0] + side * 12, b[1], x if side > 0 else x, b[1]), fill=(*col, 180), width=2)

    def current_toast(self, T):
        ev = [(t, 'c', v) for t, v in self.reps] + [(t, 'h', None) for t in self.halves]
        ev = [e for e in ev if 0 <= T - e[0] < 1.3]
        if not ev: return None
        t, k, v = max(ev)
        age = T - t
        w = 470 if k == 'c' else 600
        return (k, v, age, w, 900)

    def draw_toast(self, d, toast):
        k, v, age, w, y = toast
        x = (OW - w) // 2; a = int(255 * min(1, age / 0.12) * (1 - ease((age - 1.0) / 0.3)))
        col = GREEN if k == 'c' else RED
        d.ellipse((x + 22, y + 22, x + 94, y + 94), fill=(*col, a))
        if k == 'c': d.line((x + 40, y + 59, x + 53, y + 72, x + 77, y + 45), fill=(10, 10, 10, a), width=7, joint='curve')
        else:
            d.line((x + 44, y + 44, x + 72, y + 72), fill=(255, 255, 255, a), width=7); d.line((x + 72, y + 44, x + 44, y + 72), fill=(255, 255, 255, a), width=7)
        text(d, (x + 118, y + 44), f'REP {v}' if k == 'c' else 'HALF REP', 40, WHITE, 'Bold', anchor='lm', a=a)
        text(d, (x + 118, y + 84), 'CHIN CLEARED THE BAR' if k == 'c' else "CHIN BELOW THE BAR · DIDN'T COUNT", 18, col, 'Semibold', mono=True, anchor='lm', a=a, spacing=1)
        d.rounded_rectangle((x, y, x + w, y + 116), 58, outline=(255, 255, 255, int(a * 0.18)), width=2)

    def current_note(self, T):
        cur = [n for n in self.notes if 0 <= T - n[0] < max(3.0, n[2] + 1.2)]
        return cur[-1] if cur else None

    def draw_note(self, d, note, T):
        start, line, dur, nt = note; age = T - start
        a = int(255 * min(1, age / 0.2) * (1 - ease((age - 2.6) / 0.4)))
        x, y = 36, 1468; p = nt.get('pull') or {}
        col = RED if nt['kind'] == 'half' else VOLT
        title = {'half': 'HALF REP', 'praise': 'CLEAN REP', 'recover': 'BACK TO FULL RANGE'}[nt['kind']]
        text(d, (x + 30, y + 38), f'FORM CHECK · {title}', 18, col, 'Semibold', mono=True, anchor='lm', a=a, spacing=2)
        fix = {'half': 'Chin stopped under the bar. Pull higher.', 'praise': 'Chin well over the bar. Full hang.',
               'recover': 'Full range again. Keep it there.'}[nt['kind']]
        text(d, (x + 30, y + 92), fix, 30, WHITE, 'Semibold', anchor='lm', a=a)
        if p:
            m = f'HEIGHT {int(round(p.get("max_progress", 0) * 100))}%   ELBOW MIN {int(round(p.get("min_elbow", 0)))}°'
            text(d, (x + 30, y + 146), m, 20, GREY, 'Medium', mono=True, anchor='lm', a=a, spacing=1)
        d.rounded_rectangle((x, y, x + 640, y + 190), 30, outline=(255, 255, 255, int(a * 0.18)), width=2)
        d.rounded_rectangle((x, y + 30, x + 6, y + 160), 3, fill=(*col, a))

    def preroll(self, d, T):
        x, y, w = (OW - 640) // 2, 760, 640
        connected = T > 0.55
        text(d, (OW / 2, y + 62), 'FaceTime', 24, GREY, 'Medium', anchor='mm')
        text(d, (OW / 2, y + 122), 'Brodie' if connected else 'Connecting…', 52, WHITE, 'Bold', anchor='mm')
        text(d, (OW / 2, y + 190), 'CALIBRATING POSE · FINDING THE BAR' if connected else 'RINGING', 18, VOLT, 'Semibold', mono=True, anchor='mm', spacing=2)
        bw = 440; p = ease((T - 0.55) / (PRE - 0.8)) if connected else 0
        d.rounded_rectangle((OW / 2 - bw / 2, y + 236, OW / 2 + bw / 2, y + 244), 4, fill=(255, 255, 255, 40))
        if p > 0: d.rounded_rectangle((OW / 2 - bw / 2, y + 236, OW / 2 - bw / 2 + bw * p, y + 244), 4, fill=(*VOLT, 255))
        d.rounded_rectangle((x, y, x + w, y + 300), 40, outline=(255, 255, 255, 46), width=2)
        if connected:                                                          # scan line sweeping the frame
            sy = int(220 + (OH - 500) * ((T - 0.55) / (PRE - 0.55)) % (OH - 500))
            for k in range(26): d.line((0, sy - k * 3, OW, sy - k * 3), fill=(*VOLT, int(70 * (1 - k / 26))), width=3)

    def summary(self, d, age):
        a = int(255 * ease(age / 0.5)); x, y, w = 90, 520, OW - 180
        clean = len(self.reps); halves = len(self.halves)
        cp = [p for p in self.pulls if p['counted']]
        tempo = np.mean(np.diff([t for t, _ in self.reps])) if clean > 1 else 0
        best = max([p['max_progress'] for p in cp], default=0)
        text(d, (x + 60, y + 80), 'SET COMPLETE', 22, VOLT, 'Semibold', mono=True, anchor='lm', a=a, spacing=4)
        text(d, (x + 60, y + 150), 'Pull-ups', 56, WHITE, 'Bold', anchor='lm', a=a)
        n = int(round(clean * ease((age - 0.2) / 0.9)))
        text(d, (x + 52, y + 330), f'{n}', 230, VOLT, 'Bold', anchor='ls', a=a)
        text(d, (x + 60 + 150 * len(str(clean)), y + 300), 'clean reps', 40, WHITE, 'Semibold', anchor='ls', a=a)
        stats = [(f'{halves}', 'HALF REPS', RED if halves else WHITE), (f'{tempo:.1f}s', 'AVG TEMPO', WHITE), (f'{int(best * 100)}%', 'BEST HEIGHT', WHITE)]
        for i, (v, lab, col) in enumerate(stats):
            sx = x + 60 + i * 300
            text(d, (sx, y + 450), v, 64, col, 'Bold', anchor='ls', a=a)
            text(d, (sx, y + 492), lab, 18, GREY, 'Semibold', mono=True, anchor='ls', a=a, spacing=2)
        done = sorted([(t, 'c') for t, _ in self.reps] + [(t, 'h') for t in self.halves])
        for i, (_, k) in enumerate(done):
            bx = x + 60 + i * 86; ba = int(a * ease((age - 0.4 - i * 0.08) / 0.3))
            d.rounded_rectangle((bx, y + 560, bx + 70, y + 640), 18, fill=(*(VOLT if k == 'c' else RED), ba))
            text(d, (bx + 35, y + 600), '✓' if k == 'c' else '½', 34, (10, 10, 10), 'Bold', anchor='mm', a=ba)
        text(d, (x + 60, y + 712), 'Half reps flagged: chin stayed under the bar.' if halves else 'Every rep cleared the bar.', 26, GREY, 'Medium', anchor='lm', a=a)
        d.rounded_rectangle((x, y, x + w, y + 820), 48, outline=(255, 255, 255, int(a * 0.2)), width=2)

    def controls(self, d):
        y = OH - 200; cy = y + 70; xs = [200, 370, 540, 710]
        for i, cx in enumerate(xs):
            d.ellipse((cx - 46, cy - 46, cx + 46, cy + 46), fill=(255, 255, 255, 46))
            if i == 0:                                                         # speaker
                d.polygon([(cx - 18, cy - 8), (cx - 8, cy - 8), (cx + 4, cy - 20), (cx + 4, cy + 20), (cx - 8, cy + 8), (cx - 18, cy + 8)], fill=WHITE)
                d.arc((cx - 8, cy - 16, cx + 20, cy + 16), -50, 50, fill=WHITE, width=4)
            elif i == 1:                                                       # camera
                d.rounded_rectangle((cx - 24, cy - 14, cx + 8, cy + 14), 5, fill=WHITE); d.polygon([(cx + 10, cy), (cx + 24, cy - 12), (cx + 24, cy + 12)], fill=WHITE)
            elif i == 2:                                                       # mic
                d.rounded_rectangle((cx - 9, cy - 24, cx + 9, cy + 6), 9, fill=WHITE); d.arc((cx - 17, cy - 12, cx + 17, cy + 16), 0, 180, fill=WHITE, width=4)
                d.line((cx, cy + 16, cx, cy + 24), fill=WHITE, width=4)
            else:                                                              # share / effects: three dots
                for k in (-14, 0, 14): d.ellipse((cx + k - 5, cy - 5, cx + k + 5, cy + 5), fill=WHITE)
        ex = 900
        d.ellipse((ex - 50, cy - 50, ex + 50, cy + 50), fill=(*RED, 255))
        d.arc((ex - 30, cy - 10, ex + 30, cy + 34), 200, 340, fill=WHITE, width=10)
        hairline(d, 60, y, OW - 120, 140, 70, 40)

    def brodie(self, im, d, T):
        tx, ty, tw, th = self.tile
        sp = self.speaking(T)
        if T >= self.blink_at: self.av._blink_left = 1; self.blink_at = T + 3.2 + (T * 7.3) % 2.0
        face = self.av.frame(speaking=sp is not None, now=T).convert('RGB')
        fw, fh = face.size; sc = max(tw / fw, th / fh)
        face = face.resize((int(fw * sc), int(fh * sc)), Image.LANCZOS)
        face = face.crop(((face.width - tw) // 2, (face.height - th) // 2, (face.width - tw) // 2 + tw, (face.height - th) // 2 + th))
        m = Image.fromarray((rmask(tw, th, 34)[..., 0] * 255).astype(np.uint8))
        if sp:                                                                 # speaking glow behind the tile
            g = Image.new('RGBA', im.size, (0, 0, 0, 0)); gd = ImageDraw.Draw(g)
            gd.rounded_rectangle((tx - 6, ty - 6, tx + tw + 6, ty + th + 6), 40, fill=(*VOLT, 150))
            im.alpha_composite(g.filter(ImageFilter.GaussianBlur(18)))
        im.paste(face, (tx, ty), m)
        d.rounded_rectangle((tx, ty, tx + tw, ty + th), 34, outline=(*(VOLT if sp else (255, 255, 255)), 255 if sp else 60), width=4 if sp else 2)
        # name + live waveform
        d.rounded_rectangle((tx + 14, ty + th - 58, tx + 160, ty + th - 14), 22, fill=(0, 0, 0, 140))
        text(d, (tx + 30, ty + th - 36), 'Brodie', 22, WHITE, 'Semibold', anchor='lm')
        for k in range(4):
            amp = (0.35 + 0.65 * abs(math.sin(T * 13 + k * 1.7))) if sp else 0.18
            bh = 4 + 18 * amp; bx = tx + 116 + k * 9
            d.rounded_rectangle((bx, ty + th - 36 - bh / 2, bx + 5, ty + th - 36 + bh / 2), 2, fill=(*VOLT, 255))
        cap = self.caption(T)
        if cap: self.draw_caption(d, *cap)

    def caption(self, T):
        """Brodie's current line as a subtitle (most feeds autoplay muted): held at least 1.6 s so a one-word count reads."""
        cur = [(st, txt, d) for st, txt, d, _ in self.lines if st <= T < st + max(d + 0.35, 1.6)]
        if not cur: return None
        st, txt, d = cur[-1]; return txt, T - st, d

    def draw_caption(self, d, line, age, dur):
        """Big two-tone subtitle above Brodie's tile, words lighting up as he says them."""
        size = 50 if len(line) < 22 else 42; f = font(size, 'Bold'); maxw = OW - 72 - 56
        words, rows, row = line.split(), [], ''
        for w in words:
            t = (row + ' ' + w).strip()
            if d.textlength(t, font=f) > maxw and row: rows.append(row); row = w
            else: row = t
        rows.append(row)
        lh = int(size * 1.22); bw = max(d.textlength(r, font=f) for r in rows) + 56; bh = lh * len(rows) + 82
        tx, ty, tw, th = self.tile
        x1 = OW - 36; x0 = x1 - bw; y1 = ty - 22; y0 = y1 - bh
        a = int(255 * min(1, age / 0.12)); rise = int(14 * (1 - ease(age / 0.25)))
        y0 += rise; y1 += rise
        d.rounded_rectangle((x0, y0, x1, y1), 34, fill=(10, 10, 14, int(a * 0.88)), outline=(*VOLT, int(a * 0.7)), width=3)
        d.polygon([(x1 - 92, y1), (x1 - 58, y1), (x1 - 70, y1 + 20)], fill=(10, 10, 14, int(a * 0.88)))
        text(d, (x0 + 28, y0 + 32), 'BRODIE', 18, VOLT, 'Bold', mono=True, anchor='lm', a=a, spacing=3)
        n_lit = len(words) if dur <= 0 else max(1, math.ceil(len(words) * min(1.0, (age + 0.15) / max(dur * 0.85, 0.2))))
        k = 0
        for i, r in enumerate(rows):
            x = x0 + 28; y = y0 + 58 + i * lh + lh / 2
            for w in r.split():
                text(d, (x, y), w, size, WHITE if k < n_lit else (120, 120, 128), 'Bold', anchor='lm', a=a)
                x += d.textlength(w + ' ', font=f); k += 1

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True); ap.add_argument('--out', default=None); ap.add_argument('--pose', default='full')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.video)[0] + '.call.mp4'
    print('analysing…', flush=True)
    an = analyse(a.video, a.pose)
    if not an['n']: raise SystemExit('no frames read')
    bank = CueBank(); lines = script(an, bank)
    for st, txt, d, _ in lines: print(f'  {st - PRE:6.2f}s  Brodie: {txt}')
    fps = an['fps']; total = PRE + an['n'] / fps + POST
    wav = tempfile.NamedTemporaryFile(suffix='.wav', delete=False).name; mix(lines, bank, total, wav)
    cap = cv2.VideoCapture(a.video); ok, first = cap.read()
    sh, sw = first.shape[:2]; r = Renderer(an, lines, sw, sh)
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{OW}x{OH}', '-r', f'{fps}', '-i', '-',
                           '-i', wav, '-c:v', 'libx264', '-preset', 'medium', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
                           '-movflags', '+faststart', '-shortest', out], stdin=subprocess.PIPE)
    cur = cv2.cvtColor(first, cv2.COLOR_BGR2RGB); nsrc = 1; nframes = int(total * fps)
    print(f'rendering {nframes} frames…', flush=True)
    for k in range(nframes):
        T = k / fps; want = int((T - PRE) * fps)
        while nsrc <= want and nsrc < an['n']:
            ok, bgr = cap.read()
            if not ok: break
            cur = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); nsrc += 1
        ff.stdin.write(r.frame(cur, T).tobytes())
    ff.stdin.close(); ff.wait(); cap.release(); os.remove(wav)
    summary = dict(video=a.video, reps=len(r.reps), half_reps=len(r.halves), rep_times=[round(t - PRE, 2) for t, _ in r.reps],
                   lines=[dict(t=round(s - PRE, 2), text=t) for s, t, _, _ in lines], pulls=an['pulls'])
    with open(os.path.splitext(out)[0] + '.json', 'w') as f: json.dump(summary, f, indent=1, default=float)
    print(f'{len(r.reps)} reps, {len(r.halves)} half reps -> {out}')


if __name__ == '__main__':
    main()
