import numpy as np
import pytest

from challenge.judge.gates import DEFAULT_THRESHOLDS
from facetime import pushup_mirror as pmod
from facetime.pushup_mirror import (GOOD, BAD, Framer, MirrorState, PushupMirror, StatusFilter, ST_BACK, ST_GOOD, ST_NONE,
                                    ST_PLANK, STATUS_TEXT, camera_status, verdict_lines)

ASPECT = 16 / 9


def plank(hip_y=0.53, ankle_vis=0.95, right_vis=0.3):
    """A side-view plank, left side to the camera (normalised x, y, z, visibility, presence)."""
    lm = np.zeros((33, 5), np.float32); lm[:, 3] = 0.9; lm[:, 4] = 0.99
    left = {11: (0.35, 0.50), 13: (0.36, 0.62), 15: (0.36, 0.74), 23: (0.55, hip_y), 25: (0.68, 0.56), 27: (0.80, 0.58), 31: (0.83, 0.60)}
    lm[:, 0], lm[:, 1] = 0.55, 0.53
    for i, (x, y) in left.items(): lm[i, :2] = (x, y)
    for i in (12, 14, 16, 24, 26, 28, 32):                       # far side: just behind, barely visible
        lm[i, :2] = lm[i - 1, :2] + 0.004; lm[i, 3] = right_vis
    lm[0, :2] = (0.30, 0.48); lm[7, :2] = (0.32, 0.47); lm[8, :2] = (0.322, 0.472); lm[8, 3] = right_vis
    lm[27, 3] = ankle_vis; lm[28, 3] = min(right_vis, ankle_vis)
    return lm


def frontal():
    """Plank seen from in front of the head (the phone on the floor ahead): shoulders wide, the torso foreshortened,
    the hands under the shoulders, the knees just visible behind the hips."""
    lm = np.zeros((33, 5), np.float32); lm[:, 3] = 0.9; lm[:, 4] = 0.99; lm[:, :2] = (0.5, 0.5)
    pts = {0: (0.50, 0.36), 7: (0.47, 0.35), 8: (0.53, 0.35), 11: (0.40, 0.45), 12: (0.60, 0.45), 13: (0.37, 0.58), 14: (0.63, 0.58),
           15: (0.38, 0.72), 16: (0.62, 0.72), 23: (0.46, 0.53), 24: (0.54, 0.53), 25: (0.47, 0.57), 26: (0.53, 0.57),
           27: (0.48, 0.60), 28: (0.52, 0.60)}
    for i, xy in pts.items(): lm[i, :2] = xy
    lm[27:33, 3] = 0.2                                            # feet hidden behind the body
    return lm


def diagonal_high():
    """Plank from a higher camera off the head-side diagonal: the body runs ~35 deg down the picture."""
    lm = plank(right_vis=0.4)
    for i, (x, y) in {0: (0.28, 0.30), 7: (0.30, 0.30), 11: (0.34, 0.36), 13: (0.33, 0.48), 15: (0.33, 0.60), 23: (0.52, 0.52),
                      25: (0.63, 0.60), 27: (0.74, 0.68), 31: (0.76, 0.70)}.items():
        lm[i, :2] = (x, y)
    return lm


def test_status_good_plank_side_view():
    assert camera_status(plank(), ASPECT) == ST_GOOD


def test_status_good_from_the_front_and_from_a_higher_diagonal():
    assert camera_status(frontal(), ASPECT) == ST_GOOD
    assert camera_status(diagonal_high(), ASPECT) == ST_GOOD


def test_status_feet_out_of_frame_is_still_good():
    assert camera_status(plank(ankle_vis=0.1), ASPECT) == ST_GOOD
    lm = plank(); lm[27, 0] = 1.04; lm[31, 0] = 1.06              # the judge's conf is 0 outside the image
    assert camera_status(lm, ASPECT) == ST_GOOD


def test_status_needs_hands_to_knees():
    lm = plank(); lm[25, 3] = 0.1                                 # the knee hidden
    assert camera_status(lm, ASPECT) == ST_BACK
    lm = plank(); lm[15, 1] = -0.02                               # the wrist out of the picture
    assert camera_status(lm, ASPECT) == ST_BACK


def test_status_standing_is_get_in_plank():
    lm = plank()
    for i, (x, y) in {11: (0.5, 0.3), 23: (0.5, 0.55), 25: (0.5, 0.72), 27: (0.5, 0.9), 13: (0.5, 0.42), 15: (0.5, 0.52)}.items():
        lm[i, :2] = (x, y); lm[i + 1, :2] = (x + 0.004, y)
    assert camera_status(lm, ASPECT) == ST_PLANK


def test_status_standing_from_the_front_is_not_a_plank():
    lm = frontal()
    for i, (x, y) in {11: (0.455, 0.30), 12: (0.545, 0.30), 23: (0.47, 0.55), 24: (0.53, 0.55), 13: (0.45, 0.42), 14: (0.55, 0.42),
                      15: (0.45, 0.54), 16: (0.55, 0.54), 25: (0.47, 0.72), 26: (0.53, 0.72)}.items():
        lm[i, :2] = (x, y)
    assert camera_status(lm, ASPECT) == ST_PLANK


def test_status_no_pose_and_no_phone_nagging():
    assert camera_status(None, ASPECT) == ST_NONE
    texts = ' '.join(t for pair in STATUS_TEXT.values() for t in pair if t)
    assert 'SIDEWAYS' not in texts and 'LANDSCAPE' not in texts


def test_status_filter_hysteresis():
    f = StatusFilter()
    assert f.update(ST_BACK) == ST_BACK                           # the first status shows at once
    assert f.update(ST_GOOD) == ST_BACK and f.update(ST_GOOD) == ST_BACK and f.update(ST_GOOD) == ST_BACK
    assert f.update(ST_GOOD) == ST_GOOD                           # four in a row for green
    assert f.update(ST_PLANK) == ST_GOOD and f.update(ST_GOOD) == ST_GOOD   # a one-frame blip does not switch
    for _ in range(2): assert f.update(ST_PLANK) == ST_GOOD
    assert f.update(ST_PLANK) == ST_PLANK


# The mirror colours follow whatever thresholds it is given. These fixtures were drawn for the strict j2 gate values
# (judge j3 defaults are lenient: hip 30, depth 125, lockout 135), so the geometry tests pin those values explicitly.
J2_THR = dict(DEFAULT_THRESHOLDS, hip_line_max_dev_deg=17.5, depth_elbow_max_deg=100, lockout_min_deg=150)


def _feed(pm, lm, n=5, t0=0.0, thr=DEFAULT_THRESHOLDS):
    rgb = np.full((720, 1280, 3), 100, np.uint8)
    img = None
    for k in range(n):
        img = pm.render(rgb, lm.copy(), thr, MirrorState(), now=t0 + 0.1 * k, seq=k + int(t0 * 100))
    return img


def test_good_plank_is_green_and_sagging_hips_are_red():
    pm = PushupMirror(mascot=False)
    img = _feed(pm, plank())
    assert img.shape == (1280, 720, 3) and img.dtype == np.uint8
    body, legs, arm, hip_lab, knee_lab = pm._colors()
    assert pm.status.shown == ST_GOOD and body == GOOD and legs == GOOD and hip_lab is None
    _feed(pm, plank(hip_y=0.61), t0=1.0, thr=J2_THR)
    body, legs, arm, hip_lab, knee_lab = pm._colors()
    assert body == BAD and hip_lab == 'HIPS SAGGING'
    assert pm.form.dev > J2_THR['hip_line_max_dev_deg']


def test_colours_follow_the_live_thresholds():
    pm = PushupMirror(mascot=False)
    thr = dict(DEFAULT_THRESHOLDS, hip_line_max_dev_deg=60.0)
    rgb = np.full((720, 1280, 3), 100, np.uint8)
    for k in range(5): pm.render(rgb, plank(hip_y=0.61), thr, MirrorState(), now=0.1 * k, seq=k)
    assert pm._colors()[0] == GOOD


def test_no_form_colours_until_the_camera_angle_is_good():
    pm = PushupMirror(mascot=False)
    lm = plank(); lm[25, 3] = 0.1                                 # no knee: SHOW HANDS TO KNEES
    _feed(pm, lm)
    assert pm.status.shown == ST_BACK and pm._colors() == (pmod.WHITE,) * 3 + (None, None)


def test_front_view_is_good_but_draws_no_body_line_verdict():
    pm = PushupMirror(mascot=False)
    _feed(pm, frontal())
    body, legs, arm, hip_lab, knee_lab = pm._colors()
    assert pm.status.shown == ST_GOOD and body == pmod.WHITE and hip_lab is None   # 2-D hip angles mean nothing from the front


def test_depth_latch_per_rep():
    pm = PushupMirror(mascot=False)
    lm = plank(); _feed(pm, lm, thr=J2_THR)
    assert not pm.depth_hit
    bent = plank(); bent[13, :2] = (0.30, 0.62); bent[15, :2] = (0.36, 0.70)         # elbow well under 100 deg
    _feed(pm, bent, t0=1.0, thr=J2_THR)
    assert pm.form.elbow <= J2_THR['depth_elbow_max_deg'] and pm.depth_hit
    _feed(pm, lm, t0=2.0, thr=J2_THR); assert pm.depth_hit                                       # still this rep at the top
    mid = plank(); mid[13, :2] = (0.30, 0.62); mid[15, :2] = (0.36, 0.74)            # ~102 deg: descending, not deep yet
    _feed(pm, mid, t0=3.0, thr=J2_THR)
    assert J2_THR['depth_elbow_max_deg'] < pm.form.elbow < J2_THR['lockout_min_deg'] - 10
    assert not pm.depth_hit                                                             # the next descent started


@pytest.mark.parametrize('valid, reasons, want', [
    (True, [], ('GOOD REP +1', None)),
    (False, ['hips_sag', 'too_shallow'], ('NO REP', 'HIPS SAGGING')),
    (False, ['too_shallow'], ('NO REP', 'GO LOWER')),
    (False, ['knees_down'], ('NO REP', 'KNEES DOWN')),
    (False, ['hips_pike'], ('NO REP', 'HIPS TOO HIGH')),
    (False, ['no_lockout'], ('NO REP', 'LOCK OUT AT THE TOP')),
    (False, ['classifier:pushups - shallow'], ('NO REP', 'GO LOWER')),
    (False, ['classifier:something new'], ('NO REP', 'FIX YOUR FORM')),
    (False, [], ('NO REP', None)),
])
def test_verdict_text(valid, reasons, want):
    assert verdict_lines(valid, reasons) == want


def test_state_counts_only_valid_reps_and_flashes_each():
    st = MirrorState()
    st.rep(True, [], now=1.0); st.rep(False, ['too_fast'], now=2.0); st.rep(True, [], now=3.0, counts=False)
    assert st.count == 1 and st.verdict_ok is True and st.verdict_t == 3.0


def test_render_with_mascot_verdict_cue_and_idle_card():
    pm = PushupMirror()
    st = MirrorState(time_left_s=75.0)
    st.rep(True, [], now=0.5); st.say('Go lower - chest down.', now=0.5); st.speaking = True
    img = _feed(pm, plank())
    img = pm.render(np.full((720, 1280, 3), 100, np.uint8), plank(), None, st, now=0.6, seq=99)
    assert img.shape == (1280, 720, 3) and img.dtype == np.uint8
    idle = pm.render(None, None, None, MirrorState(), now=3.0)
    assert idle.shape == (1280, 720, 3) and idle.dtype == np.uint8
    assert idle[pmod.IDLE_FEET - 40, 40].tolist() != [0, 0, 0]


def test_render_rejects_a_bad_frame_and_keeps_input_untouched():
    pm = PushupMirror(mascot=False)
    with pytest.raises(ValueError): pm.render(np.zeros((10, 10), np.uint8), None)
    rgb = np.full((720, 1280, 3), 100, np.uint8); before = rgb.copy()
    pm.render(rgb, plank(), None, MirrorState(), now=0.0)
    assert np.array_equal(rgb, before)


def test_portrait_frame_and_resolution_change():
    pm = PushupMirror(mascot=False)
    assert pm.render(np.full((1280, 720, 3), 80, np.uint8), None, now=0.0).shape == (1280, 720, 3)
    assert pm.render(np.full((480, 640, 3), 80, np.uint8), plank(), now=0.1).shape == (1280, 720, 3)


# ---------------------------------------------------------------------------------------------------- the stable camera
SRC = (274, 486, 3)                                               # the live bridge's caller picture (content crop)


def _run_camera(pm, lm_at, t0, t1, fps=15, pose_every=1.5):
    """Render frames t0..t1 at fps; a new pose (lm_at(t)) every pose_every-th frame like the 10 fps feed. Returns
    [(t, view)]."""
    rgb = np.full(SRC, 110, np.uint8); out = []; k = 0
    n = int(round((t1 - t0) * fps))
    for i in range(n):
        t = t0 + i / fps
        if i % pose_every < 1: k += 1; lm = lm_at(t)
        pm.render(rgb, lm, DEFAULT_THRESHOLDS, MirrorState(), now=t, seq=k + int(t0 * 1000))
        out.append((t, pm.framer.view))
    return out


def _spread(views):
    v = np.array([x for _, x in views])
    return float(np.ptp(v[:, 0])), float(np.ptp(v[:, 1])), float(np.ptp(np.log(v[:, 2])))


def test_jittery_landmarks_do_not_move_the_camera():
    rng = np.random.default_rng(3)
    def lm_at(t):
        lm = plank(); lm[:, :2] += rng.normal(0, 0.012, (33, 2)).astype(np.float32); return lm
    pm = PushupMirror(mascot=False, follow=True)
    views = _run_camera(pm, lm_at, 0.0, 12.0)
    first = views[0][1]
    assert first == (SRC[1] / 2, SRC[0] / 2, float(SRC[1]))       # before LOCK_SAMPLES poses: the whole picture
    settled = [(t, v) for t, v in views if t >= 3.0]
    dx, dy, dz = _spread(settled)
    assert dx < 0.5 and dy < 0.5 and dz < 0.002                   # still (the old EMA crop moved on 244 of 250 frames)
    assert settled[0][1][2] < SRC[1] * 0.95                           # and it did frame the person (not the whole picture)


def test_no_zoom_pulse_across_reps():
    def lm_at(t):                                                 # push-ups: the upper body drops 0.10 and comes back, 1.6 s a rep
        lm = plank(); d = 0.10 * (0.5 - 0.5 * np.cos(2 * np.pi * t / 1.6))
        for i in (0, 7, 8, 11, 12, 13, 14): lm[i, 1] += d
        lm[23, 1] += d / 2; lm[24, 1] += d / 2
        return lm
    pm = PushupMirror(mascot=False, follow=True)
    views = _run_camera(pm, lm_at, 0.0, 15.0)
    dx, dy, dz = _spread([(t, v) for t, v in views if t >= 4.0])
    assert dx < 0.5 and dy < 0.5 and dz < 0.002


def test_no_pose_holds_the_framing():
    pm = PushupMirror(mascot=False, follow=True)
    views = _run_camera(pm, lambda t: plank(), 0.0, 4.0)
    held = views[-1][1]
    later = _run_camera(pm, lambda t: None, 4.0, 10.0)
    assert all(v == held for _, v in later)                       # never snaps to the full picture and back
    assert held[2] < SRC[1] * 0.95


def test_camera_follows_a_person_who_moves_away_with_an_eased_move():
    pm = PushupMirror(mascot=False, follow=True)
    _run_camera(pm, lambda t: plank(), 0.0, 4.0)
    before = pm.framer.view
    def moved(t):
        lm = plank(); lm[:, 0] -= 0.22; return lm                 # crawled toward the left edge
    views = _run_camera(pm, moved, 4.0, 10.0)
    after = views[-1][1]
    assert after[0] < before[0] - 20                              # the camera followed
    xs = [v[0] for _, v in views]
    steps = np.diff(xs)
    assert np.all(steps <= 1e-9)                                  # one monotonic move, no overshoot or wobble
    assert np.max(np.abs(steps)) < 0.25 * abs(after[0] - before[0])   # eased over many frames, not a cut
    t_moving = [t for (t, v), s in zip(views[1:], steps) if s < -1e-9]
    assert t_moving[-1] - t_moving[0] <= pmod.EASE_S + 0.1


def test_framer_crop_never_zooms_past_s_max():
    f = Framer(486, 274, follow=True)
    lm = plank(); lm[:, :2] = 0.5 + (lm[:, :2] - 0.5) * 0.15        # a tiny person
    for k in range(40): f.add(lm, 0.1 * k)
    f.update(10.0)
    M, y1 = f.matrix()
    assert M[0, 0] <= pmod.S_MAX + 1e-9 and pmod.VID_Y0 + pmod.PANEL_MIN <= y1 <= pmod.VID_Y0 + pmod.PANEL_MAX


def test_zoom_is_set_once_and_never_zooms_in_again():
    """The live complaint (it keeps re-zooming): the first framing is a cut, later the zoom never shrinks."""
    pm = PushupMirror(mascot=False, follow=True)
    views = _run_camera(pm, lambda t: plank(), 0.0, 3.0)
    zs = [v[2] for t, v in views if t >= 0.5]
    assert np.ptp(zs) == 0.0 and zs[0] < SRC[1] * 0.95             # framed within half a second, never eased in
    def closer(t):                                                # walks up to the phone: a smaller region would zoom in
        lm = plank(); lm[:, :2] = 0.5 + (lm[:, :2] - 0.5) * 0.6; return lm
    later = _run_camera(pm, closer, 3.0, 10.0)
    assert all(v[2] >= zs[0] - 1e-9 for _, v in later)


def test_live_default_shows_the_whole_picture_and_never_moves():
    """The live ask: no zoom, no pan, just what the caller's camera records."""
    for src in (SRC, (720, 486, 3)):
        pm = PushupMirror(mascot=False); rgb = np.full(src, 110, np.uint8)
        views = set()
        for k in range(60):
            lm = plank(); lm[:, 0] -= 0.004 * k                      # the person moves around
            pm.render(rgb, lm, DEFAULT_THRESHOLDS, MirrorState(), now=0.066 * k, seq=k); views.add(pm.framer.view)
        assert len(views) == 1
        M, y1 = pm.framer.matrix()
        h, w = src[:2]
        corners = M @ np.array([[0, 0, 1], [w, h, 1]], float).T        # the whole source lands inside the panel
        assert corners[0].min() >= -1e-6 and corners[0].max() <= pmod.PANEL_W + 1e-6
        assert corners[1].min() >= pmod.VID_Y0 - 1e-6 and corners[1].max() <= y1 + 1e-6


def test_render_is_fast_enough_for_the_live_loop():
    import time
    pm = PushupMirror()
    rgb = (np.random.default_rng(1).integers(0, 255, SRC)).astype(np.uint8)
    st = MirrorState(time_left_s=60.0); st.say('Go lower', now=0.0); st.speaking = True
    for k in range(10): pm.render(rgb, plank(), None, st, now=0.1 * k, seq=k)
    t0 = time.perf_counter()
    for k in range(30): pm.render(rgb, plank(), None, st, now=1.0 + 0.066 * k, seq=10 + k // 2)
    ms = (time.perf_counter() - t0) / 30 * 1000
    assert ms < 25.0, ms                                          # ~4 ms on a laptop core; the EC2 budget is 12 ms
