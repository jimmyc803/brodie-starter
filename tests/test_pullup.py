import numpy as np

from facetime.pullup import PullupCounter, compose_pullup, FAULT_CHIN, FAULT_HANG, GREEN, RED


def body(h, on_bar=True):
    """A synthetic pose hanging from a bar at y 0.19 (knuckles): h = 0 dead hang, 1 = shoulders up near the bar."""
    lm = np.zeros((33, 4), np.float32); lm[:, 3] = 0.99
    sy = 0.45 - 0.23 * h
    for side, sx, wx, out in ((0, 0.45, 0.40, -1), (1, 0.55, 0.60, 1)):
        sh, wr = np.array([sx, sy]), np.array([wx, 0.20 if on_bar else 0.70])
        el = (sh + wr) / 2 + np.array([out * 0.09 * np.sin(np.pi * min(h, 1.0) * 0.5), 0])
        lm[11 + side, :2], lm[13 + side, :2], lm[15 + side, :2] = sh, el, wr
        lm[17 + side, :2] = lm[19 + side, :2] = wr - [0, 0.01]
    lm[0, :2] = [0.5, sy - 0.08]; lm[9, :2] = [0.49, sy - 0.06]; lm[10, :2] = [0.51, sy - 0.06]
    lm[23, :2] = [0.46, sy + 0.25]; lm[24, :2] = [0.54, sy + 0.25]
    return lm


def run(heights, on_bar=True):
    pc = PullupCounter(target=5); events = []; states = []
    for i, h in enumerate(heights):
        st = pc.update(body(h, on_bar), i / 10)
        events += st.events; states.append((st.cleared, st.progress))
    return pc.st, events, states


def reps(n, top=1.0, bottom=0.0, steps=8):
    up = list(np.linspace(bottom, top, steps)); down = list(np.linspace(top, bottom, steps))
    return [0.0] * 5 + (up + [top] * 3 + down + [bottom] * 4) * n


def test_full_reps_count_once_each():
    st, events, states = run(reps(5))
    assert st.count == 5
    assert [e for e in events if e[0] == 'rep'] == [('rep', i) for i in range(1, 6)]
    assert not [e for e in events if e[0] == 'fault']
    assert any(c for c, _ in states) and max(p for _, p in states) >= 1.0


def test_half_reps_do_not_count_and_say_chin_over_the_bar():
    st, events, _ = run(reps(3, top=0.6))
    assert st.count == 0
    assert ('fault', FAULT_CHIN) in events and ('cue', 'Chin over the bar') in events


def test_no_dead_hang_between_reps_is_not_a_rep():
    hs = [0.0] * 5 + list(np.linspace(0, 1, 8)) + [1.0] * 3 + list(np.linspace(1, 0.5, 5)) + list(np.linspace(0.5, 1, 5)) + [1.0] * 3
    st, events, _ = run(hs)
    assert st.count == 1
    assert ('fault', FAULT_HANG) in events


def test_hands_down_is_off_the_bar():
    st, events, _ = run([0.0] * 10, on_bar=False)
    assert not st.on_bar and st.count == 0 and not events


def test_overlay_turns_green_on_clear_and_red_on_a_no_rep():
    rgb = np.full((720, 1280, 3), 90, np.uint8)
    pc = PullupCounter(target=5); st = None
    for i, h in enumerate(reps(1)[:16]):
        st = pc.update(body(h), i / 10)
        if st.cleared: break
    assert st is not None and st.cleared
    img = compose_pullup(rgb, body(1.0), st, now=st.clear_t + 0.1)
    assert img.shape == (1280, 720, 3)
    assert (np.abs(img.astype(int) - GREEN).sum(axis=2) < 30).sum() > 2000          # the green bar, skeleton and badge
    pc = PullupCounter(target=5); fault = None
    for i, h in enumerate(reps(1, top=0.6)):
        st = pc.update(body(h), i / 10)
        if st.events and st.events[0][0] == 'fault': fault = st; break
    assert fault is not None
    img = compose_pullup(rgb, body(0.4), fault, now=fault.fault_t + 0.1)
    assert (np.abs(img.astype(int) - RED).sum(axis=2) < 30).sum() > 2000
