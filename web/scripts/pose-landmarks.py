"""Precompute smoothed MediaPipe pose landmarks for a clip.

Usage:
  uv run --with mediapipe --with opencv-python-headless --with numpy \
    python scripts/pose-landmarks.py input.mp4 output.pose.json [--model pose_landmarker_full.task]

Output matches lib/rep-review/pose-types.ts (PoseTrack v1):
  {"v":1,"fps":F,"w":W,"h":H,"duration":D,"frames":[[t,x0,y0,v0,...,x32,y32,v32],...]}
Coordinates are normalized image coords, One Euro filtered (minCutoff 1.2, beta 0.02, dCutoff 1).
Landmarks with visibility < 0.3 hold the previous filtered value.
"""
import argparse
import json
import math
import os
import sys

import cv2
import mediapipe as mp

N = 33
DEFAULT_MODEL = os.environ.get("POSE_MODEL", "pose_landmarker_full.task")


class LowPass:
    def __init__(self):
        self.y = None

    def __call__(self, x, a):
        self.y = x if self.y is None else a * x + (1 - a) * self.y
        return self.y


class OneEuro:
    def __init__(self, min_cutoff=1.2, beta=0.02, d_cutoff=1.0):
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.x, self.dx = LowPass(), LowPass()
        self.t_prev = None
        self.value = None

    @staticmethod
    def alpha(cutoff, dt):
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        if self.t_prev is None:
            self.t_prev = t
            self.x(x, 1.0)
            self.dx(0.0, 1.0)
            self.value = x
            return x
        dt = max(t - self.t_prev, 1e-6)
        dx = (x - self.x.y) / dt
        edx = self.dx(dx, self.alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        self.value = self.x(x, self.alpha(cutoff, dt))
        self.t_prev = t
        return self.value


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("output")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--min-vis", type=float, default=0.3)
    ap.add_argument("--min-det", type=float, default=0.5, help="pose detection / presence / tracking confidence")
    ap.add_argument("--crop", default=None, help="x,y,w,h px region to run detection on (output stays in full-frame coords)")
    ap.add_argument("--scale", type=float, default=1.0, help="upscale factor applied to the (cropped) frame before detection")
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        sys.exit(f"cannot open {args.input}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    crop = [int(v) for v in args.crop.split(",")] if args.crop else [0, 0, w, h]
    BaseOptions = mp.tasks.BaseOptions
    vision = mp.tasks.vision
    opts = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=args.model),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=args.min_det,
        min_pose_presence_confidence=args.min_det,
        min_tracking_confidence=args.min_det,
    )
    filters = [[OneEuro(), OneEuro()] for _ in range(N)]
    frames = []
    i = 0
    with vision.PoseLandmarker.create_from_options(opts) as lm:
        while True:
            ok, bgr = cap.read()
            if not ok:
                break
            t = i / fps
            cx, cy, cw, ch = crop
            roi = bgr[cy:cy + ch, cx:cx + cw]
            if args.scale != 1.0:
                roi = cv2.resize(roi, None, fx=args.scale, fy=args.scale, interpolation=cv2.INTER_LANCZOS4)
            rgb = cv2.cvtColor(roi, cv2.COLOR_BGR2RGB)
            res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), int(round(t * 1000)))
            row = [round(t, 4)]
            pts = res.pose_landmarks[0] if res.pose_landmarks else None
            for j in range(N):
                fx, fy = filters[j]
                if pts is not None:
                    p = pts[j]
                    vis = float(p.visibility if p.visibility is not None else 1.0)
                else:
                    p, vis = None, 0.0
                if p is not None and (vis >= args.min_vis or fx.value is None):
                    px, py = (cx + float(p.x) * cw) / w, (cy + float(p.y) * ch) / h
                    x, y = fx(px, t), fy(py, t)
                else:  # hold previous filtered value
                    x = fx.value if fx.value is not None else 0.0
                    y = fy.value if fy.value is not None else 0.0
                row += [round(x, 4), round(y, 4), round(vis, 4)]
            frames.append(row)
            i += 1
    cap.release()
    track = {"v": 1, "fps": round(fps, 4), "w": w, "h": h, "duration": round(i / fps, 4), "frames": frames}
    with open(args.output, "w") as f:
        json.dump(track, f, separators=(",", ":"))
    print(f"{args.output}: {i} frames, {w}x{h} @ {fps}fps")


if __name__ == "__main__":
    main()
