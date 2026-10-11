"""A short heat-map intro spliced in front of a Brodie call render (facetime/call_render.py): the session's muscle map fills
in cell by cell, a cursor taps the lats on the back view, the map zooms into the hot spot and the tap opens into the call.

Muscle shapes and rank colors are the web app's (web/lib/body/shapes.json, lib/ranks.ts); the scores are a demo pull-up day.

Run:  PYTHONPATH=src .venv/bin/python -m facetime.heatmap_intro --call data/tmp/IMG_0244.call.mp4 [--out ...demo.mp4]
"""
import argparse, json, math, os, subprocess, tempfile, wave
import cv2
import numpy as np
from PIL import Image, ImageDraw
from facetime.call_render import OW, OH, VOLT, WHITE, GREY, font, text, ease, back, glass, hairline

FPS = 30
DUR = 4.6
SHAPES = os.path.join(os.path.dirname(__file__), '..', 'web', 'lib', 'body', 'shapes.json')
BG = (9, 9, 11); BODY_BASE = (63, 63, 70); UNTRAINED = (82, 82, 91); STROKE = (24, 24, 27)
# demo session: a pull-up day (back + arms hot), some legs/chest from the warm-up
SCORES = dict(lats=0.93, rear_delts=0.8, traps=0.72, biceps=0.84, forearms=0.66, triceps=0.4, abs=0.52, obliques=0.45,
              front_delts=0.38, chest=0.3, quads=0.55, glutes=0.5, hamstrings=0.42, calves=0.34)
ORDER = ['lats', 'biceps', 'rear_delts', 'traps', 'forearms', 'abs', 'obliques', 'quads', 'glutes', 'hamstrings',
         'triceps', 'front_delts', 'chest', 'calves']
RED, YEL, GRN = np.array((239, 68, 68)), np.array((234, 179, 8)), np.array((34, 197, 94))
RANKS = [(0, RED * 0.78), (0.2, RED), (0.35, (RED + YEL) / 2), (0.5, YEL), (0.62, YEL * 0.55 + GRN * 0.45), (0.75, GRN),
         (0.88, GRN * 0.7 + 255 * 0.3), (0.97, GRN * 0.4 + 255 * 0.6)]
RANK_NAMES = ['Novice', 'Beginner', 'Intermediate', 'Advanced', 'Expert', 'Elite', 'Master', 'Legendary']

def rank(score):
    i = max(k for k, (m, _) in enumerate(RANKS) if score >= m); return tuple(int(c) for c in RANKS[i][1]), RANK_NAMES[i]

# layout: front and back side by side, 100 x 220 view boxes
SC = 4.1; BW = 100 * SC; TOPY = 520
ORIG = {'front': ((OW - 2 * BW - 50) / 2, TOPY), 'back': ((OW - 2 * BW - 50) / 2 + BW + 50, TOPY)}
T_FILL, T_CURSOR, T_CLICK, T_ZOOM, T_OPEN = 0.45, 2.15, 2.95, 3.1, 3.85


def load():
    d = json.load(open(SHAPES))
    return {side: [(s['muscle'], np.array([[float(v) for v in q.split(',')] for q in s['points'].split()], np.float32)) for s in d[side]]
            for side in d}


class Intro:
    def __init__(self, first_call_frame):
        self.shapes = load(); self.call = first_call_frame
        lats = np.concatenate([p for m, p in self.shapes['back'] if m == 'lats'])
        bx, by = ORIG['back']; self.hot = np.array((bx + lats[:, 0].mean() * SC, by + lats[:, 1].mean() * SC))
        self.click = self.hot + (34, 10)
        yy, xx = np.mgrid[0:OH, 0:OW].astype(np.float32)
        r = np.sqrt(((xx - OW / 2) / OW) ** 2 + ((yy - OH * 0.45) / OH) ** 2)
        self.bg = (np.array(BG, np.float32) + np.clip(0.5 - r, 0, 1)[..., None] * np.array((60, 70, 30), np.float32) * 0.5)

    def fill_amount(self, m, t):
        if m not in SCORES: return 0.0
        return ease((t - T_FILL - ORDER.index(m) * 0.1) / 0.45)

    def frame(self, t):
        z = ease((t - T_ZOOM) / (T_OPEN + 0.5 - T_ZOOM)); zoom = 1 + 2.2 * z
        def X(p): return (p - self.hot) * zoom + self.hot + (np.array((OW / 2, OH * 0.47)) - self.hot) * z
        base = self.bg.copy(); glow = np.zeros((OH, OW, 3), np.float32)
        img = base.astype(np.uint8)
        sel = t >= T_CLICK
        for side, shapes in self.shapes.items():
            ox, oy = ORIG[side]
            for m, pts in shapes:
                P = X(pts * SC + (ox, oy))
                Pi = (P * 16).astype(np.int32)
                col = BODY_BASE if m is None else UNTRAINED
                cv2.fillPoly(img, [Pi], col, cv2.LINE_AA, shift=4)
                a = self.fill_amount(m, t) if m else 0
                if a > 0:
                    c, _ = rank(SCORES[m])
                    # a fill sweeps up the muscle: blend toward rank color with a bright flash on arrival
                    flash = max(0.0, 1 - abs(a - 0.6) / 0.4) * 0.35
                    cc = tuple(int(u * (1 - a) + v * a + 255 * flash) for u, v in zip(UNTRAINED, c))
                    cv2.fillPoly(img, [Pi], tuple(min(255, k) for k in cc), cv2.LINE_AA, shift=4)
                    cv2.fillPoly(glow, [Pi], tuple(float(k) * a * (0.35 + 0.65 * SCORES[m]) for k in c), cv2.LINE_AA, shift=4)
                hl = m == 'lats' and side == 'back' and (sel or (T_CURSOR + 0.55 < t))
                cv2.polylines(img, [Pi], True, WHITE if hl else STROKE, (3 if sel else 2) if hl else 1, cv2.LINE_AA, shift=4)
        g = cv2.GaussianBlur(glow, (0, 0), 16 * zoom ** 0.5)
        if sel:                                                                    # hot-spot pulse after the tap
            pulse = 0.5 + 0.5 * math.sin((t - T_CLICK) * 9)
            g *= 1 + 0.4 * pulse
        img = np.clip(img.astype(np.float32) + g * 0.9, 0, 255).astype(np.uint8)
        return self.chrome(img, t, X, zoom, z)

    def chrome(self, img, t, X, zoom, z):
        hot = X(self.hot)
        ta = 1 - ease((t - T_ZOOM) / 0.4)                                          # header/legend fade as we zoom
        if ta > 0.3: glass(img, 56, OH - 360, OW - 112, 150, 40, alpha=0.5)
        tip = t >= T_CLICK + 0.05
        if tip: glass(img, int(hot[0] - 230), int(hot[1] - 400), 460, 210, 34, alpha=0.6)
        im = Image.fromarray(img).convert('RGBA'); ov = Image.new('RGBA', im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
        if ta > 0.01:
            a = int(255 * ta * ease(t / 0.4))
            text(d, (72, 250), 'BRODIE · SESSION RECAP', 22, VOLT, 'Bold', mono=True, a=a, spacing=4)
            text(d, (68, 330), 'Ryan’s muscle map', 76, WHITE, 'Bold', anchor='ls', a=a)
            text(d, (72, 392), 'Pull-up day · 6 clean reps · 2 half reps', 30, GREY, 'Medium', anchor='ls', a=a)
            for side, lab in (('front', 'FRONT'), ('back', 'BACK')):
                text(d, (ORIG[side][0] + BW / 2, TOPY + 220 * SC + 40), lab, 20, GREY, 'Semibold', mono=True, anchor='mm', a=a, spacing=4)
            # caption for muted autoplay
            msg = 'Every muscle, scored from your reps' if t < T_CURSOR + 0.3 else 'Tap a muscle to see the reps behind it'
            text(d, (OW / 2, OH - 285), msg, 40, WHITE, 'Bold', anchor='mm', a=a)
            hairline(d, 56, OH - 360, OW - 112, 150, 40)
            n = sum(1 for m in ORDER if self.fill_amount(m, t) > 0.6)
            text(d, (OW - 72, 250), f'{n:02d}/{len(ORDER)} SCORED', 22, GREY, 'Semibold', mono=True, anchor='ra', a=a, spacing=2)
        if tip:
            a = int(255 * ease((t - T_CLICK - 0.05) / 0.18)); x0, y0 = hot[0] - 230, hot[1] - 400
            c, rn = rank(SCORES['lats'])
            text(d, (x0 + 30, y0 + 44), 'LATS · MAIN MUSCLE', 18, VOLT, 'Bold', mono=True, anchor='lm', a=a, spacing=3)
            text(d, (x0 + 30, y0 + 112), f'{int(SCORES["lats"] * 100)}', 72, WHITE, 'Bold', anchor='lm', a=a)
            text(d, (x0 + 150, y0 + 100), rn, 34, c, 'Bold', anchor='lm', a=a)
            text(d, (x0 + 150, y0 + 134), 'Pull-ups · 3 sets', 22, GREY, 'Medium', anchor='lm', a=a)
            d.rounded_rectangle((x0 + 30, y0 + 158, x0 + 430, y0 + 194), 18, fill=(*VOLT, a))
            text(d, (x0 + 230, y0 + 176), '▶  WATCH REP REVIEW', 18, (10, 10, 10), 'Bold', mono=True, anchor='mm', a=a, spacing=2)
            hairline(d, int(x0), int(y0), 460, 210, 34)
        self.cursor(d, t, X)
        im = Image.alpha_composite(im, ov); out = np.asarray(im.convert('RGB'))
        if t >= T_OPEN: out = self.open(out, t, hot)
        return out

    def cursor(self, d, t, X):
        if t < T_CURSOR: return
        start = np.array((OW * 0.9, OH * 0.92)); end = self.click
        p = start + (end - start) * ease((t - T_CURSOR) / 0.7)
        if t > T_ZOOM: p = X(end)
        press = 0.85 if T_CLICK <= t < T_CLICK + 0.12 else 1.0
        if t >= T_CLICK:                                                           # click ripple
            r = 20 + 90 * ease((t - T_CLICK) / 0.5); a = int(220 * (1 - ease((t - T_CLICK) / 0.5)))
            d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), outline=(255, 255, 255, a), width=4)
        s = 2.4 * press; x, y = p
        arrow = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
        pts = [(x + ax * s, y + ay * s) for ax, ay in arrow]
        d.polygon([(px + 3, py + 4) for px, py in pts], fill=(0, 0, 0, 110))
        d.polygon(pts, fill=(255, 255, 255, 255), outline=(0, 0, 0, 255))
        d.line(pts + [pts[0]], fill=(0, 0, 0, 255), width=2)

    def open(self, out, t, hot):
        """The call opens out of the tapped muscle: a rounded window grows from the hot spot to full screen."""
        k = ease((t - T_OPEN) / (DUR - T_OPEN))
        w, h = int(160 + (OW - 160) * k), int(160 + (OH - 160) * k)
        cx = hot[0] + (OW / 2 - hot[0]) * k; cy = hot[1] + (OH / 2 - hot[1]) * k
        x0, y0 = int(cx - w / 2), int(cy - h / 2)
        win = cv2.resize(self.call, (w, h), interpolation=cv2.INTER_AREA)
        r = int(80 * (1 - k)) + 1
        m = Image.new('L', (w, h), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
        m = np.asarray(m, np.float32)[..., None] / 255
        res = out.astype(np.float32) * (1 - 0.6 * k)
        xa, ya, xb, yb = max(0, x0), max(0, y0), min(OW, x0 + w), min(OH, y0 + h)
        sub = res[ya:yb, xa:xb]; mm = m[ya - y0:yb - y0, xa - x0:xb - x0]; ww = win[ya - y0:yb - y0, xa - x0:xb - x0]
        res[ya:yb, xa:xb] = sub * (1 - mm) + ww * mm
        return res.clip(0, 255).astype(np.uint8)


def sfx(sr, path):
    """Soft ticks as cells fill, a click on the tap, a whoosh as the call opens."""
    n = int(DUR * sr); buf = np.zeros(n, np.float32); tt = np.arange(int(0.05 * sr)) / sr
    def put(t, x, g):
        i = int(t * sr); j = min(n, i + len(x)); buf[i:j] += g * x[:j - i]
    for k, m in enumerate(ORDER):
        put(T_FILL + k * 0.1 + 0.2, np.sin(2 * np.pi * (900 + 40 * k) * tt) * np.exp(-tt * 90), 0.12)
    ct = np.arange(int(0.03 * sr)) / sr
    put(T_CLICK, np.random.default_rng(1).normal(0, 1, len(ct)) * np.exp(-ct * 250), 0.5)
    wt = np.arange(int(0.8 * sr)) / sr; noise = np.random.default_rng(2).normal(0, 1, len(wt))
    noise = np.convolve(noise, np.ones(30) / 30, 'same'); env = np.sin(np.pi * wt / wt[-1]) ** 2
    put(T_OPEN - 0.1, noise * env, 0.9)
    w = wave.open(path, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
    w.writeframes((np.clip(buf, -1, 1) * 32767).astype(np.int16).tobytes()); w.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--call', required=True); ap.add_argument('--out', default=None)
    a = ap.parse_args(); out = a.out or os.path.splitext(a.call)[0] + '.demo.mp4'
    cap = cv2.VideoCapture(a.call); ok, first = cap.read(); fps = cap.get(cv2.CAP_PROP_FPS); cap.release()
    intro = Intro(cv2.cvtColor(first, cv2.COLOR_BGR2RGB))
    tmp = tempfile.mkdtemp(); iv, wav = os.path.join(tmp, 'intro.mp4'), os.path.join(tmp, 'intro.wav')
    sfx(24000, wav)
    ff = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{OW}x{OH}', '-r', f'{fps}', '-i', '-',
                           '-i', wav, '-c:v', 'libx264', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '1',
                           '-shortest', iv], stdin=subprocess.PIPE)
    for k in range(int(DUR * fps)): ff.stdin.write(intro.frame(k / fps).tobytes())
    ff.stdin.close(); ff.wait()
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', iv, '-i', a.call, '-filter_complex',
                    '[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[v][a]', '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '18',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-ar', '48000', '-ac', '1', '-b:a', '160k', '-movflags', '+faststart', out], check=True)
    print(f'-> {out}')


if __name__ == '__main__':
    main()
