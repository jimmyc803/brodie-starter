"""Side-view curl counter. A rep is extension -> flexion -> extension.

Uses MediaPipe world elbow angles (not aspect-distorted image coordinates).
Locks one visible arm until tracking is lost; never combines two arms' cycles.
"""
import math

import numpy as np

CURL_NAMES = {'bicep curls', 'bicep curl', 'bicep_curl', 'bicep_curls'}


class CurlCounter:
    def __init__(self, fps=10, extended=150, flexed=65, dwell_s=0.2, min_period_s=0.8):
        self.fps = fps
        self.extended, self.flexed = extended, flexed
        self.dwell = max(2, math.ceil(dwell_s * fps))
        self.min_period = math.ceil(min_period_s * fps)
        self.i = -1
        self.count = 0
        self.events, self.turning = [], []
        self.resettle()

    def resettle(self, keep=False):
        """Discard any partial cycle while retaining completed counts and clock."""
        if keep:
            return
        self.state = None
        self.arm = None
        self.run = 0
        self.started = None
        self.extreme = 180.0
        self.extreme_i = None

    @property
    def moving(self):
        return self.started is not None or self.state == 'active'

    def update(self, img, world, ok):
        self.i += 1
        if not ok or img is None or world is None:
            self.resettle()
            return None
        # Shoulder/elbow/wrist visibility AND presence; near arm wins at acquisition.
        arms = ((11, 13, 15), (12, 14, 16))
        quality = [float(np.min(img[list(a), 3:5])) for a in arms]
        if self.arm is None:
            self.arm = int(np.argmax(quality))
        joints = arms[self.arm]
        if quality[self.arm] < 0.6 or not np.isfinite(quality[self.arm]):
            self.resettle()
            return None
        shoulder, elbow, wrist = np.asarray(world)[list(joints), :3]
        u, v = shoulder - elbow, wrist - elbow
        denom = np.linalg.norm(u) * np.linalg.norm(v)
        if not np.isfinite(denom) or denom < 1e-6:
            self.resettle()
            return None
        angle = float(np.degrees(np.arccos(np.clip(np.dot(u, v) / denom, -1, 1))))
        if self.state is None:
            self.run = self.run + 1 if angle >= self.extended else 0
            if self.run >= self.dwell:
                self.state, self.run = 'ready', 0
            return None
        if self.state == 'ready':
            if angle < self.extended and self.started is None:
                self.started = self.i
            self.run = self.run + 1 if angle <= self.flexed else 0
            if self.run >= self.dwell:
                self.state, self.run = 'active', 0
                self.extreme, self.extreme_i = angle, self.i
            elif angle >= self.extended:
                self.started = None
            return None
        if angle < self.extreme:
            self.extreme, self.extreme_i = angle, self.i
        self.run = self.run + 1 if angle >= self.extended else 0
        if self.run < self.dwell:
            return None
        valid = self.started is not None and self.i - self.started >= self.min_period
        self.state, self.run, self.started = 'ready', 0, None
        if valid:
            self.count += 1
            self.events.append(self.i)
            self.turning.append(self.extreme_i)
            return self.count
        return None
