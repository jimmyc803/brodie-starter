"""Deterministic synthetic side-view push-up pose generator (tests + judge_eval harness).

Model: a 2D sagittal body (metres; X toward the head, Z up from the floor) with rigid segments. In a plank the body is
a straight line pivoting on the ankle (toes on the floor; on the knee when knees_down) and the shoulder is placed where
that line meets the arm reach for the current elbow angle; hands stay fixed on the floor where the forearm is
vertical at the bottom of the rep. The elbow points toward the feet. hip_offset (m) pushes the hip perpendicular to
the shoulder-pivot line: + toward the floor (sag; limited so the hip joint stays >= HIP_MIN_Z above the floor, as a
pelvis cannot pass through it), - away (pike). Each rep: raised-cosine descent lockout -> depth, an optional pause of
bottom_hold_s at depth, raised-cosine ascent back to lockout; a lead-in hold at lockout precedes the first rep.

Projection: a phone on the floor to the side (landscape). P_height_units = (cx + dir * X * scale, floor_y - Z * scale);
normalised x = P_x / aspect. side='left' shows the left body side (head toward image left); far-side landmarks sit
just behind the near side with low visibility. noise = Gaussian sigma as a fraction of frame HEIGHT applied
isotropically in pixels (x sigma = noise / aspect in normalised units).

Challenge motions (liveness tests): hand_motions = [(kind, hand, t0, dur)], kind 'tap' (the wrist travels from its
floor position to just above-behind the shoulder, i.e. the hand on the shoulder) or 'lift' (the wrist rises 0.30 m and
reaches 0.30 m toward the head), hand 'left'|'right' (anatomical). Profile: raised-cosine ramp up over min(0.4, dur/3) s,
hold, ramp down; the elbow follows by two-circle IK (the lower solution). A moving far-side hand becomes visible as it
rises (visibility far_vis -> 0.95 with the motion amount), as a hand lifted above the body does. challenge_motion()
maps a liveness cue key to the motion that answers it.

pauses = [(t0, dur)]: the rep phase stops at real time t0 for dur seconds (the body holds whatever pose it is in, as
when a person freezes mid-rep); the clip grows by the paused time and fire times shift accordingly.
camera_shifts = [(t0, dur, dx, dy)]: the whole image moves by (dx, dy) (fractions of the frame HEIGHT, y down) with a
raised-cosine ramp in and out (as when the phone, or a filmed laptop screen, is moved), applied after projection.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from challenge.judge.metrics import FrameObs, RepMetrics, RepMetricsAccumulator

BODIES: dict[str, dict[str, float]] = {
    # segment lengths in metres; scale = image height units per metre (camera distance)
    "short": dict(upper_arm=0.26, forearm=0.24, torso=0.44, thigh=0.38, shin=0.36, scale=0.85),
    "average": dict(upper_arm=0.30, forearm=0.27, torso=0.50, thigh=0.43, shin=0.42, scale=0.75),
    "tall": dict(upper_arm=0.34, forearm=0.31, torso=0.56, thigh=0.50, shin=0.48, scale=0.66),
}
WRIST_Z = 0.04        # wrist joint height above the floor
ANKLE_Z = 0.10        # ankle joint height on the toes
KNEE_FLOOR_Z = 0.05   # knee joint height when kneeling
HIP_MIN_Z = 0.11      # hip joint height when the pelvis rests on the floor (sag is limited by it)
FLOOR_Y = 0.88        # floor line in normalised image y
TAP_OFFSET = np.array([-0.04, 0.07])    # wrist relative to the shoulder when the hand rests on it (m)
LIFT_OFFSET = np.array([0.30, 0.30])    # wrist relative to its floor position at the top of a lift (m)
CUE_MOTIONS = {"challenge_tap_left": ("tap", "right"), "challenge_tap_right": ("tap", "left"),
               "challenge_lift_right": ("lift", "right")}


def challenge_motion(cue_key: str, t0: float, dur: float = 1.5) -> tuple[str, str, float, float]:
    """The hand motion that answers a liveness cue (tap your LEFT shoulder = with the RIGHT hand)."""
    kind, hand = CUE_MOTIONS[cue_key]
    return (kind, hand, float(t0), float(dur))


def _motion_amount(t: float, t0: float, dur: float) -> float:
    if dur <= 0 or not t0 <= t <= t0 + dur:
        return 0.0
    ramp = min(0.4, dur / 3)
    v = t - t0
    if v < ramp:
        return (1 - math.cos(math.pi * v / ramp)) / 2
    if v > dur - ramp:
        return (1 - math.cos(math.pi * (dur - v) / ramp)) / 2
    return 1.0


def _moved_hand(B: dict, p: dict, kind: str, k: float) -> tuple[np.ndarray, np.ndarray]:
    """(wrist, elbow) of a hand `k` of the way through a challenge motion (k=0: on the floor as in pose p)."""
    target = p["S"] + TAP_OFFSET if kind == "tap" else p["W"] + LIFT_OFFSET
    w = p["W"] + k * (target - p["W"])
    e1, e2 = _circle_x(p["S"], B["upper_arm"], w, B["forearm"])
    return w, (e1 if e1[1] <= e2[1] else e2)


@dataclass
class SynthClip:
    frames: list[FrameObs]
    fire_times: list[float]
    meta: dict = field(default_factory=dict)


def _circle_x(c0: np.ndarray, r0: float, c1: np.ndarray, r1: float) -> tuple[np.ndarray, np.ndarray]:
    """Both intersections of two circles (clamped to the closest valid configuration when they do not meet)."""
    d = float(np.linalg.norm(c1 - c0))
    d = min(max(d, abs(r0 - r1) + 1e-9), r0 + r1 - 1e-12) if d > 1e-12 else 1e-9
    u = (c1 - c0) / max(float(np.linalg.norm(c1 - c0)), 1e-12)
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h = math.sqrt(max(r0 * r0 - a * a, 0.0))
    m = c0 + a * u
    perp = np.array([-u[1], u[0]])
    return m + h * perp, m - h * perp


def _pose(B: dict, theta: float, knees_down: bool, hip_offset: float, wrist: np.ndarray) -> dict[str, np.ndarray]:
    ua, fa, to, th, sh = B["upper_arm"], B["forearm"], B["torso"], B["thigh"], B["shin"]
    if knees_down:
        pivot = np.array([0.0, KNEE_FLOOR_Z])
        L = th + to
    else:
        pivot = np.array([0.0, ANKLE_Z])
        L = sh + th + to
    reach = math.sqrt(max(ua * ua + fa * fa - 2 * ua * fa * math.cos(math.radians(theta)), 1e-9))
    s1, s2 = _circle_x(pivot, L, wrist, reach)
    S = s1 if s1[1] >= s2[1] else s2
    e1, e2 = _circle_x(S, ua, wrist, fa)
    E = e1 if e1[0] <= e2[0] else e2                       # elbow toward the feet
    u = (pivot - S) / np.linalg.norm(pivot - S)
    down = np.array([-u[1], u[0]])
    if down[1] > 0:
        down = -down
    base = S + to * u
    off = hip_offset
    if off > 0 and down[1] < 0:              # the pelvis cannot pass through the floor
        off = min(off, max(0.0, (base[1] - HIP_MIN_Z) / -down[1]))
    H = base + off * down
    if knees_down:
        K = pivot
        A = K + sh * np.array([-math.cos(math.radians(5)), math.sin(math.radians(5))])
    else:
        A = pivot
        v = (H - A) / np.linalg.norm(H - A)
        K = A + sh * v
    return dict(S=S, E=E, W=wrist, H=H, K=K, A=A)


def _wrist_for(B: dict, knees_down: bool, depth: float) -> np.ndarray:
    """Hands placed so the forearm is vertical at the bottom of the rep (elbow angle `depth`): the upper arm then
    makes (90 - depth) degrees with the horizontal, shoulder below the elbow when depth < 90."""
    pivot_z = KNEE_FLOOR_Z if knees_down else ANKLE_Z
    L = B["thigh"] + B["torso"] + (0.0 if knees_down else B["shin"])
    ua, fa = B["upper_arm"], B["forearm"]
    d = math.radians(depth)
    sz = WRIST_Z + fa - ua * math.cos(d)
    sx = math.sqrt(max(L * L - (sz - pivot_z) ** 2, 1e-9))
    return np.array([sx - ua * math.sin(d), WRIST_Z])


def synth_pushups(*, depth: float = 75.0, lockout: float = 176.0, knees_down: bool = False, hip_offset: float = 0.0,
                  n_reps: int = 5, rep_s: float = 2.0, noise: float = 0.0, extra_person: bool = False,
                  occlude_lower_body: bool = False, occlude_arms: bool = False, side: str = "left", body: str = "average", fps: float = 10.0,
                  lead_in_s: float = 1.0, tail_s: float = 0.5, aspect: float = 16 / 9, seed: int = 0,
                  bottom_hold_s: float = 0.0, hand_motions: list | tuple = (), far_vis: float = 0.45,
                  pauses: list | tuple = (), camera_shifts: list | tuple = ()) -> SynthClip:
    """Side-view plank push-up clip at `fps`. depth / lockout = elbow angle (deg) at the bottom / top of every rep.
    fire_times = the end of each rep cycle (back at the top), when a rep counter would fire. n_reps=0 = a plank hold.
    hand_motions / far_vis / pauses / camera_shifts: see the module docstring. occlude_lower_body / occlude_arms: knees,
    ankles and feet / both shoulders, elbows and wrists at visibility 0.08 in every frame."""
    if not 0.0 <= bottom_hold_s < rep_s:
        raise ValueError("bottom_hold_s must be in [0, rep_s)")
    if side not in ("left", "right"):
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")
    for m in hand_motions:
        if len(m) != 4 or m[0] not in ("tap", "lift") or m[1] not in ("left", "right") or float(m[3]) <= 0:
            raise ValueError(f"hand motion must be (tap|lift, left|right, t0, dur>0), got {m!r}")
    pz = sorted((float(a), float(d)) for a, d in pauses)
    if any(d <= 0 for _, d in pz) or any(pz[i][0] + pz[i][1] > pz[i + 1][0] for i in range(len(pz) - 1)):
        raise ValueError(f"pauses must be non-overlapping (t0, dur>0), got {pauses!r}")
    for c in camera_shifts:
        if len(c) != 4 or float(c[1]) <= 0:
            raise ValueError(f"camera shift must be (t0, dur>0, dx, dy), got {c!r}")
    B = BODIES[body]
    rng = np.random.default_rng(seed)
    wrist = _wrist_for(B, knees_down, depth)
    T = lead_in_s + n_reps * rep_s + tail_s + sum(d for _, d in pz)
    n_frames = int(math.floor(T * fps + 1e-9)) + 1

    def phase_t(t: float) -> float:          # real time -> rep-phase time (paused spans removed)
        return t - sum(min(max(t - a, 0.0), d) for a, d in pz)

    def real_t(te: float) -> float:          # inverse: the real time a phase time is reached
        t = te
        for a, d in pz:
            if a < t - 1e-12:
                t += d
        return t

    fires = [round(real_t(lead_in_s + (k + 1) * rep_s), 9) for k in range(n_reps)]
    near_i = (11, 13, 15, 23, 25, 27) if side == "left" else (12, 14, 16, 24, 26, 28)
    far_i = (12, 14, 16, 24, 26, 28) if side == "left" else (11, 13, 15, 23, 25, 27)
    dirn = -1.0 if side == "left" else 1.0
    s = B["scale"]
    def theta_at(te: float) -> float:
        u = te - lead_in_s
        if u <= 0 or u >= n_reps * rep_s:
            return lockout
        v = u % rep_s
        half = (rep_s - bottom_hold_s) / 2
        if v < half:
            k = (1 - math.cos(math.pi * v / half)) / 2
        elif v < half + bottom_hold_s:
            k = 1.0
        else:
            k = (1 + math.cos(math.pi * (v - half - bottom_hold_s) / half)) / 2
        return lockout - (lockout - depth) * k

    poses = [(i / fps, _pose(B, theta_at(phase_t(i / fps)), knees_down, hip_offset, wrist)) for i in range(n_frames)]
    # framing from the body alone, as if never paused (hand motions and pauses do not re-centre the camera, so a
    # clip's frames before a pause / motion are identical to the clip without it)
    n_ref = int(math.floor((T - sum(d for _, d in pz)) * fps + 1e-9)) + 1
    ref = poses if not pz else [(0.0, _pose(B, theta_at(i / fps), knees_down, hip_offset, wrist)) for i in range(n_ref)]
    xs = [p[k][0] for _, p in ref for k in p]
    xmid = (min(xs) + max(xs)) / 2
    frames: list[FrameObs] = []
    for t, p in poses:
        img = np.zeros((33, 5))
        img[:, 3] = 0.3
        img[:, 4] = 0.9
        world = np.zeros((33, 3))
        order = ("S", "E", "W", "H", "K", "A")
        hands: dict[str, tuple[dict, float]] = {}
        for hand in ("left", "right"):
            ph, kmax = p, 0.0
            for kind, mh, t0, dur in hand_motions:
                k = _motion_amount(t, float(t0), float(dur))
                if mh == hand and k > kmax:
                    w, e = _moved_hand(B, p, kind, k)
                    ph, kmax = {**p, "W": w, "E": e}, k
            hands[hand] = (ph, kmax)
        near_p, near_k = hands[side]
        far_p, far_k = hands["right" if side == "left" else "left"]

        def put(idx: int, X: np.ndarray, vis: float, lateral: float) -> None:
            img[idx, 0] = (aspect / 2 + dirn * (X[0] - xmid) * s) / aspect
            img[idx, 1] = FLOOR_Y - X[1] * s
            img[idx, 3] = vis
            img[idx, 4] = 0.99
            world[idx] = (dirn * X[0], -X[1], lateral)

        for k, idx in zip(order, near_i):
            put(idx, near_p[k], float(np.clip(0.95 + rng.normal(0, 0.02), 0, 1)), -0.18)
        for k, idx in zip(order, far_i):
            vis = float(np.clip(far_vis + rng.normal(0, 0.05), 0, 1))
            if k in ("E", "W") and far_k > 0:
                vis = max(vis, far_vis + far_k * (0.95 - far_vis))
            put(idx, far_p[k] + np.array([0.02, 0.02]), vis, 0.18)
        head = p["S"] + np.array([0.20, 0.02])
        for idx in range(0, 11):
            put(idx, head, 0.9, 0.0)
        for idx, k in ((17, "W"), (18, "W"), (19, "W"), (20, "W"), (21, "W"), (22, "W"),
                       (29, "A"), (30, "A"), (31, "A"), (32, "A")):
            src = (hands["left"] if idx % 2 else hands["right"])[0] if k == "W" else p   # odd = left (MediaPipe)
            put(idx, src[k] + np.array([0.05 if k == "W" else -0.05, -0.03]), 0.8, 0.0)
        world -= (world[23] + world[24]) / 2
        for c0, cd, cdx, cdy in camera_shifts:
            k = _motion_amount(t, float(c0), float(cd))
            if k > 0:
                img[:, 0] += k * float(cdx) / aspect
                img[:, 1] += k * float(cdy)
        if noise > 0:
            img[:, 0] += rng.normal(0, noise / aspect, 33)
            img[:, 1] += rng.normal(0, noise, 33)
        if occlude_lower_body:
            for idx in (25, 26, 27, 28, 29, 30, 31, 32):
                img[idx, 3] = 0.08
                img[idx, 4] = 0.3
        if occlude_arms:
            for idx in (11, 12, 13, 14, 15, 16):
                img[idx, 3] = 0.08
                img[idx, 4] = 0.3
        frames.append(FrameObs(t=t, img=img, world=world, persons=2 if extra_person else 1, aspect=aspect))
    meta = dict(depth=depth, lockout=lockout, knees_down=knees_down, hip_offset=hip_offset, n_reps=n_reps, rep_s=rep_s,
                noise=noise, bottom_hold_s=bottom_hold_s, extra_person=extra_person,
                occlude_lower_body=occlude_lower_body, occlude_arms=occlude_arms, side=side, body=body,
                fps=fps, seed=seed, hand_motions=[tuple(m) for m in hand_motions], far_vis=far_vis,
                pauses=pz, camera_shifts=[tuple(c) for c in camera_shifts])
    return SynthClip(frames=frames, fire_times=fires, meta=meta)


def accumulate_clip(clip: SynthClip, thr: dict | None = None, *, fire_lag_s: float = 0.0,
                    labels: list[str] | None = None, torso_ok: bool | None = None,
                    acc: RepMetricsAccumulator | None = None) -> list[RepMetrics]:
    """Replay a clip through a RepMetricsAccumulator, closing each rep `fire_lag_s` after its fire time is passed
    (frames beyond the fire time are already buffered, as with a lagging counter)."""
    acc = acc or RepMetricsAccumulator(thr)
    out: list[RepMetrics] = []
    pending = list(clip.fire_times)
    for f in clip.frames:
        acc.add_frame(f)
        while pending and f.t >= pending[0] + fire_lag_s - 1e-9:
            out.append(acc.close_rep(pending.pop(0), list(labels or []), torso_ok))
    for tf in pending:
        out.append(acc.close_rep(tf, list(labels or []), torso_ok))
    return out
