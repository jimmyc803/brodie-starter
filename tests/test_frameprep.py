"""facetime/frameprep.py: the bridge content crop and the orientation lock (a phone held sideways under a portrait lock)."""
import os

import numpy as np
import pytest

from facetime.frameprep import ContentRect, FramePrep, content_box, plank_score, rotate, standing_score

ASPECT = 16 / 9
FPS = 15
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def plank():
    """A side-view plank in an upright landscape picture (normalised x, y, z, visibility, presence)."""
    lm = np.zeros((33, 5), np.float32); lm[:, 3] = 0.9; lm[:, 4] = 0.99; lm[:, :2] = (0.55, 0.53)
    for i, (x, y) in {0: (0.30, 0.48), 7: (0.32, 0.47), 11: (0.35, 0.50), 13: (0.36, 0.62), 15: (0.36, 0.74), 23: (0.55, 0.53),
                      25: (0.68, 0.56), 27: (0.80, 0.58), 31: (0.83, 0.60)}.items():
        lm[i, :2] = (x, y)
    for i in (8, 12, 14, 16, 24, 26, 28, 32):
        lm[i, :2] = lm[i - 1, :2] + 0.004; lm[i, 3] = 0.3
    return lm


def standing():
    lm = plank()
    for i, (x, y) in {0: (0.5, 0.12), 7: (0.49, 0.12), 11: (0.5, 0.3), 13: (0.5, 0.42), 15: (0.5, 0.52), 23: (0.5, 0.55),
                      25: (0.5, 0.72), 27: (0.5, 0.9)}.items():
        lm[i, :2] = (x, y); lm[i + 1, :2] = (x + 0.004, y)
    return lm


def desk_pushup():
    """A caller doing STANDING push-ups against a desk in an upright portrait picture (live call b632c373,
    2026-10-13): torso ~80 deg from horizontal, hands forward-down onto the desk, elbows nearly straight."""
    lm = plank()
    for i, (x, y) in {0: (0.42, 0.18), 7: (0.44, 0.19), 11: (0.45, 0.30), 13: (0.52, 0.42), 15: (0.58, 0.52),
                      23: (0.52, 0.55), 25: (0.55, 0.75), 27: (0.58, 0.93)}.items():
        lm[i, :2] = (x, y); lm[i + 1, :2] = (x + 0.004, y)
    return lm


def wall_pushup():
    """A caller doing push-ups against a WALL, hands at/above shoulder height (live 2026-10-13 #2): torso near
    vertical leaning INTO the wall, arms up-forward. The lean toward the hands is what marks a stander."""
    lm = plank()
    for i, (x, y) in {0: (0.33, 0.20), 7: (0.35, 0.21), 11: (0.40, 0.32), 13: (0.33, 0.28), 15: (0.26, 0.24),
                      23: (0.50, 0.58), 25: (0.54, 0.76), 27: (0.58, 0.94)}.items():
        lm[i, :2] = (x, y); lm[i + 1, :2] = (x + 0.004, y)
    return lm


def turned(lm, deg):
    """The landmarks of `lm` in the picture turned `deg` clockwise (what the pose model sees on a sideways phone)."""
    out = lm.copy(); x, y = lm[:, 0].copy(), lm[:, 1].copy()
    if deg == 90: out[:, 0], out[:, 1] = 1.0 - y, x
    elif deg == 270: out[:, 0], out[:, 1] = y, 1.0 - x
    return out


# ------------------------------------------------------------------------------------------------- content rect
def bridge(content, size=(720, 1280), x0=None, y0=0):
    out = np.zeros((*size, 3), np.uint8); h, w = content.shape[:2]
    x0 = (size[1] - w) // 2 if x0 is None else x0
    out[y0:y0 + h, x0:x0 + w] = content
    return out


def test_content_box_finds_the_letterboxed_picture():
    f = bridge(np.full((274, 486, 3), 90, np.uint8))           # the live log: x 0.31-0.69, y 0.00-0.38
    x0, y0, x1, y1 = content_box(f)
    assert abs(x0 - 397) <= 4 and y0 == 0 and abs(x1 - 883) <= 4 and abs(y1 - 274) <= 4


def test_content_box_keeps_a_narrow_pillarboxed_portrait_picture():
    f = bridge(np.full((446, 250, 3), 90, np.uint8))           # a rotated picture: ~20% of the width
    x0, _, x1, _ = content_box(f)
    assert abs((x1 - x0) - 250) <= 8


def test_content_box_of_a_black_or_tiny_picture_is_the_whole_frame():
    assert content_box(np.zeros((720, 1280, 3), np.uint8)) == (0, 0, 1280, 720)
    assert content_box(bridge(np.full((40, 60, 3), 90, np.uint8))) == (0, 0, 1280, 720)


def test_content_rect_is_slow_and_ignores_a_brief_black_frame():
    cr = ContentRect(); a = bridge(np.full((274, 486, 3), 90, np.uint8)); black = np.zeros_like(a)
    t = 0.0; r0 = None
    for k in range(60):                                          # 4 s with two black frames in it
        r = cr.update(black if k in (20, 21) else a, t); t += 1 / FPS
        r0 = r0 or r
        assert r == r0
    b = bridge(np.full((274, 486, 3), 90, np.uint8), x0=100)     # the window moves: follows only once it has stayed moved
    first = None
    for k in range(90):
        r = cr.update(b, t)
        if r != r0 and first is None: first = t
        t += 1 / FPS
    assert first is not None and first - 4.0 >= 1.4
    assert abs(r[0] - 100) <= 4
    assert all(v % 2 == 0 for v in r)


# ------------------------------------------------------------------------------------------------- plank score
def test_plank_score_upright_is_a_plank_and_turned_is_not():
    assert plank_score(plank(), ASPECT) > 0.5
    for deg in (90, 270):
        assert plank_score(turned(plank(), deg), 1 / ASPECT) == 0.0


def test_plank_score_standing_is_not_a_plank_either_way():
    assert plank_score(standing(), ASPECT) == 0.0
    for deg in (90, 270):
        assert plank_score(turned(standing(), deg), 1 / ASPECT) == 0.0


def test_standing_score_knows_a_stander_from_a_plank_turned_head_up():
    assert standing_score(standing(), ASPECT) > 0.5                       # arms hanging
    assert standing_score(desk_pushup(), 486 / 720) > 0.5                 # hands resting on the desk below the shoulders
    assert standing_score(wall_pushup(), 486 / 720) > 0.5                 # hands up on the wall: the lean marks a stander
    assert plank_score(desk_pushup(), 486 / 720) == 0.0                   # ... and no plank: the judge must not count it
    assert standing_score(plank(), ASPECT) == 0.0                         # a plank is not a stander
    for deg in (90, 270):
        assert standing_score(turned(standing(), deg), 1 / ASPECT) == 0.0   # a sideways phone shows a stander lying
        assert standing_score(turned(desk_pushup(), deg), 720 / 486) == 0.0
        assert standing_score(turned(wall_pushup(), deg), 720 / 486) == 0.0
        assert standing_score(turned(plank(), deg), 1 / ASPECT) == 0.0       # head-up turned plank: arms stick out sideways
    assert standing_score(None, ASPECT) == 0.0
    assert standing_score(np.zeros((10, 5)), ASPECT) == 0.0


def test_plank_score_handles_missing_or_malformed_landmarks():
    assert plank_score(None, ASPECT) == 0.0
    assert plank_score(np.zeros((10, 5)), ASPECT) == 0.0
    lm = plank(); lm[:, 3] = np.nan
    assert plank_score(lm, ASPECT) == 0.0


# ------------------------------------------------------------------------------------------------- orientation lock
def scene():
    """An upright landscape picture with a red mark in its top-left corner (the fake pose model's 'person')."""
    img = np.full((360, 640, 3), 100, np.uint8); img[:40, :40] = (255, 0, 0)
    return img


def upright(img):
    m = (img[..., 0] > 200) & (img[..., 1] < 60)
    if not m.any(): return False
    ys, xs = np.nonzero(m)
    return xs.mean() < img.shape[1] / 2 and ys.mean() < img.shape[0] / 2 and img.shape[1] > img.shape[0]


class FakePose:
    """A plank when the mark is top-left of a landscape picture (the scene is upright), else `other` (None)."""
    def __init__(self, other=None): self.other = other; self.calls = 0

    def __call__(self, img):
        self.calls += 1
        return plank() if upright(img) else self.other


def run(prep, frame, pose, seconds, t0=0.0):
    events, t = [], t0
    for _ in range(int(seconds * FPS)):
        up = prep(frame, t)
        sw = prep.observe(frame, pose(up), t)
        if sw: events.append((round(t, 2), sw))
        t += 1 / FPS
    return events, t


@pytest.mark.parametrize('held, fix', [(270, 90), (90, 270)])
def test_lock_turns_a_sideways_picture_upright(held, fix):
    pose = FakePose(); prep = FramePrep(probe=pose)
    frame = bridge(rotate(scene(), held))                         # portrait content in the black bridge frame
    events, t = run(prep, frame, pose, 4.0)
    assert [e[1] for e in events] == [(0, fix)]
    assert events[0][0] <= 2.5                                    # two probe wins, one second apart
    assert prep.rotation == fix and upright(prep(frame, t))
    n = prep.n_probes
    run(prep, frame, pose, 5.0, t)                                # upright now: a plank every frame, no more probing
    assert prep.n_probes == n and prep.rotation == fix
    assert f'rot {fix}' in prep.diag()


def test_lock_needs_consecutive_wins():
    """Hysteresis: a probe that wins only every other time never turns the picture."""
    calls = {'n': 0}

    def flaky(img):
        calls['n'] += 1
        return plank() if upright(img) and (calls['n'] // 2) % 2 == 0 else None
    prep = FramePrep(probe=flaky)
    frame = bridge(rotate(scene(), 270))
    prep_pose = lambda up: None
    events, _ = run(prep, frame, prep_pose, 8.0)
    assert prep.n_probes >= 8 and events == []


def test_lock_does_not_turn_a_landscape_picture_with_a_person_in_it():
    """A standing person in an upright landscape picture: no probing while there is a pose (a turned stander can look
    like a plank)."""
    probe = FakePose(other=plank())                               # the worst case: every turned probe says plank
    prep = FramePrep(probe=probe)
    frame = bridge(scene(), size=(720, 1280))
    events, t = run(prep, frame, lambda up: standing(), 10.0)
    assert events == [] and probe.calls == 0 and prep.rotation == 0
    # nobody at all for a while: probing starts, and needs three wins on landscape content
    events, _ = run(prep, frame, lambda up: None, 6.0, t)
    assert probe.calls > 0
    assert events and events[0][0] - t >= 3.0 + 2.0 - 1e-6


def test_lock_does_not_turn_a_portrait_picture_on_a_standing_caller():
    """Live 2026-10-13, call b632c373: a caller doing STANDING desk push-ups in an upright portrait picture read as a
    plausible plank once turned, and the lock flipped to 270 — breaking the judge AND the coach-video layout. A person
    standing upright in the current view proves the view is upright: no probing while they are seen."""
    probe = FakePose(other=plank())                                # the worst case: every turned probe says plank
    prep = FramePrep(probe=probe)
    frame = bridge(np.full((720, 486, 3), 90, np.uint8))           # the live call's pillarboxed portrait picture
    events, t = run(prep, frame, lambda up: desk_pushup(), 10.0)
    assert events == [] and probe.calls == 0 and prep.rotation == 0
    # ... and neither do WALL push-ups with the hands at shoulder height or above (live 2026-10-13 #2)
    events, t = run(prep, frame, lambda up: wall_pushup(), 10.0, t)
    assert events == [] and probe.calls == 0 and prep.rotation == 0
    # the stander walks out: portrait content with nobody in it probes again, so a real sideways phone still self-fixes
    # (the fake probe then calls EVERY orientation of the featureless grey picture a plank, so only the first flip counts)
    events, _ = run(prep, frame, lambda up: None, 4.0, t)
    assert probe.calls > 0 and events and events[0][1][0] == 0 and events[0][0] - t <= 2.5


def test_apply_reuses_the_geometry_and_rejects_other_frame_sizes():
    pose = FakePose(); prep = FramePrep(probe=pose)
    frame = bridge(rotate(scene(), 270)); run(prep, frame, pose, 4.0)
    out = prep.apply(frame)
    assert out is not None and upright(out) and out.flags['C_CONTIGUOUS']
    assert prep.apply(np.zeros((480, 640, 3), np.uint8)) is None
    assert FramePrep(probe=pose).apply(frame) is None              # nothing seen yet
