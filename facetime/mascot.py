"""Brodie the mascot (the website's flat cartoon, pushup-web/assets/brodie.png), animated for the call video.

The 314x320 art is re-rendered crisp at any size: its two inks (cream body, black outline) become a soft alpha and an
ink-ness map, upsampled 4x with a cubic filter and re-sharpened (a cheap vectorisation of flat art), with the face
features painted out. Eyes, brows and mouth are drawn back as vector shapes (4x supersampled, then downsampled) so he
can blink, talk and react. Composed sprites are cached per (size, eyes, brows, mouth, effect).

    m = Mascot(height=230)
    m.draw(canvas_rgb, cx=600, feet_y=1000, now=t, speaking=True)            # breathing, blinking, talking
    m.react('good', now=t)  /  m.react('bad', now=t)                          # hop + flex lines / shake + frown

Animation: breathing squash/stretch anchored at the feet; a blink every few seconds; while speaking the mouth cycles
open shapes; 'good' = two hops, happy eyes, raised brows, a big grin, flex marks and sparkles; 'bad' = a head shake,
angry brows, a gritted-teeth grimace and a sweat drop. A hard offset shadow (the website's drop-shadow) sits under him.
"""
from __future__ import annotations

import math
import os
import random
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw

from facetime import ROOT

ART = os.path.join(ROOT, 'pushup-web', 'assets', 'brodie.png')
INK = (22, 18, 14)                     # --color-ink #16120e
CREAM = (239, 230, 217)                # the art's body colour
WHITE = (255, 253, 248)
PINK = (255, 61, 151)                  # --color-pink
YELLOW = (255, 216, 58)                # --color-yellow
BLUE = (35, 70, 216)                   # --color-blue
UP = 4                                 # vectorisation upsample
PAD = 0.16                             # sprite padding around the art (effects, squash) as a fraction of the art size
REACT_S = 1.2

# feature geometry in the original art's pixels (314 x 320)
EYES = ((138.0, 80.0), (191.0, 79.0)); EYE_R = (7.6, 10.6)
BROWS = {'normal': (((125, 57), (147, 64)), ((181, 63), (200, 56))),
         'angry': (((125, 54), (148, 67)), ((180, 67), (201, 53))),
         'raised': (((125, 51), (147, 55)), ((181, 55), (201, 50)))}
PAINT_OUT = [(120, 47, 154, 95), (175, 46, 207, 94), (128, 92, 200, 131)]   # eyes + brows, mouth (x0, y0, x1, y1)
FACE = (112, 40, 214, 140)             # the region the features are drawn in
TALK = ['talk_small', 'talk_open', 'grin', 'talk_o', 'closed', 'talk_open', 'talk_small', 'grin']


def _q(p0, p1, p2, n=16):
    return [((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
             (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]) for t in (i / n for i in range(n + 1))]


def _c(p0, p1, p2, p3, n=20):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3))
            for t in (i / n for i in range(n + 1))]


@lru_cache(maxsize=2)
def _base(path=ART):
    """The art at UP x: (rgb uint8, alpha float32) with the face features painted out."""
    a = np.asarray(Image.open(path).convert('RGBA')).astype(np.float32)
    rgb, al = a[..., :3], a[..., 3] / 255.0
    lum = rgb @ np.array([0.299, 0.587, 0.114], np.float32)
    k = np.clip((228.0 - lum) / (228.0 - 24.0), 0.0, 1.0)            # ink-ness: 0 cream (and the white teeth), 1 ink
    for x0, y0, x1, y1 in PAINT_OUT: k[y0:y1, x0:x1] = 0.0
    h, w = al.shape
    A = cv2.resize(al, (w * UP, h * UP), interpolation=cv2.INTER_CUBIC)
    K = cv2.resize(k * al, (w * UP, h * UP), interpolation=cv2.INTER_CUBIC)
    K = np.where(A > 1e-3, K / np.maximum(A, 1e-3), 0.0)
    sharpen = lambda x: np.clip((x - 0.5) * (UP / 1.6) + 0.5, 0.0, 1.0)
    A, K = sharpen(A), sharpen(K)
    col = np.array(CREAM, np.float32) * (1 - K[..., None]) + np.array(INK, np.float32) * K[..., None]
    return col.astype(np.uint8), A.astype(np.float32)


def _features(eyes, brows, mouth, fx, box):
    """Face features and / or an effect as a PIL RGBA layer at UP x covering `box` (art px, x0, y0, x1, y1)."""
    bx0, by0, bx1, by1 = box
    lay = Image.new('RGBA', (int((bx1 - bx0) * UP), int((by1 - by0) * UP)), (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    P = lambda x, y: ((x - bx0) * UP, (y - by0) * UP)
    def line(pts, width, fill=INK):
        q = [P(*p) for p in pts]; wd = int(width * UP)
        d.line(q, fill=fill + (255,), width=wd, joint='curve')
        for e in (q[0], q[-1]): d.ellipse([e[0] - wd / 2, e[1] - wd / 2, e[0] + wd / 2, e[1] + wd / 2], fill=fill + (255,))
    def poly(pts, fill, outline=3.4):
        q = [P(*p) for p in pts]
        d.polygon(q, fill=fill + (255,))
        if outline: line(pts + [pts[0]], outline)
    # eyes
    for (cx, cy) in (EYES if eyes else ()):
        rx, ry = EYE_R
        if eyes == 'open':
            d.ellipse([*P(cx - rx, cy - ry), *P(cx + rx, cy + ry)], fill=INK + (255,))
        elif eyes == 'closed':
            line(_q((cx - 8, cy + 1), (cx, cy + 6), (cx + 8, cy + 1)), 3.6)
        elif eyes == 'happy':
            line(_q((cx - 8, cy + 4), (cx, cy - 8), (cx + 8, cy + 4)), 3.8)
    for a, b in (BROWS[brows] if brows else ()):
        line([a, b], 7.0)
    # mouth
    if mouth == 'grin':                                   # the art's grin
        top = _q((133, 99), (164, 106), (196, 99)); bot = _c((196, 99), (195, 131), (133, 131), (133, 99))
        poly(top + bot[1:-1], WHITE)
        line([(140, 111), (152, 113)], 2.4); line([(182, 112), (190, 110)], 2.4)
    elif mouth == 'yell':                                 # good rep: wide open grin
        top = _q((130, 97), (164, 103), (198, 97)); bot = _q((198, 97), (164, 160), (130, 97))
        poly(top + bot[1:-1], INK)
        teeth = _q((133, 99), (164, 105), (195, 99)) + _q((195, 99), (164, 117), (133, 99))[1:-1]
        poly(teeth, WHITE, outline=0)
        d.ellipse([*P(152, 116), *P(176, 128)], fill=PINK + (255,))
        line(top + bot[1:], 3.4)
    elif mouth in ('talk_small', 'talk_open'):
        dep = 130 if mouth == 'talk_small' else 150; x0, x1 = (140, 188) if mouth == 'talk_small' else (136, 192)
        top = _q((x0, 100), (164, 106), (x1, 100)); bot = _q((x1, 100), (164, dep), (x0, 100))
        poly(top + bot[1:-1], INK)
        teeth = _q((x0 + 3, 101), (164, 107), (x1 - 3, 101)) + _q((x1 - 3, 101), (164, 113 if mouth == 'talk_small' else 115), (x0 + 3, 101))[1:-1]
        poly(teeth, WHITE, outline=0)
        if mouth == 'talk_open': d.ellipse([*P(154, 113), *P(174, 124)], fill=PINK + (255,))
        line(top + bot[1:], 3.4)
    elif mouth == 'talk_o':
        d.ellipse([*P(151, 99), *P(177, 124)], fill=INK + (255,))
        d.ellipse([*P(157, 113), *P(171, 122)], fill=PINK + (255,))
    elif mouth == 'closed':
        line(_q((138, 103), (164, 120), (190, 103)), 3.8)
    elif mouth == 'frown':                                # no rep: gritted teeth, corners down
        top = _q((136, 110), (164, 96), (192, 110)); bot = _q((192, 110), (164, 126), (136, 110))
        poly(top + bot[1:-1], WHITE)
        line(_q((139, 110), (164, 110), (189, 110)), 2.4)
        for x in (150, 164, 178): line([(x, 104 if x == 164 else 105), (x, 116 if x == 164 else 115)], 2.2)
        line(top + bot[1:], 3.4)
    # effects
    if fx == 'flex':
        for cx, cy, sgn in ((50, 92, -1), (265, 88, 1)):                  # power marks off the fists
            for ang in (-20, -55, -90):
                a = math.radians(180 - ang if sgn < 0 else ang)
                r0, r1 = 34, 50
                line([(cx + math.cos(a) * r0, cy + math.sin(a) * r0), (cx + math.cos(a) * r1, cy + math.sin(a) * r1)], 4.2)
        for sx, sy, r in ((40, 30, 13), (280, 36, 10), (250, 0, 7)):     # sparkles
            pts = []
            for i in range(8):
                rr = r if i % 2 == 0 else r * 0.38; aa = math.pi / 4 * i - math.pi / 2
                pts.append((sx + math.cos(aa) * rr, sy + math.sin(aa) * rr))
            poly(pts, YELLOW, outline=2.6)
    elif fx == 'sweat':
        cx, cy = 228, 54
        pts = _q((cx, cy - 14), (cx + 12, cy + 2), (cx + 7, cy + 8)) + _q((cx - 7, cy + 8), (cx - 12, cy + 2), (cx, cy - 14))
        poly(pts, (120, 180, 255), outline=2.6)
    return lay


def _shrink(lay, s):
    """PIL RGBA at UP x -> (rgb uint8, alpha float32 HxWx1) at scale s of the art (premultiplied area resize)."""
    a = np.asarray(lay).astype(np.float32); al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, al], axis=2)
    h, w = a.shape[:2]
    small = cv2.resize(pm, (max(1, int(round(w * s / UP))), max(1, int(round(h * s / UP)))), interpolation=cv2.INTER_AREA)
    alpha = np.clip(small[..., 3:4], 0, 1)
    return np.where(alpha > 1e-4, small[..., :3] / np.maximum(alpha, 1e-4), 0).astype(np.float32), alpha.astype(np.float32)


def _over(dst_rgb, dst_a, rgb, a, x, y):
    """Composite (rgb, a) over the float sprite (dst_rgb, dst_a) at integer (x, y), in place."""
    h, w = a.shape[:2]; H_, W_ = dst_a.shape[:2]
    X0, Y0, X1, Y1 = max(0, x), max(0, y), min(W_, x + w), min(H_, y + h)
    if X1 <= X0 or Y1 <= Y0: return
    sa = a[Y0 - y:Y1 - y, X0 - x:X1 - x]; sr = rgb[Y0 - y:Y1 - y, X0 - x:X1 - x]
    da = dst_a[Y0:Y1, X0:X1]; dr = dst_rgb[Y0:Y1, X0:X1]
    oa = sa + da * (1 - sa)
    dr[:] = (sr * sa + dr * da * (1 - sa)) / np.maximum(oa, 1e-4); da[:] = oa


@lru_cache(maxsize=8)
def _base_small(height):
    """The padded art (features painted out) at `height`: float (rgb, alpha) and the scale."""
    rgb, al = _base()
    h, w = al.shape; s = height / (h / UP)
    px, py = int(w * PAD), int(h * PAD)
    full = np.zeros((h + 2 * py, w + 2 * px, 4), np.float32)
    full[py:py + h, px:px + w, :3] = rgb; full[py:py + h, px:px + w, 3] = al * 255
    r, a = _shrink(Image.fromarray(full.astype(np.uint8), 'RGBA'), s)
    return r, a, s


FX_BOX = (-40, -30, 354, 150)          # art px: the effects (sparkles, flex marks, sweat) live up here


@lru_cache(maxsize=16)
def _fx_small(height, fx):
    _, _, s = _base_small(height)
    return _shrink(_features(None, None, None, fx, FX_BOX), s)


def _compose(height, eyes, brows, mouth, fx):
    """Padded sprite (rgb uint8, alpha float32 HxWx1) of the art + features (+ effect), `height` px for the art itself."""
    br, ba, s = _base_small(height)
    rgb, a = br.copy(), ba.copy()
    _, al = _base(); pad_x, pad_y = int(al.shape[1] * PAD) / UP, int(al.shape[0] * PAD) / UP     # art px of padding
    fr, fa = _shrink(_features(eyes, brows, mouth, None, FACE), s)
    _over(rgb, a, fr, fa, int(round((FACE[0] + pad_x) * s)), int(round((FACE[1] + pad_y) * s)))
    if fx:
        xr, xa = _fx_small(height, fx)
        _over(rgb, a, xr, xa, int(round((FX_BOX[0] + pad_x) * s)), int(round((FX_BOX[1] + pad_y) * s)))
    return np.clip(rgb, 0, 255).astype(np.uint8), a


class Mascot:
    def __init__(self, height=230, seed=None):
        self.height = int(height)
        self._cache = {}
        self._rng = random.Random(seed)
        self._next_blink = 0.0; self._blink_until = -1.0
        self._mouth_i = 0; self._mouth_t = -1.0
        self.react_kind = None; self.react_t = -1e9
        _, al = _base(); self.art_w = al.shape[1] / UP * self.height / (al.shape[0] / UP)

    def sprite(self, eyes='open', brows='normal', mouth='grin', fx=None):
        key = (eyes, brows, mouth, fx)
        if key not in self._cache: self._cache[key] = _compose(self.height, *key)
        return self._cache[key]

    def warm(self, reactions=True):
        """Pre-compose the expressions a call uses (a few ms each) so the first blink or word does not stall a frame."""
        for eyes in ('open', 'closed'):
            for mouth in ['grin'] + TALK:
                self.sprite(eyes, 'normal', mouth, None)
                if reactions: self.sprite(eyes, 'angry', mouth, 'sweat')
            if reactions: self.sprite(eyes, 'angry', 'frown', 'sweat')
        if reactions:
            for mouth in ['yell'] + TALK: self.sprite('happy', 'raised', mouth, 'flex')

    def react(self, kind, now):
        """'good' or 'bad': the reaction plays for REACT_S seconds from `now`."""
        self.react_kind = kind; self.react_t = float(now)

    def pose(self, now, speaking=False):
        """(eyes, brows, mouth, fx, dx, dy, sx, sy) for time `now`: the animation state, without drawing."""
        since = now - self.react_t
        kind = self.react_kind if 0 <= since < REACT_S else None
        if self._next_blink == 0.0: self._next_blink = now + self._rng.uniform(1.5, 4.0)
        if now >= self._next_blink:
            self._blink_until = now + 0.13; self._next_blink = now + self._rng.uniform(2.8, 5.5)
        eyes = 'closed' if now < self._blink_until else 'open'
        brows = 'normal'; fx = None
        if speaking:
            if now - self._mouth_t > 0.1 or now < self._mouth_t:
                self._mouth_i = (self._mouth_i + self._rng.choice((1, 1, 2))) % len(TALK); self._mouth_t = now
            mouth = TALK[self._mouth_i]
        else:
            mouth = 'grin'
        br = math.sin(now * 2 * math.pi / 3.2)
        sx, sy, dx, dy = 1.0 - 0.006 * br, 1.0 + 0.014 * br, 0.0, 0.0
        if kind == 'good':
            eyes, brows, fx = 'happy', 'raised', 'flex'
            if not speaking: mouth = 'yell'
            hop = since / 0.42
            if hop < 2:
                ph = hop % 1.0; amp = 0.16 if hop < 1 else 0.07
                dy = -amp * self.height * math.sin(math.pi * ph)
                land = max(0.0, 1 - ph / 0.25) if hop >= 1 or ph < 0.25 else 0.0
                sy *= 1 - 0.08 * land * (1 if hop >= 0.2 else 0); sx *= 1 + 0.06 * land * (1 if hop >= 0.2 else 0)
        elif kind == 'bad':
            brows, fx = 'angry', 'sweat'
            if not speaking: mouth = 'frown'
            dx = 0.035 * self.height * math.sin(2 * math.pi * since * 5.5) * max(0.0, 1 - since / 0.8)
        return eyes, brows, mouth, fx, dx, dy, sx, sy

    def draw(self, img, cx, feet_y, now, speaking=False, shadow=True):
        """Brodie onto `img` (RGB uint8, in place): horizontally centred on cx, feet on feet_y."""
        eyes, brows, mouth, fx, dx, dy, sx, sy = self.pose(now, speaking)
        rgb, al = self.sprite(eyes, brows, mouth, fx)
        h, w = al.shape[:2]
        pad_y = h * PAD / (1 + 2 * PAD)                         # sprite rows below the art's feet
        ax, ay = w / 2.0, h - pad_y                             # anchor: feet centre
        M = np.array([[sx, 0, cx + dx - sx * ax], [0, sy, feet_y + dy - sy * ay]], np.float32)
        x0 = int(math.floor(cx + dx - sx * ax)) - 2; y0 = int(math.floor(feet_y + dy - sy * ay)) - 2
        x1 = int(math.ceil(cx + dx + sx * (w - ax))) + 2; y1 = int(math.ceil(feet_y + dy + sy * (h - ay))) + 2
        M[:, 2] -= (x0, y0)
        bw, bh = x1 - x0, y1 - y0
        srgb = cv2.warpAffine(rgb, M, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        sal = cv2.warpAffine(al[..., 0], M, (bw, bh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)[..., None]
        if shadow:
            off = max(3, int(self.height * 0.025))
            _alpha_blit(img, np.full_like(srgb, INK), sal * 0.9, x0 + off, y0 + off)
        _alpha_blit(img, srgb, sal, x0, y0)


def _alpha_blit(img, rgb, a, x, y):
    H, W = img.shape[:2]; h, w = a.shape[:2]
    X0, Y0, X1, Y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if X1 <= X0 or Y1 <= Y0: return
    s = rgb[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32); al = a[Y0 - y:Y1 - y, X0 - x:X1 - x]
    roi = img[Y0:Y1, X0:X1]
    roi[:] = (s * al + roi.astype(np.float32) * (1 - al)).astype(np.uint8)


if __name__ == '__main__':      # python -m facetime.mascot [out.png]: the original next to the rig's expressions
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'data', 'tmp', 'mascot_sheet.png')
    m = Mascot(height=420)
    tiles = []
    orig = Image.open(ART).convert('RGBA'); bg = Image.new('RGBA', orig.size, (242, 236, 223, 255)); bg.alpha_composite(orig)
    o = np.asarray(bg.convert('RGB').resize((int(orig.width * 420 / orig.height), 420), Image.BICUBIC))
    tile = np.full((560, 520, 3), (242, 236, 223), np.uint8); tile[70:490, (520 - o.shape[1]) // 2:(520 - o.shape[1]) // 2 + o.shape[1]] = o
    tiles.append(tile)
    for key in [('open', 'normal', 'grin', None), ('closed', 'normal', 'talk_open', None), ('open', 'normal', 'talk_o', None),
                ('happy', 'raised', 'yell', 'flex'), ('open', 'angry', 'frown', 'sweat')]:
        t = np.full((560, 520, 3), (242, 236, 223), np.uint8)
        rgb, al = m.sprite(*key); h, w = al.shape[:2]
        _alpha_blit(t, rgb, al, (520 - w) // 2, 520 - h + int(h * PAD / (1 + 2 * PAD)) - 30)
        tiles.append(t)
    sheet = np.concatenate([np.concatenate(tiles[:3], 1), np.concatenate(tiles[3:], 1)], 0)
    os.makedirs(os.path.dirname(out), exist_ok=True); cv2.imwrite(out, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR)); print('wrote', out)
