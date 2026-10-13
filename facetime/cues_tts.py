"""Render the closed cue vocabulary to PCM with a TTS API and cache it.

Backends: --backend openai (gpt-4o-mini-tts, response_format pcm = 24 kHz s16 mono) writes data/cues_audio/;
--backend gemini (the current flash TTS model from client.models.list(), generate_content with
response_modalities=["AUDIO"], one prebuilt voice, audio comes back as a 24 kHz s16 mono WAV, resampled if ever not
24 kHz) writes data/cues_audio_gemini/. Each directory has its own manifest.json (text -> {file, duration_s, chars,
model, voice, backend}) so the two voices never mix; the player picks the bank by env CUE_AUDIO_DIR (default: the
gemini bank if it is complete, else the openai one). Clips are <sha1 of text>.pcm, exactly what the "coach-audio"
LiveKit track carries. Rendering is idempotent: clips already in the manifest with a file on disk are skipped.
Leading and trailing silence below -40 dBFS is trimmed, keeping 60 ms of tail so the end of a word is not clipped.
Gemini is billed per token (text in, audio out): the usage metadata totals are printed.

--bank v2 (the default voice, data/cues_audio_v2): Puck with a short coach stage direction, every take mastered (trim with
pre-roll, fades, RMS -18 dBFS / peak -1 dBFS), heard back by a Gemini listener (a take whose words do not match the text,
e.g. a spoken direction, is re-rendered) and the better of 2 matching takes kept. Voice/style/out dir also via env
CUE_TTS_VOICE / CUE_TTS_STYLE / CUE_TTS_OUT_DIR. One failing string never loses the rest: it is listed and the run exits 1.

Run:  .venv/bin/python -m facetime.cues_tts [--bank v2] [--backend openai|gemini] [--voice nova|Puck] [--style ...] [--out-dir ...]
      [--takes N] [--[no-]master] [--[no-]verify] [--model ...] [--dry-run]
"""
import argparse, hashlib, json, os, sys, time, concurrent.futures as cf
import numpy as np
from facetime import CUES_DIR, CUES_DIR_GEMINI, CUES_DIR_V2, SAMPLE_RATE
from rtcoach.coach import CUES, PRAISE, COUNT_WORDS
from rtcoach.exmap import LR2CLF
from shared.scoring import RULES, plan_name

MANIFEST = os.path.join(CUES_DIR, 'manifest.json')      # openai bank; the gemini bank has its own
SILENCE_DBFS = -40.0
TAIL_S = 0.060
COUNT_TRIM = (-45.0, 0.030)          # count words: do not clip a soft onset, keep only 30 ms of tail (immediacy)
COUNT_MAX = 100                      # spoken counts exist for 1..COUNT_MAX (competition calls count every valid rep aloud)

def count_words():
    return {w.capitalize() for w in COUNT_WORDS.values()} | {str(n) for n in range(21, COUNT_MAX + 1)}

def count_text(n):
    """The bank text of the spoken count n, as the demo Coach says it: "One".."Twenty", then digits ("21".."100").
    None outside 1..COUNT_MAX (no clip: stay silent)."""
    if not isinstance(n, int) or n < 1 or n > COUNT_MAX: return None
    return COUNT_WORDS[n].capitalize() if n in COUNT_WORDS else str(n)

def trim_params(text):
    return COUNT_TRIM if text in count_words() else (SILENCE_DBFS, TAIL_S)
USD_PER_MCHAR = {'tts-1': 15.0, 'tts-1-hd': 30.0, 'gpt-4o-mini-tts': 15.0}   # char-rate estimate; 4o-mini-tts is also ~$0.015/min
INSTRUCTIONS = ('You are an energetic, upbeat gym coach calling out short cues mid-set. '
                'Clear, punchy, confident, friendly. No trailing pause.')

ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()
TENS = {2: 'twenty', 3: 'thirty', 4: 'forty', 5: 'fifty', 6: 'sixty', 7: 'seventy', 8: 'eighty', 9: 'ninety'}
def number_word(n):
    """0..100 as words (Coach.COUNT_WORDS stops at twenty); digits above that."""
    if n <= 20: return ONES[n]
    if n >= 100: return 'one hundred' if n == 100 else str(n)
    t, o = divmod(n, 10)
    return TENS[t] + (' ' + ONES[o] if o else '')

def exercise_names():
    """Classifier names plus the canonical names used by assigned program days."""
    return sorted(set(LR2CLF) | {plan_name(key) for key in RULES['exercises']})

def vocabulary():
    """Every string the coach can say. Order is stable (sorted) so the manifest diff is readable."""
    v = set()
    v.update(c['cue'] for c in CUES.values() if c.get('cue'))
    v.update(PRAISE)
    v.update(w.capitalize() for w in COUNT_WORDS.values())
    v.update(str(n) for n in range(21, COUNT_MAX + 1))            # Coach says digits past twenty (competition counts to 100)
    v.update(f"That's {n}" for n in (5, 10, 15, 20, 25, 30))
    v.update(["Let's go", "That's it"])
    names = exercise_names()
    v.update(f"Let's do {ex}" for ex in names)
    # session script (facetime/session.py): plan mode, auto mode, tempo
    v.update(f"That's {number_word(n)}, nice work" for n in range(1, 31))
    v.update(f"Moving on to {ex}" for ex in names)
    v.update(f"Looks like {ex}" for ex in names)
    v.update(["Rest for a moment", "All done, great session", "Nice work", "Slow down", "Pick up the pace"])
    v.update(["Okay, moving on"])                                    # --gesture-next: the T-pose command (facetime/probe.py TPose)
    v.update(["Step back so I can see your whole body", "Great, I can see you", "I will wait here, step into view when you are ready"])   # facetime/visibility.py
    v.update(["Probe ready, raise both arms"])
    from facetime.roast import ROAST_LINES
    v.update(ROAST_LINES)                                            # roast mode (facetime/roast.py)
    v.update(["Chin over the bar", "Full hang at the bottom"])        # pull-ups (facetime/pullup.py)                      # latency probe (coach_agent --latency-probe)
    bad = [t for t in v if '\u2014' in t or '\u2013' in t]
    assert not bad, f'dashes in cue text: {bad}'
    from challenge.judge.cues import CUES as CHALLENGE_CUES
    v.update(CHALLENGE_CUES.values())                                # challenge mode (SPEC section 6): exact spec text, em dashes included
    return sorted(v)

def sha1(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()

def trim(pcm, rate=SAMPLE_RATE, dbfs=SILENCE_DBFS, tail_s=TAIL_S, head_s=0.0):
    """Trim leading/trailing samples below `dbfs`, keep `head_s` before the first and `tail_s` after the last loud sample."""
    x = np.frombuffer(pcm, np.int16)
    thr = 32767 * 10 ** (dbfs / 20)
    loud = np.flatnonzero(np.abs(x.astype(np.int32)) > thr)
    if len(loud) == 0:
        return x.tobytes()
    a = max(0, int(loud[0]) - int(head_s * rate)); b = min(len(x), int(loud[-1]) + 1 + int(tail_s * rate))
    return x[a:b].tobytes()

HEAD_S = 0.015                       # mastered banks: 15 ms of pre-roll so a soft consonant onset ("f", "h", "s") is not clipped
FADE_S = 0.004                       # 4 ms fade in/out: no click at the cut points

def master(pcm, text, rate=SAMPLE_RATE, normalize=True):
    """The mastering chain of a mastered bank: trim leading/trailing silence (count words keep no pre-roll, see trim_params),
    4 ms fades, then loudness-normalize to the player's target (facetime.audio_out.normalize_level: RMS -18 dBFS, peaks
    <= -1 dBFS) so every clip arrives at the same level and the player's own normalisation is a no-op."""
    db, tail = trim_params(text)
    head = 0.0 if text in count_words() else HEAD_S
    x = np.frombuffer(trim(pcm, rate, db, tail, head), np.int16).astype(np.float32)
    f = min(int(FADE_S * rate), len(x) // 2)
    if f > 0:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32); x[:f] *= ramp; x[-f:] *= ramp[::-1]
    y = np.round(x).astype(np.int16)
    if normalize:
        from facetime.audio_out import normalize_level
        y = normalize_level(y)
    return y.tobytes()

def clip_stats(pcm, rate=SAMPLE_RATE):
    """Loudness facts of a clip: duration, RMS and peak in dBFS, and the share of 20 ms frames that are speech (> -40 dBFS)."""
    x = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    if len(x) == 0:
        return dict(duration_s=0.0, rms_dbfs=-120.0, peak_dbfs=-120.0, active=0.0)
    n = len(x) // 480 * 480; fr = x[:n].reshape(-1, 480) if n else x[None, :]
    frms = np.sqrt((fr * fr).mean(1) + 1e-12)
    return dict(duration_s=round(len(x) / rate, 3), rms_dbfs=round(float(20 * np.log10(np.sqrt((x * x).mean()) + 1e-9)), 2),
                peak_dbfs=round(float(20 * np.log10(np.abs(x).max() + 1e-9)), 2), active=round(float((frms > 0.01).mean()), 3))

def load_manifest(cues_dir=CUES_DIR):
    mf = os.path.join(cues_dir, 'manifest.json')
    if os.path.exists(mf):
        return json.load(open(mf))
    return {}

def save_manifest(m, cues_dir=CUES_DIR):
    os.makedirs(cues_dir, exist_ok=True)
    mf = os.path.join(cues_dir, 'manifest.json'); tmp = mf + '.tmp'
    json.dump(m, open(tmp, 'w'), indent=1, sort_keys=True); os.replace(tmp, mf)

def bank_complete(cues_dir):
    """True when every vocabulary string has a clip on disk in that bank."""
    m = load_manifest(cues_dir)
    return all(t in m and os.path.exists(os.path.join(cues_dir, m[t]['file'])) for t in vocabulary())

# ---- named bank presets (cues_tts --bank NAME) ----
# v2 (2026-10-13): 6 voices (Puck, Fenrir, Orus, Sadachbia, Alnilam, Achird) x 4 lines were rated by Gemini listeners
# (gemini-3.8-flash x2 + gemini-3.1-pro: energy, clarity, naturalness, coach fit; plus listwise rankings in two presentation
# orders). Puck with this short direction ranked first overall (Borda 3.4/5) and is the quickest talker, which keeps the
# reject lines inside the 5 s gatekeeper window; on short cues it beat plain Puck (energy 7.3 vs 6.4, coach fit 7.9 vs 7.2) and
# gemini-2.5-pro-preview-tts (no better than plain). Longer directions were read aloud far more often, so keep it short.
V2_VOICE = 'Puck'
V2_STYLE = '(Energetic, confident gym coach, quick pace) '
BANKS = {'v2': dict(out_dir=CUES_DIR_V2, voice=V2_VOICE, style=V2_STYLE, model='gemini-3.8-flash-tts', verify=True, takes=2,
                   fallback_styles=('[energetic, confident] ', ''))}      # strings that keep reading the direction aloud: tag, then plain

# ---- verify: a stage direction is occasionally read aloud ("Enthusiastic. Nice work!"), so a styled bank is checked by ear ----
VERIFY_MODEL = 'gemini-3.8-flash'
VERIFY_TRIES = 3
REVIEW_PROMPT = ('You are auditioning takes for "Brodie", a hype push-up coach heard over a FaceTime call on a phone speaker. '
                 'The script of this clip is: "{text}". Listen and return JSON only: {{"transcript": the exact words spoken, '
                 '"energy": 1-10 (motivating energy; 10 = fired up but not shouting), "clarity": 1-10 (intelligible on a phone speaker), '
                 '"naturalness": 1-10 (a real person, natural pacing and intonation), "coach_fit": 1-10 (a confident, warm gym coach), '
                 '"shouting": true or false}}')

def _words(s):
    import re
    s = re.sub(r'(\d+)', lambda m: ' ' + number_word(int(m.group(1))) + ' ' if int(m.group(1)) <= COUNT_MAX else m.group(1), s.lower())
    return re.findall(r"[a-z0-9']+", s.replace('-', ' ').replace('\u2019', "'"))

def transcript_ok(text, heard):
    """False when the transcript has words the script does not: any extra leading word (a spoken stage direction comes
    first), two or more extra words anywhere, or a poor match overall. Substitutions such as QUEUE heard as "Q" pass."""
    import difflib
    tw, hw = _words(text), _words(heard)
    if not hw:
        return False
    sm = difflib.SequenceMatcher(None, tw, hw, autojunk=False)
    # a replace that only re-splits a compound ("pushups" -> "push ups", "armcrosschest" -> "arm cross chest") adds no word
    ops = [op for op in sm.get_opcodes() if not (op[0] == 'replace' and ''.join(tw[op[1]:op[2]]) == ''.join(hw[op[3]:op[4]]))]
    extra = sum(max(0, (j2 - j1) - (i2 - i1)) for tag, i1, i2, j1, j2 in ops if tag in ('insert', 'replace'))
    lead = bool(ops) and ops[0][0] in ('insert', 'replace') and ops[0][3] == 0 and (ops[0][4] - ops[0][3]) > (ops[0][2] - ops[0][1])
    return not lead and extra < 2 and difflib.SequenceMatcher(None, ''.join(tw), ''.join(hw), autojunk=False).ratio() >= 0.75

def take_score(review):
    """Rank of a reviewed take: energy + clarity + naturalness + coach fit, shouting penalised."""
    return sum(float(review.get(k) or 0) for k in ('energy', 'clarity', 'naturalness', 'coach_fit')) - (5.0 if review.get('shouting') else 0.0)

def gemini_review(client, pcm, text, model=VERIFY_MODEL):
    """A Gemini listener's review of a 24 kHz s16 mono clip: {transcript, energy, clarity, naturalness, coach_fit, shouting}
    (retried with backoff like the renderer)."""
    from google.genai import types
    import io, wave
    b = io.BytesIO(); w = wave.open(b, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm); w.close()
    last = None
    for attempt in range(RETRIES):
        try:
            r = client.models.generate_content(model=model, contents=[types.Part.from_bytes(data=b.getvalue(), mime_type='audio/wav'), REVIEW_PROMPT.format(text=text)],
                                               config=types.GenerateContentConfig(temperature=0.0, response_mime_type='application/json'))
            j = json.loads(r.text)
            j = j[0] if isinstance(j, list) and j else j
            if not isinstance(j, dict) or not isinstance(j.get('transcript'), str):
                raise ValueError(f'unexpected review {r.text[:200]!r}')
            return j
        except Exception as e:
            last = e
            if attempt + 1 < RETRIES:
                time.sleep(backoff_s(attempt, e))
    raise last

# ---- gemini backend ----
GEMINI_USD = {'text_in_per_m': 0.50, 'audio_out_per_m': 10.0}      # gemini-2.5-flash-preview-tts list price; the 3.8 model is assumed the same

def gemini_client(api_key=None):
    """genai.Client on the key from GEMINI_API_KEY. With env GEMINI_BASE_URL set (hackathon: the key is a team token and the relay in
    modal/gemini_relay.py holds the real one) every call goes to that base URL instead of Google; unset, the client is built as before."""
    from google import genai
    key = api_key or os.environ['GEMINI_API_KEY']
    base_url = (os.environ.get('GEMINI_BASE_URL') or '').strip().rstrip('/')
    if not base_url:
        return genai.Client(api_key=key)
    from google.genai import types
    print(f'[cues_tts] gemini via relay {base_url}', flush=True)
    return genai.Client(api_key=key, http_options=types.HttpOptions(base_url=base_url))

def gemini_pick_model(client, want):
    names = [m.name.split('/')[-1] for m in client.models.list() if 'tts' in m.name.lower()]
    if want in names:
        return want
    for f in (lambda n: 'flash' in n and 'lite' not in n and 'preview' not in n, lambda n: 'flash' in n and 'lite' not in n,
              lambda n: 'flash' in n, lambda n: True):
        c = [n for n in names if f(n)]
        if c:
            return sorted(c)[-1]
    raise SystemExit(f'no Gemini TTS model listed (have {names})')

RETRIES = 8

def backoff_s(attempt, err=None):
    """Seconds before retry `attempt + 1`: 2, 4, 8, ... capped at 60, plus jitter; a rate limit (429 / RESOURCE_EXHAUSTED)
    waits at least the server's retryDelay when the error carries one."""
    import random, re
    d = min(60.0, 2.0 * 2 ** attempt) * (0.75 + 0.5 * random.random())
    msg = str(err or '')
    if '429' in msg or 'RESOURCE_EXHAUSTED' in msg:
        m = re.search(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s", msg)
        d = max(d, float(m.group(1)) + 1.0 if m else 15.0)
    return d

def gemini_render_one(client, model, voice, text):
    """Plain text, or a bracketed stage direction before it: "(Australian accent, warm, upbeat trainer) Sink lower" is not read
    aloud by gemini-3.8-flash-tts (a spoken prefix like "Say this in ..." is); system instructions are not supported."""
    from google.genai import types
    import io, wave
    cfg = types.GenerateContentConfig(response_modalities=['AUDIO'],
                                      speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
                                      automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
    last = None
    for attempt in range(RETRIES):
        try:
            r = client.models.generate_content(model=model, contents=text, config=cfg)
            if not r.candidates or not r.candidates[0].content or not r.candidates[0].content.parts:
                raise RuntimeError(f'no audio in the response (finish {getattr(r.candidates[0], "finish_reason", None) if r.candidates else None})')
            part = r.candidates[0].content.parts[0]; data = part.inline_data.data; mime = part.inline_data.mime_type or ''
            if data[:4] == b'RIFF':
                w = wave.open(io.BytesIO(data)); rate, ch = w.getframerate(), w.getnchannels(); x = np.frombuffer(w.readframes(w.getnframes()), np.int16)
            else:                                   # audio/L16;codec=pcm;rate=24000
                rate = int(mime.split('rate=')[1].split(';')[0]) if 'rate=' in mime else SAMPLE_RATE; ch = 1; x = np.frombuffer(data, np.int16)
            if ch > 1:
                x = x.reshape(-1, ch).mean(1).astype(np.int16)
            if rate != SAMPLE_RATE:
                n = int(round(len(x) * SAMPLE_RATE / rate)); x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x.astype(np.float32)).astype(np.int16)
            u = r.usage_metadata
            return x.tobytes(), dict(text_tokens=u.prompt_token_count or 0, audio_tokens=u.candidates_token_count or 0, total_tokens=u.total_token_count or 0)
        except Exception as e:                      # 429 / 5xx / empty candidates: exponential backoff with jitter
            last = e
            if attempt + 1 < RETRIES:
                time.sleep(backoff_s(attempt, e))
    raise last

def pick_model(client, want):
    ids = {m.id for m in client.models.list()}
    if want in ids:
        return want
    return 'tts-1'

def render_one(client, model, voice, text):
    kw = dict(model=model, voice=voice, input=text, response_format='pcm')
    if model.startswith('gpt-4o'):
        kw['instructions'] = INSTRUCTIONS
    for attempt in range(4):
        try:
            r = client.audio.speech.create(**kw)
            return r.content
        except Exception as e:                     # rate limits and transient errors
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1)); last = e

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--backend', default='openai', choices=['openai', 'gemini'])
    ap.add_argument('--model', default=None, help='openai: gpt-4o-mini-tts (fallback tts-1); gemini: the listed flash TTS model')
    ap.add_argument('--bank', default=None, choices=sorted(BANKS), help='a named bank preset (voice, style, model, out dir, mastering); '
                    'v2 = the current recommended voice into data/cues_audio_v2. Explicit flags and CUE_TTS_* env override it')
    ap.add_argument('--voice', default=os.environ.get('CUE_TTS_VOICE') or None, help='openai default nova; gemini default Puck (env CUE_TTS_VOICE)')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--dry-run', action='store_true', help='list what would be rendered, no API calls')
    ap.add_argument('--rerender-counts', action='store_true', help='drop the count words from the manifest so they are rendered again with the tighter trim')
    ap.add_argument('--style', default=os.environ.get('CUE_TTS_STYLE'), help='gemini only: a bracketed stage direction prepended to every string, e.g. "(Australian accent, warm, upbeat trainer) "; not spoken, not part of the manifest key (env CUE_TTS_STYLE)')
    ap.add_argument('--out-dir', default=os.environ.get('CUE_TTS_OUT_DIR') or None, help='bank directory (default: the backend bank); use a new directory for a new voice so banks never mix (env CUE_TTS_OUT_DIR)')
    ap.add_argument('--master', default=None, action=argparse.BooleanOptionalAction,
                    help='trim with pre-roll + fades + loudness-normalize every clip (see master()); default on for a --bank preset, off otherwise so the legacy banks render as before')
    ap.add_argument('--verify', default=None, action=argparse.BooleanOptionalAction,
                    help=f'gemini only: have {VERIFY_MODEL} listen to every new take and re-render (up to {VERIFY_TRIES} extra takes) when the words '
                         'do not match the text, e.g. a spoken stage direction; default on for a --bank preset')
    ap.add_argument('--takes', type=int, default=None, help='gemini + verify: render this many matching takes per string and keep the one the '
                    'listener rates best (energy + clarity + naturalness + coach fit); default 1, or the --bank preset value')
    a = ap.parse_args()
    preset = BANKS.get(a.bank, {})
    if preset:
        a.backend = 'gemini'
    gem = a.backend == 'gemini'
    cues_dir = a.out_dir or preset.get('out_dir') or (CUES_DIR_GEMINI if gem else CUES_DIR)
    want_model = a.model or preset.get('model') or ('gemini-3.8-flash-tts' if gem else 'gpt-4o-mini-tts')
    voice = a.voice or preset.get('voice') or ('Puck' if gem else 'nova')
    a.style = a.style if a.style is not None else preset.get('style', '')
    do_master = a.master if a.master is not None else bool(preset)
    do_verify = gem and (a.verify if a.verify is not None else bool(preset.get('verify')))
    takes = max(1, a.takes or preset.get('takes', 1)) if do_verify else 1
    vocab = vocabulary(); man = load_manifest(cues_dir)
    if a.rerender_counts:
        old = {t: man[t]['duration_s'] for t in count_words() if t in man}
        for t in old: man.pop(t)
        print(f'count words before re-render: {len(old)} clips, mean {sum(old.values()) / max(len(old), 1):.3f} s, total {sum(old.values()):.2f} s')
    todo = [t for t in vocab if not (t in man and os.path.exists(os.path.join(cues_dir, man[t]['file'])))]
    chars = sum(len(t) for t in todo)
    print(f'[{a.backend}] vocabulary {len(vocab)} strings, cached {len(vocab) - len(todo)}, to render {len(todo)} ({chars} chars) -> {cues_dir}')
    if a.dry_run or not todo:
        rate = USD_PER_MCHAR.get(want_model, 15.0)
        if gem: print(f'estimated cost for the remaining {len(todo)} clips: about ${len(todo) * 55 * GEMINI_USD["audio_out_per_m"] / 1e6:.3f} (55 audio tokens per clip)')
        else: print(f'estimated cost for the remaining {chars} chars: ${chars * rate / 1e6:.4f} (at ${rate}/1M chars)')
        if not todo:
            tot = sum(v['duration_s'] for v in man.values())
            print(f'nothing to do; {len(man)} clips, {tot:.1f} s of audio, mean clip {tot / max(len(man), 1):.2f} s; bank complete: {bank_complete(cues_dir)}')
        return
    def finish(pcm, text):
        if do_master:
            return master(pcm, text)
        db, tail = trim_params(text); return trim(pcm, dbfs=db, tail_s=tail)
    print(f'voice {voice}, model {want_model}, style {a.style!r}, mastering {"on" if do_master else "off"}, verify {"on" if do_verify else "off"}, takes {takes}')
    if gem:
        client = gemini_client(); model = gemini_pick_model(client, want_model)
        if model != want_model: print(f'{want_model} not listed, using {model}')
        styles = [a.style] + ([f for f in preset.get('fallback_styles', ()) if f != a.style] if do_verify else [])
        def job(text):
            usage = dict(text_tokens=0, audio_tokens=0, total_tokens=0); good = []; heard = None; n = 0
            for style in styles:                    # a direction this string keeps reading aloud -> the next, plainer one
                for _ in range(takes + VERIFY_TRIES - 1):
                    pcm, u = gemini_render_one(client, model, voice, style + text); n += 1
                    for k in usage: usage[k] += u[k]
                    cut = finish(pcm, text)
                    if not do_verify:
                        return text, pcm, cut, usage
                    rv = gemini_review(client, cut, text); heard = rv['transcript']
                    if transcript_ok(text, heard):
                        good.append((take_score(rv), pcm, cut, style))
                    if len(good) >= takes:
                        break
                if good:
                    break
            if not good:
                raise RuntimeError(f'{n} takes, none matched the text; last heard {heard!r}')
            score, pcm, cut, style = max(good, key=lambda g: g[0])
            usage['score'] = score; usage['style'] = style
            return text, pcm, cut, usage
    else:
        import openai
        client = openai.OpenAI(); model = pick_model(client, want_model)
        if model != want_model: print(f'{want_model} not available, using {model}')
        def job(text):
            pcm = render_one(client, model, voice, text); return text, pcm, finish(pcm, text), None
    os.makedirs(cues_dir, exist_ok=True)
    t0 = time.time(); done = 0; raw_s = 0.0; out_s = 0.0; tok = dict(text_tokens=0, audio_tokens=0, total_tokens=0)
    failed = {}
    def safe(text):                         # one bad string must not lose the rest of the run; failures are listed and exit 1
        try:
            return job(text)
        except Exception as e:
            return text, e, None, None
    with cf.ThreadPoolExecutor(a.workers) as ex:
        for text, pcm, cut, usage in ex.map(safe, todo):
            if isinstance(pcm, Exception):
                failed[text] = pcm; print(f'  FAILED {text!r}: {pcm}', flush=True); continue
            fn = sha1(text) + '.pcm'
            open(os.path.join(cues_dir, fn), 'wb').write(cut)
            d = len(cut) / 2 / SAMPLE_RATE
            db, tail = trim_params(text)
            man[text] = dict(file=fn, duration_s=round(d, 3), chars=len(text), model=model, voice=voice, backend=a.backend, trim_dbfs=db, tail_s=tail, **({'style': a.style} if a.style else {}),
                             **({'mastered': True, 'rms_dbfs': clip_stats(cut)['rms_dbfs']} if do_master else {}))
            raw_s += len(pcm) / 2 / SAMPLE_RATE; out_s += d; done += 1
            if usage:
                for k in tok: tok[k] += usage[k]
                if 'score' in usage: man[text]['review_score'] = usage['score']
                if 'style' in usage:
                    man[text].pop('style', None)
                    if usage['style']: man[text]['style'] = usage['style']
            if done % 25 == 0 or done + len(failed) == len(todo):
                save_manifest(man, cues_dir); print(f'  {done}/{len(todo)}  {time.time() - t0:.0f} s', flush=True)
    save_manifest(man, cues_dir)
    print(f'rendered {done} clips with {model}/{voice}: {raw_s:.1f} s raw -> {out_s:.1f} s after trim; mean clip {out_s / max(done, 1):.2f} s')
    if gem:
        usd = tok['text_tokens'] * GEMINI_USD['text_in_per_m'] / 1e6 + tok['audio_tokens'] * GEMINI_USD['audio_out_per_m'] / 1e6
        print(f"usage totals: {tok['text_tokens']} text tokens in, {tok['audio_tokens']} audio tokens out, {tok['total_tokens']} total; "
              f"cost at the 2.5-flash-tts list price (${GEMINI_USD['text_in_per_m']}/M in, ${GEMINI_USD['audio_out_per_m']}/M audio out): ${usd:.3f}")
    else:
        rate = USD_PER_MCHAR.get(model, 15.0)
        print(f'cost estimate: {chars} chars x ${rate}/1M chars = ${chars * rate / 1e6:.4f}'
              + (f'  (gpt-4o-mini-tts per-minute rate: {raw_s / 60 * 0.015:.4f} USD)' if model.startswith('gpt-4o') else ''))
    tot = sum(v['duration_s'] for v in man.values())
    print(f'manifest {os.path.join(cues_dir, "manifest.json")}: {len(man)} clips, mean clip {tot / max(len(man), 1):.2f} s; bank complete: {bank_complete(cues_dir)}')
    if failed:
        raise SystemExit(f'{len(failed)} strings failed (run again to retry only those): ' + '; '.join(f'{t!r}: {e}' for t, e in failed.items()))

if __name__ == '__main__':
    main()
