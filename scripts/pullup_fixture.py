"""Rebuild tests/fixtures/pullup_landmarks.npz (git-ignored, like all .npz): download six free Mixkit pull-up clips (Mixkit
free license) into data/tmp/pullup_clips/ and save their MediaPipe landmarks at the pipeline's 10 fps, a fresh tracker per clip.

  .venv/bin/python scripts/pullup_fixture.py && .venv/bin/python -m pytest -q tests/test_pullup.py
"""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, 'src')]
import numpy as np, cv2
from facetime.pipeline import FramePipeline, COUNTERS, FPS

CLIPS = ['25248', '44410', '735', '40140', '40151', '40157']
DIR = os.path.join(ROOT, 'data', 'tmp', 'pullup_clips')
OUT = os.path.join(ROOT, 'tests', 'fixtures', 'pullup_landmarks.npz')


def main():
    os.makedirs(DIR, exist_ok=True); os.makedirs(os.path.dirname(OUT), exist_ok=True); out = {}
    for c in CLIPS:
        path = os.path.join(DIR, f'mk{c}.mp4')
        if not os.path.exists(path):
            subprocess.run(['curl', '-sfL', '-o', path, f'https://assets.mixkit.co/videos/{c}/{c}-720.mp4'], check=True)
        pipe = FramePipeline(os.path.join(ROOT, 'data', 'models', 'clf_pose.pt'), None, 'full', {}, None, rep_params=COUNTERS['v2'], trigger='none')
        cap = cv2.VideoCapture(path); fps = cap.get(cv2.CAP_PROP_FPS); i = 0; nt = 0.0; L = []
        while True:
            ok, bgr = cap.read()
            if not ok: break
            t = i / fps; i += 1
            if t + 1e-6 < nt: continue
            nt += 1 / FPS; pipe.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), t_ms=t * 1000); lm = pipe.last_landmarks
            L.append(np.full((33, 4), np.nan, np.float32) if lm is None else np.asarray(lm, np.float32)[:, :4])
        out[f'mk{c}'] = np.stack(L).astype(np.float16); pipe.close(); print(f'mk{c}: {len(L)} frames')
    np.savez_compressed(OUT, **out); print('wrote', OUT)


if __name__ == '__main__':
    main()
