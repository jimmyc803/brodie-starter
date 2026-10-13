import json, os

from challenge.judge.cues import CUES, REASON_CUE, cue_for_reason, text_for_reason
from facetime.audio_out import default_cues_dir
from facetime.cues_tts import vocabulary

KEYS = """camera_off try_again knees_down too_shallow no_lockout not_in_frame hips multiple_people challenge_tap_left challenge_tap_right
challenge_lift_right challenge_lift_hold challenge_double_tap challenge_freeze challenge_go challenge_passed challenge_failed not_your_turn queued at_cap not_signed_up competition_over thirty_left
time_up check_texts power_hour hang_up welcome""".split()


def test_keys_and_exact_phrases():
    assert set(CUES) == set(KEYS)
    assert CUES['competition_over'] == "The challenge isn't open right now. Watch your texts!"
    assert CUES['time_up'] == 'Time!'
    assert CUES['hang_up'] == "That's a wrap! You can hang up now."
    assert CUES['welcome'] == "You're on! Upper body and knees in frame. Let's go!"
    assert CUES['not_your_turn'] == "Not your turn! Text this number JOIN, then QUEUE. I'll text you when you're up."
    assert CUES['queued'] == "Line's busy, but you're in line now! I'll text you when you're up."
    assert CUES['not_signed_up'] == "You're not signed up! Text this number JOIN and your name."


def test_pickup_lines_tell_the_caller_what_to_text():
    # The FaceTime line and the texting number are the same, so the reject lines say "this number", never a name to text.
    for key in ('not_your_turn', 'not_signed_up'):
        assert 'Text this number JOIN' in CUES[key]
    assert 'QUEUE' in CUES['not_your_turn'] and "I'll text you when you're up" in CUES['not_your_turn']
    assert "I'll text you when you're up" in CUES['queued']
    assert not any('Brodie' in CUES[k] for k in ('not_your_turn', 'not_signed_up', 'queued'))


def test_every_phrase_in_rendered_vocabulary():
    assert set(CUES.values()) <= set(vocabulary())


def test_reason_mapping():
    assert all(v is None or v in CUES for v in REASON_CUE.values())
    assert cue_for_reason('hips_sag') == cue_for_reason('hips_pike') == 'hips'
    assert cue_for_reason('not_horizontal') == 'not_in_frame'
    assert cue_for_reason('too_fast') is None and text_for_reason('too_fast') is None
    assert cue_for_reason('classifier:pushups - shallow') == 'too_shallow'
    assert cue_for_reason('classifier:pushups (on knees) - deep') == 'knees_down'
    assert cue_for_reason('classifier:pushups - hip sag') == 'hips'
    assert cue_for_reason('classifier:pushups - elevated hips') == 'hips'
    assert cue_for_reason('classifier:unknown') is None


def test_audio_bank_has_every_phrase_when_present():
    bank = default_cues_dir()
    if not os.path.isdir(bank):
        return
    mf = os.path.join(bank, 'manifest.json')
    assert os.path.exists(mf), f'no manifest in {bank}'
    m = json.load(open(mf))
    missing = [t for t in CUES.values() if t not in m or not os.path.exists(os.path.join(bank, m[t]['file']))]
    assert not missing, missing
