"""A break in the middle of a set: the rep counter has to keep counting when the person starts again.

The shape of a real break (2026-10-14 bug): the person pushes up onto their knees to rest, which takes the body out
of the prone body state, so the pushup gate goes off and the trackers are rebuilt; they lie back down and carry on.
"""
import numpy as np, pytest
from rtcoach.repcount2 import RepCounter2

FPS = 10


def _frame(depth, prone=True):
    """One synthetic side-on pushup frame. depth 0 = arms straight (top), 1 = elbows bent (bottom).
    prone=False is the same person up on their knees, resting."""
    img = np.zeros((33, 4), np.float32)
    img[:, 3] = 1.0
    if prone:
        sh_y = 0.40 + 0.06 * depth
        img[0, :2] = (0.70, sh_y - 0.03)                      # nose, out in front
        for s, sx in ((11, 0.60), (12, 0.61)):                # shoulders
            img[s, :2] = (sx, sh_y)
        for h, hx in ((23, 0.35), (24, 0.36)):                # hips, behind and level: torso near horizontal
            img[h, :2] = (hx, sh_y + 0.02)
        for k, kx in ((25, 0.20), (26, 0.21)): img[k, :2] = (kx, sh_y + 0.03)
        for a, ax in ((27, 0.08), (28, 0.09)): img[a, :2] = (ax, sh_y + 0.04)
        # arms: shoulder above elbow, wrist swinging from straight-down (180 deg) to horizontal (90 deg)
        ang = np.radians(180.0 - 90.0 * depth)
        for s, e, w, sx in ((11, 13, 15, 0.60), (12, 14, 16, 0.61)):
            ex, ey = sx, sh_y + 0.12
            img[e, :2] = (ex, ey)
            img[w, :2] = (ex + 0.12 * np.sin(ang - np.pi / 2) * -1, ey + 0.12 * -np.cos(ang - np.pi / 2) * -1)
            img[w, :2] = (ex + 0.12 * np.cos(ang - np.pi), ey + 0.12 * np.sin(np.pi - ang))
    else:
        img[0, :2] = (0.50, 0.26)
        for s, sx in ((11, 0.49), (12, 0.51)): img[s, :2] = (sx, 0.30)
        for h, hx in ((23, 0.49), (24, 0.51)): img[h, :2] = (hx, 0.55)
        for k, kx in ((25, 0.48), (26, 0.52)): img[k, :2] = (kx, 0.70)
        for a, ax in ((27, 0.47), (28, 0.53)): img[a, :2] = (ax, 0.80)
        for e, ex in ((13, 0.46), (14, 0.54)): img[e, :2] = (ex, 0.42)
        for w, wx in ((15, 0.45), (16, 0.55)): img[w, :2] = (wx, 0.54)

    world = np.zeros((33, 3), np.float32)
    if prone:
        # torso lies along x: uprightness ~0
        world[11] = (0.25, -0.02, 0.0); world[12] = (0.25, 0.02, 0.0)
        world[23] = (-0.25, -0.02, 0.0); world[24] = (-0.25, 0.02, 0.0)
        bend = np.radians(180.0 - 90.0 * depth)
        for s, e, w in ((11, 13, 15), (12, 14, 16)):
            world[e] = world[s] + (0.0, 0.0, 0.26)
            world[w] = world[e] + (0.26 * np.cos(np.pi - bend), 0.0, 0.26 * np.cos(bend))
    else:
        world[11] = (-0.02, -0.50, 0.0); world[12] = (0.02, -0.50, 0.0)
        world[23] = (-0.02, 0.0, 0.0); world[24] = (0.02, 0.0, 0.0)
        for s, e, w in ((11, 13, 15), (12, 14, 16)):
            world[e] = world[s] + (0.0, 0.22, 0.0)
            world[w] = world[e] + (0.0, 0.22, 0.0)
    for k, a, hp in ((25, 27, 23), (26, 28, 24)):
        world[k] = world[hp] + (-0.35, 0.0, 0.0) if prone else world[hp] + (0.0, 0.35, 0.0)
        world[a] = world[k] + (-0.35, 0.0, 0.0) if prone else world[k] + (0.0, 0.35, 0.0)
    return img, world


def _reps(n, period_s=1.4):
    """n pushups as a smooth down-up wave, starting and ending at the top (rest)."""
    per = int(period_s * FPS)
    out = []
    for r in range(n):
        for j in range(per):
            out.append(_frame(0.5 - 0.5 * np.cos(2 * np.pi * j / per)))
    return out


def _rest(seconds):
    return [_frame(0.0, prone=False) for _ in range(int(seconds * FPS))]


def _run(frames):
    rc = RepCounter2(fps=FPS, exercise='pushups', select='mask', gate=True, settle=True,
                     walk_vx=1.0, first_mask=True)
    for img, world in frames:
        rc.update(img, world, True)
    return rc


def test_counts_a_plain_set():
    rc = _run(_reps(8))
    assert rc.count == pytest.approx(8, abs=1)


def test_keeps_counting_after_a_break():
    """8 reps, a breather up on the knees, 8 more. The second half has to be counted too."""
    rc = _run(_reps(8) + _rest(3.0) + _reps(8))
    assert rc.n_gate_off >= 1, 'the break should take the body out of the prone gate'
    assert rc.count == pytest.approx(16, abs=2), f'lost the reps after the break: {rc.count}'


def test_keeps_counting_after_two_breaks():
    rc = _run(_reps(6) + _rest(3.0) + _reps(6) + _rest(3.0) + _reps(6))
    assert rc.count == pytest.approx(18, abs=3), f'lost the reps after the breaks: {rc.count}'
