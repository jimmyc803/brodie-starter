"""The website's visual language (pushup-web/app/globals.css) for the call video, as cached RGBA sprites.

Paper canvas, ink #16120e, fluoro pink + yellow spot colours, thick ink borders, hard offset shadows, a bold condensed
display face (Oswald Bold, SIL OFL, assets/fonts/; the site uses Anton). Every text, pill and card is rendered once with
PIL at 2x, downsampled, and cached by its content, so drawing one per frame is a small alpha blit.

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

FONT_PATH = os.path.join(ROOT, 'assets', 'fonts', 'Oswald-Bold.ttf')
CANVAS = (242, 236, 223)      # --color-canvas #f2ecdf
SURFACE = (248, 244, 234)
INK = (22, 18, 14)            # --color-ink
INK2 = (75, 68, 57)
PINK = (255, 61, 151)         # --color-pink
YELLOW = (255, 216, 58)       # --color-yellow
GOOD = (34, 197, 94)          # form / status green
BAD = (239, 68, 68)           # form / status red
WHITE = (255, 253, 248)
SS = 2                        # supersampling for sprites


@lru_cache(maxsize=64)
def font(px):
    try:
        return ImageFont.truetype(FONT_PATH, int(px))
    except OSError:
        return ImageFont.load_default(int(px))


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


def text_size(s, px):
    l, t, r, b = font(px * SS).getbbox(s)
    return (r - l) / SS, (b - t) / SS


@lru_cache(maxsize=512)
def text(s, px, color, stroke=0, stroke_color=INK):
    f = font(px * SS); l, t, r, b = f.getbbox(s, stroke_width=stroke * SS)
    im = Image.new('RGBA', (r - l + 4, b - t + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - l, 2 - t), s, font=f, fill=tuple(color) + (255,), stroke_width=stroke * SS, stroke_fill=tuple(stroke_color) + (255,))
    return _down(im)


def _icon(d, kind, cx, cy, r, fill):
    """Icons drawn (fonts have no ticks): a disc with an ink border and a tick / bang / cross."""
    lw = max(2, int(r * 0.24))
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
def pill(lines, fill, icon=None, radius=None, pad=(22, 12), border=3, shadow=5, min_w=0, max_w=10000, align='left', gap=2):
    """A bordered card with a hard offset shadow. lines: tuple of (text, px, colour); icon: None/'check'/'bang'/'cross'
    (a disc the height of the text block, on the left). radius None = fully rounded (a pill)."""
    lines = tuple(lines)
    sizes = [(font(px * SS).getbbox(s), px) for s, px, _ in lines]
    th = sum((b - t) for (l, t, r, b), _ in sizes) + gap * SS * (len(lines) - 1)
    tw = max((r - l) for (l, t, r, b), _ in sizes) if lines else 0
    px_, py_ = pad[0] * SS, pad[1] * SS
    ic = int(min(th, 46 * SS) if icon else 0)
    iw = ic + (14 * SS if icon else 0)
    w = int(max(min_w * SS, tw + iw + 2 * px_)); w = int(min(w, max_w * SS)); h = int(th + 2 * py_)
    b, sh = border * SS, shadow * SS
    im = Image.new('RGBA', (w + sh + b, h + sh + b), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    rad = h // 2 if radius is None else radius * SS
    if sh: d.rounded_rectangle([sh, sh, w + sh - 1, h + sh - 1], rad, fill=INK + (255,))
    d.rounded_rectangle([0, 0, w - 1, h - 1], rad, fill=tuple(fill) + (255,), outline=INK + (255,), width=b)
    x = px_
    if icon:
        _icon(d, icon, x + ic / 2, h / 2, ic / 2, tuple(fill)); x += iw
    y = py_
    for ((l, t, r, bb), px), (s, _, col) in zip(sizes, lines):
        xx = x if align == 'left' else (w - (r - l)) / 2
        d.text((xx - l, y - t), s, font=font(px * SS), fill=tuple(col) + (255,))
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
def bubble(lines, px, max_w, tail='right'):
    """A speech bubble (the website's): paper card, ink border, hard shadow, a square tail on one side."""
    lines = tuple(lines)
    f = font(px * SS); lh = int(px * SS * 1.18)
    tw = max(f.getbbox(s)[2] - f.getbbox(s)[0] for s in lines)
    padx, pady, b, sh, tl = 20 * SS, 14 * SS, 3 * SS, 5 * SS, 16 * SS
    w = int(min(max_w * SS, tw + 2 * padx)); h = int(lh * len(lines) + 2 * pady - (lh - px * SS))
    W2 = w + sh + b + (tl if tail == 'right' else 0); H2 = h + sh + b
    im = Image.new('RGBA', (W2, H2), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    ty = int(h * 0.62)
    tail_pts = [(w - b * 2, ty - tl), (w + tl, ty), (w - b * 2, ty + tl * 0.4)]
    sh_pts = [(x + sh, y + sh) for x, y in tail_pts]
    if tail == 'right': d.polygon(sh_pts, fill=INK + (255,))
    d.rounded_rectangle([sh, sh, w + sh - 1, h + sh - 1], 10 * SS, fill=INK + (255,))
    d.rounded_rectangle([0, 0, w - 1, h - 1], 10 * SS, fill=SURFACE + (255,), outline=INK + (255,), width=b)
    if tail == 'right':
        d.polygon(tail_pts, fill=SURFACE + (255,))
        d.line([tail_pts[0], tail_pts[1], tail_pts[2]], fill=INK + (255,), width=b, joint='curve')
    y = pady
    for s in lines:
        l, t, r, bb = f.getbbox(s)
        d.text((padx - l, y - t + (lh - px * SS) * 0), s, font=f, fill=INK + (255,))
        y += lh
    return _down(im)
