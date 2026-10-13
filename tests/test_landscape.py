"""The coach-video follows the caller's physical phone: portrait canvas when it is upright, a 1280x720 landscape canvas when
it is held sideways (facetime/frameprep.py phone_sideways + OrientationGate, pushup_mirror landscape layout, worker wiring)."""
import asyncio
import time
from types import SimpleNamespace

import numpy as np
import pytest

from challenge.judge.gates import DEFAULT_THRESHOLDS
from facetime import pushup_mirror as pmod
from facetime import worker
from facetime.frameprep import FramePrep, OrientationGate, ORIENT_SUSTAIN_S, ORIENT_HOLD_S, phone_sideways, rotate
from facetime.pushup_mirror import MirrorState, PushupMirror

from test_pushup_mirror import plank, SRC


def bridge(content):
    """Chert's 1280x720 bridge frame with the caller's picture letterboxed in it (flat black around)."""
    out = np.zeros((720, 1280, 3), np.uint8); h, w = content.shape[:2]; x0 = (1280 - w) // 2
    out[:h, x0:x0 + w] = content
    return out


PORTRAIT_PIC = np.full((400, 226, 3), 90, np.uint8)        # an upright phone: a 9:16 picture
LANDSCAPE_PIC = np.full((274, 486, 3), 90, np.uint8)       # a sideways phone without rotation lock: 16:9


def _fed(pic, n=8, rotation=0, t0=0.0):
    prep = FramePrep(probe=lambda img: None); prep.rotation = rotation
    raw = bridge(pic)
    for k in range(n): prep(raw, t0 + 0.25 * k)
    return prep, raw


# ---------------------------------------------------------------------------------------------------- the signal
def test_phone_sideways_from_the_picture_shape_and_the_rotation():
    assert phone_sideways(*_fed(PORTRAIT_PIC)) is False                    # upright: portrait picture, no turn
    assert phone_sideways(*_fed(LANDSCAPE_PIC)) is True                    # sideways, no lock: landscape picture
    assert phone_sideways(*_fed(PORTRAIT_PIC, rotation=90)) is True        # sideways with portrait lock: FramePrep turned it
    assert phone_sideways(*_fed(PORTRAIT_PIC, rotation=270)) is True
    assert phone_sideways(None, None) is None


def test_phone_sideways_has_no_evidence_from_black_or_square_frames():
    prep, raw = _fed(np.zeros((400, 226, 3), np.uint8))                    # black: content_box falls back to the frame
    assert phone_sideways(prep, raw) is None
    assert phone_sideways(*_fed(np.full((400, 400, 3), 90, np.uint8))) is None   # square: no call either way
    assert phone_sideways(FramePrep(probe=lambda img: None), None) is None       # nothing seen yet


def test_phone_sideways_ignores_black_frame_samples_among_real_ones():
    prep = FramePrep(probe=lambda img: None)
    black = np.zeros((720, 1280, 3), np.uint8); pic = bridge(PORTRAIT_PIC)
    for k in range(4): prep(black, 0.25 * k)                               # the call starts on black frames
    for k in range(4, 6): prep(pic, 0.25 * k)                              # then the upright picture
    assert phone_sideways(prep, pic) is False


def test_a_picture_that_fills_the_bridge_frame_counts():
    prep = FramePrep(probe=lambda img: None); raw = np.full((720, 1280, 3), 90, np.uint8)
    for k in range(4): prep(raw, 0.25 * k)
    assert phone_sideways(prep, raw) is True


# ---------------------------------------------------------------------------------------------------- hysteresis
def test_gate_starts_portrait_and_switches_only_after_sustained_evidence():
    g = OrientationGate()
    assert g.landscape is False and g.update(None, 0.0) is False
    t = 0.0
    while t < ORIENT_SUSTAIN_S - 0.1:
        assert g.update(True, t) is False; t += 0.1
    assert g.update(True, ORIENT_SUSTAIN_S + 0.01) is True and g.n_switches == 1


def test_gate_does_not_flap():
    g = OrientationGate()
    for k in range(100):                                                   # 10 s of alternating 1.5 s bursts
        g.update((k // 15) % 2 == 0, 0.1 * k)
    assert g.landscape is False and g.n_switches == 0
    for k in range(40): g.update(True if k != 10 else False, 20.0 + 0.1 * k)   # one contrary sample restarts the clock
    assert g.n_switches == 1 and g.switch_t >= 21.0 + ORIENT_SUSTAIN_S - 1e-6


def test_gate_none_neither_confirms_nor_cancels_and_holds_after_a_switch():
    g = OrientationGate()
    g.update(True, 0.0); g.update(None, 1.0); g.update(None, 1.9)
    assert g.update(True, 2.05) is True                                   # black frames in between did not cancel it
    t = 2.05
    for k in range(1, 140):                                               # upright again right away: held ORIENT_HOLD_S
        g.update(False, t + 0.1 * k)
        if g.landscape is False: break
    assert g.switch_t - 2.05 >= ORIENT_HOLD_S - 1e-6


# ---------------------------------------------------------------------------------------------------- the landscape layout
def _render(pm, rgb, landscape, st=None, n=6, lm='plank'):
    st = st or MirrorState(time_left_s=42.0)
    img = None
    for k in range(n):
        img = pm.render(rgb, plank() if lm == 'plank' else lm, DEFAULT_THRESHOLDS, st, now=0.1 * k, seq=k, landscape=landscape)
    return img


def test_landscape_render_shape_and_idle_card_stays_portrait():
    pm = PushupMirror()
    rgb = np.full(SRC, 100, np.uint8); before = rgb.copy()
    img = _render(pm, rgb, True)
    assert img.shape == (pmod.LH, pmod.LW, 3) == (720, 1280, 3) and img.dtype == np.uint8
    assert np.array_equal(rgb, before)
    assert pm.render(None, None, None, MirrorState(), now=2.0, landscape=True).shape == (1280, 720, 3)
    assert pm.render(rgb, plank(), None, MirrorState(), now=2.1, seq=99).shape == (1280, 720, 3)   # and back
    for src in ((486, 274, 3), (720, 1280, 3), (480, 640, 3)):            # any picture shape fits (a turned one is portrait)
        assert _render(PushupMirror(mascot=False), np.full(src, 90, np.uint8), True).shape == (720, 1280, 3)


def test_landscape_shows_the_whole_picture_unzoomed_and_unmoved():
    pm = PushupMirror(mascot=False)
    rgb = np.zeros(SRC, np.uint8); rgb[:] = (0, 255, 255)                 # a colour nothing else on the canvas uses
    boxes = set()
    for k in range(30):
        lm = plank(); lm[:, 0] -= 0.006 * k                               # the person moves
        img = pm.render(rgb, lm, DEFAULT_THRESHOLDS, MirrorState(), now=0.066 * k, seq=k, landscape=True)
        boxes.add(pm.boxes['picture'])
    assert len(boxes) == 1
    x0, y0, x1, y1 = boxes.pop()
    assert abs((x1 - x0) / (y1 - y0) - SRC[1] / SRC[0]) < 0.01           # the source's aspect: nothing cropped off
    assert x1 - x0 >= 0.6 * pmod.LW                                       # large: most of the canvas width
    m = np.all(img == (0, 255, 255), axis=2); ys, xs = np.nonzero(m)
    assert xs.min() >= x0 and xs.max() < x1 and ys.min() >= y0 and ys.max() < y1
    assert m[y0 + 2, x0 + 2] and m[y1 - 3, x1 - 3]                        # the corners of the picture are on screen


def test_landscape_render_costs_no_more_than_portrait():
    rgb = (np.random.default_rng(1).integers(0, 255, SRC)).astype(np.uint8)
    def bench(landscape):
        pm = PushupMirror()
        st = MirrorState(time_left_s=60.0); st.say('Go lower', now=0.0); st.speaking = True
        for k in range(10): pm.render(rgb, plank(), None, st, now=0.1 * k, seq=k, landscape=landscape)
        best = 1e9
        for _ in range(3):
            t0 = time.perf_counter()
            for k in range(30): pm.render(rgb, plank(), None, st, now=1.0 + 0.066 * k, seq=10 + k // 2, landscape=landscape)
            best = min(best, (time.perf_counter() - t0) / 30 * 1000)
        return best
    pt, ls = bench(False), bench(True)
    assert ls < 25.0, ls                                                  # the live loop's budget, like the portrait test
    assert ls <= 1.15 * pt + 1.0, (ls, pt)


# ---------------------------------------------------------------------------------------------------- FaceTime fill
SCREEN = 19.5 / 9                                                         # iPhone long side / short side


def visible(canvas_h, canvas_w):
    """(x0, y0, x1, y1) of the canvas a 19.5:9 iPhone shows with FaceTime Fill in the canvas's own orientation."""
    if canvas_w > canvas_h:                                               # landscape screen: full width, rows cut
        vh = canvas_w / SCREEN; c = (canvas_h - vh) / 2
        return (0, c, canvas_w, canvas_h - c)
    vw = canvas_h / SCREEN; c = (canvas_w - vw) / 2                       # portrait screen: full height, columns cut
    return (c, 0, canvas_w - c, canvas_h)


def inside(box, area):
    return box[0] >= area[0] - 1e-6 and box[1] >= area[1] - 1e-6 and box[2] <= area[2] + 1e-6 and box[3] <= area[3] + 1e-6


def diff_box(a, b):
    ys, xs = np.nonzero(np.any(a != b, axis=2))
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


@pytest.mark.parametrize('landscape', [False, True])
def test_facetime_fill_keeps_count_status_brodie_and_picture_on_screen(landscape):
    rgb = np.full(SRC if landscape else (SRC[1], SRC[0], 3), 100, np.uint8)   # what each phone orientation sends (upright)
    def frame(count, mascot=True):
        pm = PushupMirror(mascot=mascot)
        st = MirrorState(time_left_s=42.0); st.count = count
        return _render(pm, rgb, landscape, st), pm
    a, pm = frame(3); b, _ = frame(188); c, _ = frame(3, mascot=False)
    H_, W_ = a.shape[:2]
    vis = visible(H_, W_)
    if landscape:
        assert (W_, H_) == (1280, 720) and abs(vis[1] - pmod.LS_CROP_Y) < 1.0
        safe = (pmod.LS_SAFE_X, pmod.LS_SAFE_TOP, pmod.LW - pmod.LS_SAFE_X, pmod.LS_SAFE_BOTTOM)
        pip_y = vis[3] - pmod.LS_PIP_H
        keep_out = [(0, pip_y, pmod.LS_PIP_W, H_), (W_ - pmod.LS_PIP_W, pip_y, W_, H_)]   # the self-view, either corner
    else:
        assert (W_, H_) == (720, 1280)
        safe = (pmod.SAFE_X - 6, 0, W_ - pmod.SAFE_X + 6, pmod.SAFE_BOTTOM)
        keep_out = []
    assert inside(safe, vis)
    boxes = dict(pm.boxes)
    # what the renderer reports
    for k in ('count', 'pill', 'mascot', 'timer'):
        assert inside(boxes[k], safe), (k, boxes[k], safe)
        assert not any(overlaps(boxes[k], z) for z in keep_out), (k, boxes[k])
    assert inside(boxes['picture'], vis)
    # what the pixels say: the count (3 vs 188) and Brodie (with vs without) change only on screen
    cb = diff_box(a, b); assert inside(cb, vis) and overlaps(cb, boxes['count'])
    mb = diff_box(a, c); assert inside(mb, vis), (mb, vis)
    assert not any(overlaps(mb, z) for z in keep_out), mb


@pytest.mark.parametrize('landscape', [False, True])
def test_facetime_fill_keeps_the_cue_bubble_and_stamp_on_screen(landscape):
    pm = PushupMirror(); rgb = np.full(SRC, 100, np.uint8)
    st = MirrorState(time_left_s=42.0)
    st.say('Chest all the way down, bro, all the way', now=0.0); st.speaking = True
    st.rep(False, ['hips_sag'], now=0.4)
    img = _render(pm, rgb, landscape, st)
    vis = visible(*img.shape[:2])
    assert inside(pm.boxes['bubble'], vis) and 'stamp' in pm.boxes
    sx0, sy0, sx1, sy1 = pm.boxes['stamp']                                # the stamp's settled centre is on screen
    assert inside(((sx0 + sx1) / 2, (sy0 + sy1) / 2, (sx0 + sx1) / 2, (sy0 + sy1) / 2), vis)


# ---------------------------------------------------------------------------------------------------- worker wiring
def _mirror_job(monkeypatch, captured):
    class Source:
        def __init__(self, w, h): pass
        def capture_frame(self, f): captured.append((f.width, f.height))
    monkeypatch.setattr(worker.rtc, 'VideoSource', Source)
    monkeypatch.setattr(worker.rtc.LocalVideoTrack, 'create_video_track', staticmethod(lambda name, src: SimpleNamespace(name=name)))
    async def publish_track(track, opts): pass
    job = worker.CoachJob.__new__(worker.CoachJob)
    job.a = SimpleNamespace(avatar_fps=50.0, mirror=True, mirror_fps=50.0); job.player = SimpleNamespace(playing=None)
    job.room = SimpleNamespace(local_participant=SimpleNamespace(publish_track=publish_track))
    job.stop = worker.threading.Event(); job.mirror_in = None; job.mirror_live = False; job.mirror_state = None
    return job


def test_mirror_loop_switches_the_canvas_when_the_decision_flips(monkeypatch):
    captured = []; job = _mirror_job(monkeypatch, captured)
    rgb = np.full(SRC, 90, np.uint8); phase = {'n': 0}
    def drive():
        if not job.mirror_live: return False
        job.mirror_in = (rgb, plank(), 1, time.monotonic())               # a live caller frame every tick
        n = len(captured)
        if phase['n'] == 0 and n >= 3: job.mirror_landscape = True; phase.update(n=1, at=n)
        elif phase['n'] == 1 and n >= phase['at'] + 4: job.mirror_landscape = False; phase.update(n=2, at=n)
        elif phase['n'] == 2 and n >= phase['at'] + 4: job.mirror_in = None; phase.update(n=3, at=n)
        return phase['n'] == 3 and n >= phase['at'] + 2
    async def go():
        t = asyncio.create_task(job.avatar_loop())
        for _ in range(1500):
            if t.done(): break
            stop = drive()
            if stop: break
            await asyncio.sleep(0.005)
        job.stop.set(); await asyncio.wait_for(t, 5)
    asyncio.run(go())
    sizes = [c for i, c in enumerate(captured) if i == 0 or c != captured[i - 1]]
    assert (1280, 720) in captured and sizes[0] == (720, 1280)
    assert sizes[:3] == [(720, 1280), (1280, 720), (720, 1280)]           # portrait -> landscape -> portrait, no flicker
    assert captured[-1] == (720, 1280)                                    # no caller video: the idle card, portrait


def test_idle_card_is_portrait_even_when_the_phone_was_sideways(monkeypatch):
    job = worker.CoachJob.__new__(worker.CoachJob); job.mirror_thresholds = lambda: None
    r = PushupMirror(mascot=False)
    f = job._mirror_frame(r, None, None, MirrorState(), 0.0, [0, 0], dict(n=0, ms=0.0), landscape=True)
    assert (f.width, f.height) == (720, 1280)
    f = job._mirror_frame(r, None, (np.full(SRC, 90, np.uint8), None, 1, 0.0), MirrorState(), 0.0, [0, 0], dict(n=0, ms=0.0), landscape=True)
    assert (f.width, f.height) == (1280, 720)


def test_feed_layout_follows_the_phone_with_hysteresis(capsys):
    job = worker.CoachJob.__new__(worker.CoachJob)
    job.pipe = SimpleNamespace(pose_variant='full'); job.prep = FramePrep(probe=lambda img: None)
    up, side = bridge(PORTRAIT_PIC), bridge(LANDSCAPE_PIC)
    t, seen = 0.0, []
    def step(raw):
        nonlocal t
        job.prep_frame(raw, t); job.update_layout(raw, t); seen.append((t, job.mirror_landscape)); t += 0.1
    for _ in range(30): step(up)
    assert job.mirror_landscape is False
    t_turn = t
    for _ in range(100): step(side)                                       # the phone goes sideways for 10 s
    assert job.mirror_landscape is True
    first = min(tt for tt, v in seen if v)
    assert first - t_turn >= ORIENT_SUSTAIN_S - 1e-6                      # not before the sustain
    assert sum(1 for i in range(1, len(seen)) if seen[i][1] != seen[i - 1][1]) == 1   # one switch, no flapping
    assert "phone sideways: coach-video landscape" in capsys.readouterr().out
    job.prep.rotation = 90                                                # portrait-locked and sideways: still landscape
    for _ in range(40): step(up)
    assert job.mirror_landscape is True


def test_layout_update_failure_is_logged_and_keeps_the_layout(capsys):
    job = worker.CoachJob.__new__(worker.CoachJob)
    class Boom:
        rotation = 0
        @property
        def content(self): raise RuntimeError('boom')
    job.prep = Boom(); job.mirror_landscape = True
    for k in range(3): job.update_layout(np.zeros((8, 8, 3), np.uint8), float(k))
    assert job.mirror_landscape is True and job.layout_fails == 3
    assert capsys.readouterr().out.count('layout update failed') == 1


def test_rotated_portrait_picture_turned_upright_reads_as_sideways():
    content = np.full((360, 640, 3), 100, np.uint8)
    prep = FramePrep(probe=lambda img: None); prep.rotation = 90
    raw = bridge(rotate(content, 270))
    for k in range(4): up = prep(raw, 0.25 * k)
    assert up.shape[:2] == (360, 640) and phone_sideways(prep, raw) is True


def test_gate_holds_a_switch_long_enough_for_the_caller_to_place_the_phone():
    """A live call (2026-10-13) flapped sideways -> upright -> sideways within 6 s while the phone was being set down."""
    g = OrientationGate()
    t = 0.0
    while not g.landscape: t += 0.1; g.update(True, t)
    switched = t
    while g.landscape and t < switched + 30: t += 0.1; g.update(False, t)
    assert ORIENT_HOLD_S >= 8.0 and t - switched >= 8.0 - 1e-6 and g.n_switches == 2
