"""Annotate a recorded pull-up video: the live pipeline's pose + PullupCounter + mirror overlay, written to an mp4.

Pose runs on every frame (smooth skeleton); the counter steps at the live rate (10 fps) like on a call, so the count,
CLEARED flashes and "Chin over the bar" faults match what Brodie would say live. Prints every rep and pull, and writes a JSON
summary next to the output (reps with times, each pull's min elbow angle / height / fault).

Run:  PYTHONPATH=src .venv/bin/python -m facetime.annotate_video --video my_pullups.mov [--out data/tmp/my_pullups.annotated.mp4] [--target 10]
"""
import argparse, json, os, subprocess, tempfile
import cv2
from facetime.pipeline import FPS, to_short_side
from facetime.pullup import PullupCounter, compose_pullup
from facetime.mirror import W, H
from rtcoach.pose import Pose


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True); ap.add_argument('--out', default=None)
    ap.add_argument('--target', type=int, default=0); ap.add_argument('--pose', default='full')
    a = ap.parse_args()
    out = a.out or os.path.splitext(a.video)[0] + '.annotated.mp4'
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened(): raise SystemExit(f"can't open {a.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
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
        img = compose_pullup(rgb, lm, pc.st, now=t)
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
