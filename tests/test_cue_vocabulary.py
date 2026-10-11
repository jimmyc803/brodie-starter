"""The prerecorded vocabulary must cover every assignable exercise."""
import json

import numpy as np

from facetime import cues_tts
from facetime.audio_out import CueBank
from shared.scoring import RULES, plan_name


def test_assigned_exercises_have_every_session_announcement():
    vocabulary = set(cues_tts.vocabulary())
    for key in RULES['exercises']:
        name = plan_name(key)
        assert name in cues_tts.exercise_names()
        for prefix in ("Let's do ", 'Moving on to ', 'Looks like '):
            assert prefix + name in vocabulary


def test_missing_curl_clips_are_generated_and_playable(tmp_path, monkeypatch):
    # Stub only the paid provider; exercise the real renderer, manifest and player.
    class Client:
        pass

    monkeypatch.setattr(cues_tts, 'gemini_client', lambda: Client())
    monkeypatch.setattr(cues_tts, 'gemini_pick_model', lambda client, want: 'test-tts')
    rendered = []

    def render(client, model, voice, text):
        rendered.append(text)
        pcm = np.full(2400, 2000, dtype=np.int16).tobytes()
        return pcm, dict(text_tokens=1, audio_tokens=1, total_tokens=2)

    monkeypatch.setattr(cues_tts, 'gemini_render_one', render)
    curl_phrases = {prefix + 'bicep curls' for prefix in ("Let's do ", 'Moving on to ', 'Looks like ')}
    # Existing bank is complete except for the newly added curl phrases.
    existing = np.full(2400, 2000, dtype=np.int16).tobytes()
    (tmp_path / 'existing.pcm').write_bytes(existing)
    manifest = {text: {'file': 'existing.pcm', 'duration_s': .1}
                for text in cues_tts.vocabulary() if text not in curl_phrases}
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    assert not cues_tts.bank_complete(str(tmp_path))
    monkeypatch.setattr('sys.argv', ['cues_tts', '--backend', 'gemini', '--workers', '1', '--out-dir', str(tmp_path)])
    cues_tts.main()
    assert set(rendered) == curl_phrases
    assert cues_tts.bank_complete(str(tmp_path))
    bank = CueBank(str(tmp_path))
    for text in curl_phrases:
        pcm = bank.get(text)
        assert pcm is not None and np.any(pcm)
    cues_tts.main()
    assert len(rendered) == 3  # Cached clips are retained on repeat runs.
