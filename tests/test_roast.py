from facetime.roast import ROAST_LINES, ROAST_FAULT, roast_for, close_line


def test_every_roast_line_is_short_and_bank_safe():
    for line in ROAST_LINES:
        assert '—' not in line and '–' not in line
        assert len(line.split()) <= 9, line


def test_roast_matches_the_fault_and_rotates():
    assert roast_for('pull ups - chin over the bar', 0) != roast_for('pull ups - chin over the bar', 1)
    assert roast_for('squats - shallow') in dict(ROAST_FAULT)['shallow']
    assert roast_for('something new') in ROAST_LINES and roast_for(None) in ROAST_LINES
    assert close_line(4) in ROAST_LINES


def test_roast_lines_are_in_the_cue_vocabulary():
    from facetime.cues_tts import vocabulary
    assert set(ROAST_LINES) <= set(vocabulary())


def test_roast_handlers_space_out_mid_set_roasts():
    import importlib.util, os
    spec = importlib.util.spec_from_file_location('roast_h', os.path.join(os.path.dirname(__file__), '..', 'starter', 'examples', 'roast', 'handlers.py'))
    h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
    said, asked = [], []
    say = lambda text, intent='other': said.append(text); ask = asked.append
    h.on_event({'type': 'session', 'state': 'wait'}, say, ask)
    h.on_event({'type': 'fault', 'label': 'squats - shallow'}, say, ask)
    h.on_event({'type': 'fault', 'label': 'squats - shallow'}, say, ask)      # inside the gap: no second roast
    h.on_event({'type': 'session', 'state': 'rest'}, say, ask)
    assert len(said) == 2 and all(s in ROAST_LINES for s in said) and len(asked) == 1


def test_letterbox_keeps_a_landscape_body_whole_and_the_skeleton_on_it():
    import numpy as np
    from facetime import mirror
    rgb = np.zeros((720, 1280, 3), np.uint8); rgb[300:420, 100:1180] = 255           # a long white "body" across the frame
    lm = np.zeros((33, 4), np.float32); lm[:, 3] = 1.0; lm[:, 0] = [0.1 + 0.8 * k / 32 for k in range(33)]; lm[:, 1] = 0.5
    old = mirror.LETTERBOX; mirror.LETTERBOX = True
    try: img, box = mirror.crop_portrait(rgb, lm)
    finally: mirror.LETTERBOX = old
    assert img.shape == (mirror.H, mirror.W, 3)
    pts = mirror._map(lm, box, 1280, 720)
    assert min(p[0] for p in pts) >= 0 and max(p[0] for p in pts) < mirror.W              # head to feet all in the view
    for x, y, _ in pts: assert img[y, x].mean() > 200                                       # every joint lands on the body
