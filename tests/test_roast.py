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
