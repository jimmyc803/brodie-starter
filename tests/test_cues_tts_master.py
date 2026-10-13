"""Mastered banks (cues_tts --bank v2): trim + fades + loudness normalisation, the transcript check that catches a spoken
stage direction, and the retry/backoff and per-string failure handling of a render run."""
import json

import numpy as np
import pytest

from facetime import cues_tts
from facetime.audio_out import CueBank, normalize_level

RATE = cues_tts.SAMPLE_RATE


def speech(amp, seconds=0.5, lead=0.3, tail=0.4):
    t = np.arange(int(seconds * RATE)) / RATE
    tone = (amp * np.sin(2 * np.pi * 220 * t)).astype(np.int16)
    return np.concatenate([np.zeros(int(lead * RATE), np.int16), tone, np.zeros(int(tail * RATE), np.int16)]).tobytes()


def test_master_trims_fades_and_levels_quiet_and_loud_clips_alike():
    quiet, loud = cues_tts.master(speech(800), 'Nice work'), cues_tts.master(speech(20000), 'Looking strong')
    for out in (quiet, loud):
        x = np.frombuffer(out, np.int16)
        assert len(x) / RATE < 0.5 + cues_tts.HEAD_S + cues_tts.TAIL_S + 0.01      # leading/trailing silence gone
        assert abs(int(x[0])) < 50 and abs(int(x[-1])) < 50                         # faded ends: no click
        assert abs(cues_tts.clip_stats(out)['rms_dbfs'] - (-18.0)) < 0.6           # same level whatever the take
        assert np.array_equal(normalize_level(x), x)                                # the player's own pass is a no-op


def test_count_words_keep_no_pre_roll():
    out = np.frombuffer(cues_tts.master(speech(8000), 'Seven'), np.int16)
    assert len(out) / RATE < 0.5 + 0.030 + 0.005


@pytest.mark.parametrize('text, heard, ok', [
    ('Lower! Get that chest down.', 'Enthusiastic. Lower! Get that chest down.', False),
    ('Nice work', 'Energetic, confident gym coach, quick pace. Nice work!', False),
    ('Nice work', 'Nice work, nice work, great', False),
    ('Freeze!', '', False),
    ("Not your turn! Text this number JOIN, then QUEUE. I'll text you when you're up.",
     "Not your turn? Text this number join, then Q. I'll text you when you're up.", True),
    ('21', 'Twenty-one.', True),
    ("That's 5", "That's five.", True),
    ('Hand up, and hold it!', 'Hand up and hold it.', True),
])
def test_transcript_check(text, heard, ok):
    assert cues_tts.transcript_ok(text, heard) is ok


def test_backoff_grows_and_honours_retry_delay():
    assert cues_tts.backoff_s(0) < cues_tts.backoff_s(4)
    assert cues_tts.backoff_s(10) <= 60 * 1.25
    assert cues_tts.backoff_s(0, Exception("429 RESOURCE_EXHAUSTED {'retryDelay': '33s'}")) >= 34


def stub_provider(monkeypatch, tmp_path, vocab, render):
    class Client:
        pass
    monkeypatch.setattr(cues_tts, 'vocabulary', lambda: list(vocab))
    monkeypatch.setattr(cues_tts, 'gemini_client', lambda: Client())
    monkeypatch.setattr(cues_tts, 'gemini_pick_model', lambda client, want: want)
    monkeypatch.setattr(cues_tts, 'gemini_render_one', render)
    monkeypatch.setitem(cues_tts.BANKS, 'v2', dict(cues_tts.BANKS['v2'], out_dir=str(tmp_path)))


def test_bank_preset_renders_mastered_verified_clips_and_retakes_a_spoken_direction(tmp_path, monkeypatch):
    vocab = ['Nice work', 'Time!']
    calls = []

    def render(client, model, voice, text):
        calls.append((model, voice, text))
        return speech(3000), dict(text_tokens=1, audio_tokens=1, total_tokens=2)
    stub_provider(monkeypatch, tmp_path, vocab, render)
    heard = {'Nice work': ['Energetic coach. Nice work', 'Nice work!'], 'Time!': ['Time!']}
    monkeypatch.setattr(cues_tts, 'gemini_review', lambda client, pcm, text, model=None: dict(transcript=heard[text].pop(0), energy=8, clarity=9, naturalness=8, coach_fit=8))
    monkeypatch.setattr('sys.argv', ['cues_tts', '--bank', 'v2', '--workers', '1', '--takes', '1'])
    cues_tts.main()
    p = cues_tts.BANKS['v2']
    assert {c[:2] for c in calls} == {(p['model'], p['voice'])}
    assert [c[2] for c in calls] == [p['style'] + 'Nice work'] * 2 + [p['style'] + 'Time!']   # one retake
    m = json.loads((tmp_path / 'manifest.json').read_text())
    assert set(m) == set(vocab) and all(v['mastered'] and v['voice'] == p['voice'] for v in m.values())
    bank = CueBank(str(tmp_path))
    assert all(bank.get(t) is not None for t in vocab)


def test_a_failing_string_does_not_lose_the_others_and_exits_nonzero(tmp_path, monkeypatch):
    vocab = ['Nice work', 'Time!', 'Good pace']

    def render(client, model, voice, text):
        if text.endswith('Time!'):
            raise RuntimeError('500 INTERNAL')
        return speech(3000), dict(text_tokens=1, audio_tokens=1, total_tokens=2)
    stub_provider(monkeypatch, tmp_path, vocab, render)
    monkeypatch.setattr(cues_tts, 'backoff_s', lambda attempt, err=None: 0)
    monkeypatch.setattr('sys.argv', ['cues_tts', '--bank', 'v2', '--workers', '2', '--no-verify'])
    with pytest.raises(SystemExit, match='1 strings failed'):
        cues_tts.main()
    assert set(json.loads((tmp_path / 'manifest.json').read_text())) == {'Nice work', 'Good pace'}


def test_default_bank_is_v2_only_while_it_covers_the_most(tmp_path, monkeypatch):
    from facetime import audio_out
    vocab = ['Nice work', 'Time!']
    monkeypatch.setattr(cues_tts, 'vocabulary', lambda: list(vocab))
    monkeypatch.delenv('CUE_AUDIO_DIR', raising=False)
    v2, old = tmp_path / 'v2', tmp_path / 'old'
    for d, texts in ((v2, vocab), (old, vocab)):
        d.mkdir(); (d / 'a.pcm').write_bytes(b'\0\0' * 480)
        (d / 'manifest.json').write_text(json.dumps({t: {'file': 'a.pcm', 'duration_s': .02} for t in texts}))
    monkeypatch.setattr(audio_out, 'DEFAULT_BANKS', (str(v2), str(old)))
    assert audio_out.default_cues_dir() == str(v2)                       # equally complete: v2 wins the tie
    (v2 / 'manifest.json').write_text(json.dumps({'Nice work': {'file': 'a.pcm', 'duration_s': .02}}))
    assert audio_out.default_cues_dir() == str(old)                      # an incomplete v2 never displaces a fuller bank
    monkeypatch.setenv('CUE_AUDIO_DIR', str(v2))
    assert audio_out.default_cues_dir() == str(v2)                       # the env var still picks any bank


def test_best_of_n_keeps_the_take_the_listener_rates_highest(tmp_path, monkeypatch):
    amps = iter([1000, 6000, 3000])                     # three takes, told apart by their (pre-normalisation) level

    def render(client, model, voice, text):
        return speech(next(amps)), dict(text_tokens=1, audio_tokens=1, total_tokens=2)
    stub_provider(monkeypatch, tmp_path, ['Nice work'], render)
    reviews = iter([dict(transcript='Nice work', energy=5, clarity=9, naturalness=8, coach_fit=6),
                    dict(transcript='Enthusiastic. Nice work', energy=10, clarity=10, naturalness=10, coach_fit=10),   # leak: never kept
                    dict(transcript='Nice work', energy=9, clarity=9, naturalness=9, coach_fit=9)])
    kept = []
    monkeypatch.setattr(cues_tts, 'gemini_review', lambda client, pcm, text, model=None: kept.append(pcm) or next(reviews))
    monkeypatch.setattr('sys.argv', ['cues_tts', '--bank', 'v2', '--workers', '1', '--takes', '2'])
    cues_tts.main()
    m = json.loads((tmp_path / 'manifest.json').read_text())
    assert m['Nice work']['review_score'] == 36
    assert (tmp_path / m['Nice work']['file']).read_bytes() == kept[2]


@pytest.mark.parametrize('text, heard, ok', [
    ("Let's do pushups", "Let's do push-ups", True),
    ('Moving on to armcrosschest left', 'Moving on to arm cross chest left', True),
    ("Let's do lunges", "Alright, let's do lunges.", False),
    ('Push knees out', 'Energetic, confident gym coach, quick pace. Push knees out.', False),
])
def test_transcript_check_compounds_and_fillers(text, heard, ok):
    assert cues_tts.transcript_ok(text, heard) is ok


def test_a_string_that_keeps_reading_the_direction_falls_back_to_a_plainer_one(tmp_path, monkeypatch):
    seen = []

    def render(client, model, voice, text):
        seen.append(text)
        return speech(3000), dict(text_tokens=1, audio_tokens=1, total_tokens=2)
    stub_provider(monkeypatch, tmp_path, ['Push knees out'], render)
    p = cues_tts.BANKS['v2']
    leak = lambda prompt: prompt.startswith(p['style'])   # the main direction is always spoken for this string
    monkeypatch.setattr(cues_tts, 'gemini_review', lambda client, pcm, text, model=None: dict(
        transcript=('Energetic coach. ' if leak(seen[-1]) else '') + text, energy=8, clarity=9, naturalness=8, coach_fit=8))
    monkeypatch.setattr('sys.argv', ['cues_tts', '--bank', 'v2', '--workers', '1', '--takes', '1'])
    cues_tts.main()
    first_fallback = p['fallback_styles'][0]
    assert seen == [p['style'] + 'Push knees out'] * cues_tts.VERIFY_TRIES + [first_fallback + 'Push knees out']
    assert json.loads((tmp_path / 'manifest.json').read_text())['Push knees out']['style'] == first_fallback
