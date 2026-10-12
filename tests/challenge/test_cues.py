import json, os

from challenge.judge.cues import CUES, REASON_CUE, cue_for_reason, text_for_reason
from facetime import CUES_DIR_GEMINI
from facetime.cues_tts import vocabulary

KEYS = """knees_down too_shallow no_lockout not_in_frame hips multiple_people challenge_tap_left challenge_tap_right
challenge_lift_right challenge_passed challenge_failed not_your_turn at_cap not_signed_up competition_over thirty_left
time_up check_texts power_hour hang_up welcome""".split()


def test_keys_and_exact_phrases():
    assert set(CUES) == set(KEYS)
    assert CUES['competition_over'] == 'The competition is over — thanks for playing.'
    assert CUES['time_up'] == 'Time!'
    assert CUES['hang_up'] == "Time's up — you can hang up now."
    assert CUES['welcome'] == "You're on — side view, whole body in frame. Go!"


def test_every_phrase_in_rendered_vocabulary():
    assert set(CUES.values()) <= set(vocabulary())


def test_reason_mapping():
    assert all(v is None or v in CUES for v in REASON_CUE.values())
    assert cue_for_reason('hips_sag') == cue_for_reason('hips_pike') == 'hips'
    assert cue_for_reason('not_horizontal') == 'not_in_frame'
    assert cue_for_reason('too_fast') is None and text_for_reason('too_fast') is None
    assert cue_for_reason('classifier:pushups - shallow') == 'too_shallow'
    assert cue_for_reason('classifier:unknown') is None


def test_audio_bank_has_every_phrase_when_present():
    mf = os.path.join(CUES_DIR_GEMINI, 'manifest.json')
    if not os.path.exists(mf):
        return
    m = json.load(open(mf))
    missing = [t for t in CUES.values() if t not in m or not os.path.exists(os.path.join(CUES_DIR_GEMINI, m[t]['file']))]
    assert not missing, missing
