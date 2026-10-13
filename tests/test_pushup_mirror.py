import numpy as np
import pytest

from challenge.judge.gates import DEFAULT_THRESHOLDS
from facetime import pushup_mirror as pmod
from facetime.pushup_mirror import (GOOD, BAD, MirrorState, PushupMirror, StatusFilter, ST_BACK, ST_GOOD, ST_NONE, ST_PHONE,
                                    ST_PLANK, ST_SIDE, camera_status, content_box, is_portrait_strip, verdict_lines)

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
    """Plank seen from the head: shoulders wide, the torso foreshortened."""
    lm = plank(right_vis=0.9)
    lm[11, :2] = (0.40, 0.40); lm[12, :2] = (0.60, 0.40); lm[23, :2] = (0.46, 0.50); lm[24, :2] = (0.54, 0.50)
    return lm


def test_status_good_plank_side_view():
    assert camera_status(plank(), ASPECT) == ST_GOOD


def test_status_frontal_is_turn_sideways():
    assert camera_status(frontal(), ASPECT) == ST_SIDE


def test_status_missing_ankles_is_step_back():
    assert camera_status(plank(ankle_vis=0.1), ASPECT) == ST_BACK


def test_status_out_of_frame_ankle_is_step_back():
    lm = plank(); lm[27, 0] = 1.04                                # the judge's conf is 0 outside the image
    assert camera_status(lm, ASPECT) == ST_BACK


def test_status_standing_is_get_in_plank():
    lm = plank()
    for i, (x, y) in {11: (0.5, 0.3), 23: (0.5, 0.55), 25: (0.5, 0.72), 27: (0.5, 0.9), 13: (0.5, 0.42), 15: (0.5, 0.52)}.items():
        lm[i, :2] = (x, y); lm[i + 1, :2] = (x + 0.004, y)
    assert camera_status(lm, ASPECT) == ST_PLANK


def test_status_no_pose_and_pillarbox():
    assert camera_status(None, ASPECT) == ST_NONE
    assert camera_status(None, ASPECT, portrait=True) == ST_PHONE
    assert camera_status(plank(ankle_vis=0.1), ASPECT, portrait=True) == ST_PHONE
    assert camera_status(plank(), ASPECT, portrait=True) == ST_GOOD      # whole body in a plank: the strip is not the problem


def test_pillarboxed_frame_is_a_portrait_strip():
    rgb = np.zeros((720, 1280, 3), np.uint8); rgb[:, 438:842] = 120
    box = content_box(rgb)
    assert abs(box[0] - 438) <= 4 and abs(box[2] - 842) <= 4 and box[1] == 0 and box[3] == 720
    assert is_portrait_strip(box)
    assert not is_portrait_strip(content_box(np.full((720, 1280, 3), 90, np.uint8)))


def test_renderer_phone_sideways_on_pillarboxed_bridge_frame():
    pm = PushupMirror(mascot=False)
    rgb = np.zeros((720, 1280, 3), np.uint8); rgb[:, 438:842] = 120
    img = pm.render(rgb, None, None, MirrorState(), now=0.0)
    assert pm.status.shown == ST_PHONE and img.shape == (1280, 720, 3)


def test_status_filter_hysteresis():
    f = StatusFilter()
    assert f.update(ST_BACK) == ST_BACK                           # the first status shows at once
    assert f.update(ST_GOOD) == ST_BACK and f.update(ST_GOOD) == ST_BACK and f.update(ST_GOOD) == ST_BACK
    assert f.update(ST_GOOD) == ST_GOOD                           # four in a row for green
    assert f.update(ST_SIDE) == ST_GOOD and f.update(ST_GOOD) == ST_GOOD   # a one-frame blip does not switch
    for _ in range(2): assert f.update(ST_SIDE) == ST_GOOD
    assert f.update(ST_SIDE) == ST_SIDE


def _feed(pm, lm, n=5, t0=0.0):
    rgb = np.full((720, 1280, 3), 100, np.uint8)
    img = None
    for k in range(n):
        img = pm.render(rgb, lm.copy(), DEFAULT_THRESHOLDS, MirrorState(), now=t0 + 0.1 * k, seq=k + int(t0 * 100))
    return img


def test_good_plank_is_green_and_sagging_hips_are_red():
    pm = PushupMirror(mascot=False)
    img = _feed(pm, plank())
    assert img.shape == (1280, 720, 3) and img.dtype == np.uint8
    body, legs, arm, hip_lab, knee_lab = pm._colors()
    assert pm.status.shown == ST_GOOD and body == GOOD and legs == GOOD and hip_lab is None
    _feed(pm, plank(hip_y=0.61), t0=1.0)
    body, legs, arm, hip_lab, knee_lab = pm._colors()
    assert body == BAD and hip_lab == 'HIPS SAGGING'
    assert pm.form.dev > DEFAULT_THRESHOLDS['hip_line_max_dev_deg']


def test_colours_follow_the_live_thresholds():
    pm = PushupMirror(mascot=False)
    thr = dict(DEFAULT_THRESHOLDS, hip_line_max_dev_deg=60.0)
    rgb = np.full((720, 1280, 3), 100, np.uint8)
    for k in range(5): pm.render(rgb, plank(hip_y=0.61), thr, MirrorState(), now=0.1 * k, seq=k)
    assert pm._colors()[0] == GOOD


def test_no_form_colours_until_the_camera_angle_is_good():
    pm = PushupMirror(mascot=False)
    lm = frontal(); lm[23, 1] = 0.7
    _feed(pm, lm)
    assert pm.status.shown == ST_SIDE and pm._colors()[3] is None


def test_depth_latch_per_rep():
    pm = PushupMirror(mascot=False)
    lm = plank(); _feed(pm, lm)
    assert not pm.depth_hit
    bent = plank(); bent[13, :2] = (0.30, 0.62); bent[15, :2] = (0.36, 0.70)         # elbow well under 100 deg
    _feed(pm, bent, t0=1.0)
    assert pm.form.elbow <= DEFAULT_THRESHOLDS['depth_elbow_max_deg'] and pm.depth_hit
    _feed(pm, lm, t0=2.0); assert pm.depth_hit                                       # still this rep at the top
    mid = plank(); mid[13, :2] = (0.30, 0.62); mid[15, :2] = (0.36, 0.74)            # ~102 deg: descending, not deep yet
    _feed(pm, mid, t0=3.0)
    assert DEFAULT_THRESHOLDS['depth_elbow_max_deg'] < pm.form.elbow < DEFAULT_THRESHOLDS['lockout_min_deg'] - 10
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
