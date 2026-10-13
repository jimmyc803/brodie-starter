"""The website's visual language (pushup-web/app/globals.css) for the call video, as cached RGBA sprites.

Paper canvas, ink #16120e, fluoro pink + riso blue + yellow spot colours, ink borders, hard offset shadows, the site's
faces: display = Anton (poster condensed), mono = Space Mono Bold (eyebrows, ticket stubs, tracked uppercase); both SIL
OFL in assets/fonts/ (Oswald Bold is the fallback when Anton is missing). Every text, pill and card is rendered once
with PIL at 2x, downsampled, and cached by its content, so drawing one per frame is a small alpha blit. A text line is
(text, px, colour) in the display face or (text, px, colour, 'mono') in the tracked mono face.

    rgb, a = text('GOOD REP', 48, INK)
    rgb, a = pill([('CAMERA ANGLE GOOD', 30, INK)], fill=GOOD, icon='check')
    blit(canvas, rgb, a, x, y)                       # in place, clipped
"""
from __future__ import annotations

import os
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from facetime import ROOT

FONT_DIR = os.path.join(ROOT, 'assets', 'fonts')
FONT_PATH = os.path.join(FONT_DIR, 'Anton-Regular.ttf')
FALLBACK_PATH = os.path.join(FONT_DIR, 'Oswald-Bold.ttf')
MONO_PATH = os.path.join(FONT_DIR, 'SpaceMono-Bold.ttf')
MONO_TRACK = 0.14             # the site's .eyebrow letter-spacing (em)
CANVAS = (242, 236, 223)      # --color-canvas #f2ecdf
SURFACE = (248, 244, 234)
INK = (22, 18, 14)            # --color-ink
INK2 = (75, 68, 57)
PINK = (255, 61, 151)         # --color-pink
YELLOW = (255, 216, 58)       # --color-yellow
BLUE = (35, 70, 216)          # --color-blue (the overprint)
SURFACE2 = (233, 225, 207)    # --color-surface-2
INK3 = (111, 103, 90)         # --color-ink-3
SITE_GOOD = (17, 128, 74)     # --color-good (cards, stamps)
SITE_BAD = (198, 42, 26)      # --color-bad
LIVE = (255, 59, 31)          # --color-live
GOOD = (34, 197, 94)          # skeleton green (bright on video)
BAD = (239, 68, 68)           # skeleton red
WHITE = (255, 253, 248)
SS = 2                        # supersampling for sprites


@lru_cache(maxsize=96)
def font(px, face='display'):
    for path in ((MONO_PATH,) if face == 'mono' else (FONT_PATH, FALLBACK_PATH)):
        try:
            return ImageFont.truetype(path, int(px))
        except OSError:
            continue
    return ImageFont.load_default(int(px))


def _bbox(s, px, face='display'):
    """(l, t, r, b) of a line at SS scale; mono lines are tracked (MONO_TRACK em after every letter but the last)."""
    f = font(px * SS, face); l, t, r, b = f.getbbox(s)
    if face == 'mono' and len(s) > 1: r += int(round(MONO_TRACK * px * SS * (len(s) - 1)))
    return l, t, r, b


def _draw_line(d, xy, s, px, color, face='display'):
    f = font(px * SS, face)
    if face != 'mono':
        d.text(xy, s, font=f, fill=tuple(color) + (255,)); return
    x, y = xy; tr = MONO_TRACK * px * SS
    for ch in s:
        d.text((x, y), ch, font=f, fill=tuple(color) + (255,)); x += f.getlength(ch) + tr


def _parts(line):
    s, px, col = line[:3]
    return s, px, col, (line[3] if len(line) > 3 else 'display')


def _down(im):
    """PIL RGBA at SS x -> (rgb uint8, alpha float32 HxWx1), premultiplied downsample."""
    a = np.asarray(im).astype(np.float32)
    al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, al], axis=2)
    h, w = a.shape[:2]
    small = cv2.resize(pm, (max(1, w // SS), max(1, h // SS)), interpolation=cv2.INTER_AREA)
    alpha = np.clip(small[..., 3:4], 0.0, 1.0)
    rgb = np.where(alpha > 1e-4, small[..., :3] / np.maximum(alpha, 1e-4), 0.0)
    return np.clip(rgb, 0, 255).astype(np.uint8), alpha.astype(np.float32)


def text_size(s, px, face='display'):
    l, t, r, b = _bbox(s, px, face)
    return (r - l) / SS, (b - t) / SS


@lru_cache(maxsize=512)
def text(s, px, color, stroke=0, stroke_color=INK, face='display', offset=None, offset_color=BLUE):
    """One line. offset (dx, dy) px: the site's misregistered overprint, a copy in offset_color behind the text."""
    if face == 'mono' and not stroke and offset is None:
        l, t, r, b = _bbox(s, px, face)
        im = Image.new('RGBA', (r - l + 4, b - t + 4), (0, 0, 0, 0))
        _draw_line(ImageDraw.Draw(im), (2 - l, 2 - t), s, px, color, face)
        return _down(im)
    f = font(px * SS, face); l, t, r, b = f.getbbox(s, stroke_width=stroke * SS)
    ox, oy = (int(round(offset[0] * SS)), int(round(offset[1] * SS))) if offset else (0, 0)
    im = Image.new('RGBA', (r - l + 4 + abs(ox), b - t + 4 + abs(oy)), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    x0, y0 = 2 - l + max(0, -ox), 2 - t + max(0, -oy)
    if offset:
        d.text((x0 + ox, y0 + oy), s, font=f, fill=tuple(offset_color) + (255,), stroke_width=stroke * SS, stroke_fill=tuple(offset_color) + (255,))
    d.text((x0, y0), s, font=f, fill=tuple(color) + (255,), stroke_width=stroke * SS, stroke_fill=tuple(stroke_color) + (255,))
    return _down(im)


def _icon(d, kind, cx, cy, r, fill):
    """Icons drawn (fonts have no ticks): a disc with an ink border and a tick / bang / cross; 'dot' = the site's
    LIVE NOW dot (a plain disc in `fill`)."""
    lw = max(2, int(r * 0.24))
    if kind == 'dot':
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(fill) + (255,), outline=INK + (255,), width=max(2, int(r * 0.2)))
        return
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WHITE + (255,), outline=INK + (255,), width=max(2, int(r * 0.14)))
    if kind == 'check':
        d.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.38), (cx + r * 0.5, cy - r * 0.35)], fill=fill + (255,), width=lw, joint='curve')
    elif kind == 'bang':
        d.line([(cx, cy - r * 0.5), (cx, cy + r * 0.12)], fill=INK + (255,), width=lw)
        rr = lw * 0.6; d.ellipse([cx - rr, cy + r * 0.42 - rr, cx + rr, cy + r * 0.42 + rr], fill=INK + (255,))
    elif kind == 'cross':
        k = r * 0.36
        d.line([(cx - k, cy - k), (cx + k, cy + k)], fill=fill + (255,), width=lw); d.line([(cx - k, cy + k), (cx + k, cy - k)], fill=fill + (255,), width=lw)


@lru_cache(maxsize=256)
def pill(lines, fill, icon=None, radius=None, pad=(22, 12), border=3, shadow=5, min_w=0, max_w=10000, align='left', gap=2,
         icon_fill=None, icon_px=None):
    """A bordered card with a hard offset shadow. lines: tuple of (text, px, colour[, face]); icon: None/'check'/'bang'/
    'cross'/'dot' (a disc the height of the text block, or icon_px, on the left; icon_fill its colour, default the card's
    fill). radius None = fully rounded (a pill)."""
    lines = tuple(lines)
    sizes = [(_bbox(*_parts(ln)[:2], _parts(ln)[3]), _parts(ln)[1]) for ln in lines]
    th = sum((b - t) for (l, t, r, b), _ in sizes) + gap * SS * (len(lines) - 1)
    tw = max((r - l) for (l, t, r, b), _ in sizes) if lines else 0
    px_, py_ = pad[0] * SS, pad[1] * SS
    ic = int((icon_px * SS if icon_px else min(th, 46 * SS)) if icon else 0)
    iw = ic + (14 * SS if icon else 0)
    w = int(max(min_w * SS, tw + iw + 2 * px_)); w = int(min(w, max_w * SS)); h = int(th + 2 * py_)
    b, sh = border * SS, shadow * SS
    im = Image.new('RGBA', (w + sh + b, h + sh + b), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    rad = h // 2 if radius is None else radius * SS
    if sh: d.rounded_rectangle([sh, sh, w + sh - 1, h + sh - 1], rad, fill=INK + (255,))
    d.rounded_rectangle([0, 0, w - 1, h - 1], rad, fill=tuple(fill) + (255,), outline=INK + (255,), width=b)
    x = px_
    if icon:
        _icon(d, icon, x + ic / 2, h / 2, ic / 2, tuple(icon_fill or fill)); x += iw
    y = py_
    for ((l, t, r, bb), px), ln in zip(sizes, lines):
        s, _, col, face = _parts(ln)
        xx = x if align == 'left' else (w - (r - l)) / 2
        _draw_line(d, (xx - l, y - t), s, px, col, face)
        y += (bb - t) + gap * SS
    return _down(im)


def blit(img, rgb, a, x, y, opacity=1.0):
    H, W = img.shape[:2]; h, w = a.shape[:2]; x, y = int(x), int(y)
    X0, Y0, X1, Y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if X1 <= X0 or Y1 <= Y0: return
    al = a[Y0 - y:Y1 - y, X0 - x:X1 - x]
    if opacity < 1.0: al = al * opacity
    s = rgb[Y0 - y:Y1 - y, X0 - x:X1 - x].astype(np.float32)
    roi = img[Y0:Y1, X0:X1]
    roi[:] = (s * al + roi.astype(np.float32) * (1.0 - al)).astype(np.uint8)


def transform(rgb, a, scale=1.0, angle=0.0):
    """Rotate (degrees, counter-clockwise) and scale a sprite about its centre; returns a sprite that holds it."""
    if scale == 1.0 and angle == 0.0: return rgb, a
    h, w = a.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
    cos, sin = abs(M[0, 0]), abs(M[0, 1])
    nw, nh = int(h * sin + w * cos) + 2, int(h * cos + w * sin) + 2
    M[0, 2] += nw / 2 - w / 2; M[1, 2] += nh / 2 - h / 2
    r2 = cv2.warpAffine(rgb, M, (nw, nh), flags=cv2.INTER_LINEAR)
    a2 = cv2.warpAffine(a[..., 0], M, (nw, nh), flags=cv2.INTER_LINEAR)[..., None]
    return r2, a2


def wrap(s, px, max_w):
    words = s.split(); lines, cur = [], ''
    for w_ in words:
        t = (cur + ' ' + w_).strip()
        if text_size(t, px)[0] <= max_w or not cur: cur = t
        else: lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines


@lru_cache(maxsize=32)
def bubble(lines, px, max_w, tail='right', radius=10, tail_at=0.8):
    """A speech bubble (the website's): paper card, ink border, hard shadow, a tail on one side: 'right' (a square tail
    at 62 % height), 'down' (a triangle under the card at tail_at of its width, like the site's hero bubble) or 'none'."""
    lines = tuple(lines)
    f = font(px * SS); lh = int(px * SS * 1.18)
    tw = max(f.getbbox(s)[2] - f.getbbox(s)[0] for s in lines)
    padx, pady, b, sh, tl = 20 * SS, 14 * SS, 3 * SS, 5 * SS, 16 * SS
    w = int(min(max_w * SS, tw + 2 * padx)); h = int(lh * len(lines) + 2 * pady - (lh - px * SS))
    W2 = w + sh + b + (tl if tail == 'right' else 0); H2 = h + sh + b + (tl + b if tail == 'down' else 0)
    im = Image.new('RGBA', (W2, H2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    if tail == 'right':
        ty = int(h * 0.62)
        tail_pts = [(w - b * 2, ty - tl), (w + tl, ty), (w - b * 2, ty + tl * 0.4)]
    elif tail == 'down':
        tx = int(w * tail_at)
        tail_pts = [(tx - tl, h - b * 2), (tx, h + tl), (tx + tl * 0.2, h - b * 2)]
    else:
        tail_pts = None
    if tail_pts: d.polygon([(x + sh, y + sh) for x, y in tail_pts], fill=INK + (255,))
    d.rounded_rectangle([sh, sh, w + sh - 1, h + sh - 1], radius * SS, fill=INK + (255,))
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius * SS, fill=SURFACE + (255,), outline=INK + (255,), width=b)
    if tail_pts:
        d.polygon(tail_pts, fill=SURFACE + (255,))
        d.line(tail_pts, fill=INK + (255,), width=b, joint='curve')
    y = pady
    for s in lines:
        l, t, r, bb = f.getbbox(s)
        d.text((padx - l, y - t), s, font=f, fill=INK + (255,))
        y += lh
    return _down(im)
