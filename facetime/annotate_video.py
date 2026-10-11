"""Annotate a recorded pull-up video: the live pipeline's pose + PullupCounter + mirror overlay, written to an mp4.

Pose runs on every frame (smooth skeleton); the counter steps at the live rate (10 fps) like on a call, so the count,
CLEARED flashes and "Chin over the bar" faults match what Brodie would say live. Prints every rep and pull, and writes a JSON
summary next to the output (reps with times, each pull's min elbow angle / height / fault).

Run:  PYTHONPATH=src .venv/bin/python -m facetime.annotate_video --video my_pullups.mov [--out data/tmp/my_pullups.annotated.mp4] [--target 10]
"""
import argparse, json, os, subprocess, tempfile
import cv2
import numpy as np
from facetime.pipeline import FPS, to_short_side
from facetime.pullup import PullupCounter, compose_pullup
from facetime.mirror import W, H, SAFE_TOP, SAFE_BOTTOM
from rtcoach.pose import Pose


TOP, BOTTOM = SAFE_TOP + 106, SAFE_BOTTOM - 40     # the picture area between the top and bottom bars


def framing(path, variant, every_s=0.5):
    """One fixed crop for the whole video (no jitter): the box around the upper body (head, arms, hands on the bar, hips)
    over every sampled frame, padded, widened to the picture area's aspect. Normalised (x0, y0, x1, y1); whole frame if no pose."""
    cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; k = max(1, round(fps * every_s))
    pose = Pose(variant, video=True); pts, i = [], 0
    while True:
        ok = cap.grab()
        if not ok: break
        if i % k == 0:
            ok, bgr = cap.retrieve(); h, w = bgr.shape[:2]
            lm, _ = pose(to_short_side(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)), int(i / fps * 1000))
            if lm is not None: pts += [(x, y) for x, y, _, v, *_ in lm[:25] if v > 0.5]
        i += 1
    cap.release(); pose.close()
    if len(pts) < 10: return (0.0, 0.0, 1.0, 1.0)
    p = np.array(pts); x0, y0 = np.percentile(p, 1, axis=0); x1, y1 = np.percentile(p, 99, axis=0)
    bw, bh = x1 - x0, y1 - y0
    x0, x1 = x0 - 0.25 * bw, x1 + 0.25 * bw; y0, y1 = y0 - 0.32 * bh, y1 + 0.06 * bh             # headroom: the CLEARED badge sits above the bar
    aspect = W / (BOTTOM - TOP)                                          # target w/h in pixels
    pw, ph = (x1 - x0) * w, (y1 - y0) * h
    if pw / ph < aspect: grow = (ph * aspect - pw) / w / 2; x0, x1 = x0 - grow, x1 + grow
    else: grow = (pw / aspect - ph) / h / 2; y0, y1 = y0 - grow, y1 + grow
    dx = max(0, -x0) - max(0, x1 - 1); dy = max(0, -y0) - max(0, y1 - 1)   # slide back inside the frame
    x0, x1, y0, y1 = x0 + dx, x1 + dx, y0 + dy, y1 + dy
    return (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))


def fit_frame(rgb, box):
    """The `box` region of the frame fitted between the top and bottom bars (blurred fill around it). Returns the WxH frame
    and a map from frame-normalised (x, y) to output-normalised."""
    h, w = rgb.shape[:2]
    bx0, by0, bx1, by1 = box
    X0, Y0, X1, Y1 = int(bx0 * w), int(by0 * h), int(bx1 * w), int(by1 * h)
    crop = rgb[Y0:Y1, X0:X1]; ch, cw = crop.shape[:2]
    s = min((BOTTOM - TOP) / ch, W / cw); fw, fh = int(cw * s), int(ch * s)
    x0, y0 = (W - fw) // 2, TOP + (BOTTOM - TOP - fh) // 2
    bg = cv2.GaussianBlur(cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA), (0, 0), 25)
    img = (bg * 0.45).astype(np.uint8)
    img[y0:y0 + fh, x0:x0 + fw] = cv2.resize(crop, (fw, fh), interpolation=cv2.INTER_AREA)
    return img, lambda x, y: ((x0 + (x * w - X0) * s) / W, (y0 + (y * h - Y0) * s) / H)


def draw_fit(rgb, lm, st, now, box):
    """compose_pullup on the fitted frame: landmarks, bar and chin are moved into it just for drawing."""
    img, to = fit_frame(rgb, box)
    flm = None
    if lm is not None:
        flm = np.array(lm, np.float32, copy=True)
        flm[:, 0], flm[:, 1] = to(flm[:, 0], flm[:, 1])
        if flm.shape[1] > 3: flm[(flm[:, 1] * H < TOP) | (flm[:, 1] * H > BOTTOM), 3] = 0.0   # joints outside the picture: not drawn
    bar_y, chin = st.bar_y, st.chin
    if bar_y is not None: st.bar_y = to(0.5, bar_y)[1]
    if chin is not None: st.chin = to(*chin)
    try:
        return compose_pullup(img, flm, st, now=now)
    finally:
        st.bar_y, st.chin = bar_y, chin


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True); ap.add_argument('--out', default=None)
    ap.add_argument('--target', type=int, default=0); ap.add_argument('--pose', default='full')
    ap.add_argument('--crop', action='store_true', help='crop/stretch to fill the frame like the live mirror (default: fit the whole frame between the bars)')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.video)[0] + '.annotated.mp4'
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened(): raise SystemExit(f"can't open {a.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    box = None if a.crop else framing(a.video, a.pose)
    if box: print(f'framing (normalised x0, y0, x1, y1): {tuple(round(v, 3) for v in box)}')
    step = max(1, round(fps / FPS))                       # counter frames: every `step`-th frame (~10 fps)
    pose = Pose(a.pose, video=True); pc = PullupCounter(target=a.target)
    tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    wr = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'), fps, (W, H))
    reps, faults, i, last_ms = [], [], 0, -1
    while True:
        ok, bgr = cap.read()
        if not ok: break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); t = i / fps
        ms = max(last_ms + 1, int(t * 1000)); last_ms = ms
        lm, _ = pose(to_short_side(rgb), ms)
        if i % step == 0:
            st = pc.update(lm, t)
            for kind, val in st.events:
                if kind == 'rep': reps.append(round(t, 2)); print(f'  t={t:6.2f}s  REP {val}')
                elif kind == 'fault': faults.append((round(t, 2), val)); print(f'  t={t:6.2f}s  fault: {val}')
        img = compose_pullup(rgb, lm, pc.st, now=t) if a.crop else draw_fit(rgb, lm, pc.st, t, box)
        wr.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR)); i += 1
    cap.release(); wr.release(); pose.close()
    if i == 0: raise SystemExit('no frames read')
    # mp4v -> H.264 so it plays in QuickTime / browsers / editors
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p',
                        '-movflags', '+faststart', out])
    if r.returncode: os.replace(tmp, out)
    else: os.remove(tmp)
    summary = dict(video=a.video, frames=i, fps=fps, reps=len(reps), rep_times=reps,
                   faults=[dict(t=t, label=l) for t, l in faults], pulls=pc.pulls)
    with open(os.path.splitext(out)[0] + '.json', 'w') as f: json.dump(summary, f, indent=1, default=float)
    print(f'{len(reps)} reps, {len(faults)} faults, {i / fps:.1f} s -> {out}')


if __name__ == '__main__':
    main()
