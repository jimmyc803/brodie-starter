"""Demo video: a workout recording run through Brodie, the live skeleton overlay on the left, the recap heat map on the right.

The left panel is facetime/mirror.py (what the caller sees on FaceTime with --mirror): the caller's frame with the pose skeleton,
the exercise and rep count, Brodie's last cue and his face inset. The right panel is the recap card (facetime/recap_video.py),
re-rendered each time a set closes so the heat map fills in during the workout, then held at the end. Brodie's cue clips are
mixed in as the audio track (bank clips only: the Gemini voice needs a live call).

Perception runs at the pipeline's 10 fps exactly as on a call; the video is rendered at the source frame rate (max 30) with the
landmarks interpolated between processed frames, so the skeleton moves smoothly.

  .venv/bin/python scripts/make_demo_video.py --video data/tmp/mac_handoff/crops/run3.mp4 \
      --plan "squats:10,pushups:8,jumping jacks:20,lunges:10" [--out data/tmp/demo/demo.mp4] [--save]

--save also writes the session to Supabase (DEMO_CLIENT_ID; source ~/.beat-muse-supabase.secrets first), uses the web card
(WEB_URL/api/recap-image/<token>) as the final card and prints the /r recap link.
"""
import argparse, os, subprocess, sys, tempfile, time
import numpy as np
import cv2

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'src'))

from facetime.pipeline import FPS
from facetime.perception import Perception, Config, add_arguments
from facetime.audio_out import CueBank
from facetime import mirror
from facetime.mirror import compose, VOLT

# A video has no Dynamic Island, no FaceTime crop and no self-view: put the bars at the edges so they don't cover the body.
mirror.SAFE_TOP = 10; mirror.SAFE_X = 40; mirror.SAFE_BOTTOM = mirror.H
from facetime.avatar import Avatar
from facetime.session_sink import SessionSink
from facetime.recap_video import render_recap_png
from facetime.replay_local import mix_audio

CW, CH = 1920, 1080                       # canvas
PW, PH = 540, 960                         # each 9:16 panel
LX, RX, PY = 360, 1020, 84                # panel positions
BG = (10, 10, 10); WHITE = (235, 235, 235); GREY = (140, 140, 140)


def log(msg):
    print(f'[demo] {msg}', flush=True)


def lerp_lm(a, b, w):
    if a is None or b is None: return a if w < 0.5 else b
    out = a.copy(); out[:, :3] = a[:, :3] * (1 - w) + b[:, :3] * w; out[:, 3] = np.minimum(a[:, 3], b[:, 3]); return out


def png_to_panel(png):
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    return cv2.cvtColor(cv2.resize(img, (PW, PH), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2RGB)


def card_for(events, plan, upto):
    """The recap card as of events[:upto]: a local, write-free sink replays them and renders the view."""
    sink = SessionSink(os.environ.get('DEMO_CLIENT_ID'), None, None, plan, db=None); sink.db = None
    for ev in events[:upto]: sink.on_event(ev)
    return png_to_panel(render_recap_png(sink.finish('demo snapshot')))


def label(img, s, x, y, scale=0.8, color=VOLT, thick=2):
    cv2.putText(img, s, (x, y), cv2.FONT_HERSHEY_DUPLEX, scale, color, thick, cv2.LINE_AA)


def frame_canvas(left, right):
    c = np.full((CH, CW, 3), BG, np.uint8)
    label(c, 'LIVE ON FACETIME', LX, PY - 22); label(c, 'RECAP HEAT MAP', RX, PY - 22)
    for x, img in ((LX, left), (RX, right)):
        cv2.rectangle(c, (x - 3, PY - 3), (x + PW + 2, PY + PH + 2), VOLT, 2)
        c[PY:PY + PH, x:x + PW] = img
    label(c, 'BRODIE FOR COACHES', LX, CH - 14, 0.6, GREY, 1)
    label(c, 'reps, form and heat map: computed live from the video', RX, CH - 14, 0.6, GREY, 1)
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True)
    ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'tmp', 'demo', 'demo.mp4'))
    ap.add_argument('--hold', type=float, default=6.0, help='seconds the final card stays on screen after the workout')
    ap.add_argument('--max-fps', type=float, default=30.0)
    ap.add_argument('--start', type=float, default=None, help='trim: start at this second of the recording')
    ap.add_argument('--end', type=float, default=None, help='trim: stop at this second of the recording')
    ap.add_argument('--save', action='store_true', help='write the session to Supabase and use the web card as the final card')
    ap.add_argument('--no-audio', dest='audio', action='store_false')
    add_arguments(ap)
    a = ap.parse_args()
    if not a.plan and not a.exercise: a.plan = 'squats:10'
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    trimmed = None
    if a.start is not None or a.end is not None:          # cut first, so every time below is video time from 0
        trimmed = os.path.join(os.path.dirname(os.path.abspath(a.out)), '.trimmed.mp4')
        cmd = ['ffmpeg', '-v', 'error', '-y'] + (['-ss', str(a.start)] if a.start else []) + ['-i', a.video]
        if a.end is not None: cmd += ['-t', str(a.end - (a.start or 0.0))]
        subprocess.run(cmd + ['-an', '-c:v', 'libx264', '-crf', '14', '-preset', 'fast', trimmed], check=True); a.video = trimmed

    # ---- pass 1: perception at 10 fps, exactly as on a call ----
    cap = cv2.VideoCapture(a.video); src_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); out_fps = min(src_fps, a.max_fps)
    log(f'{a.video}: {n_src} frames at {src_fps:g} fps; plan {a.plan or a.exercise}')
    bank = CueBank(); per = Perception(Config.from_args(a), clip_s=bank.duration, t0=0.0)
    events = []; per.on_event(events.append)
    samples = []                         # (t, landmarks, count, target, exercise, state)
    next_t = 0.0; i = 0; t_start = time.time()
    while True:
        ok, bgr = cap.read()
        if not ok: break
        t = i / src_fps; i += 1
        if t + 1e-6 < next_t: continue
        next_t += 1.0 / FPS
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        per.process_frame(rgb, t_recv=t, t_ms=t * 1000.0, meta=dict(frame=len(samples), t_clip=t))
        lm = per.pipe.last_landmarks
        s = per.session
        samples.append((t, None if lm is None else np.array(lm, np.float32), s.last_count, getattr(s, 'target', None), per.pipe.exercise, s.state))
    cap.release(); duration = i / src_fps
    reps = [e for e in events if e.get('type') == 'rep']; cues = [e for e in events if e.get('type') == 'cue']
    log(f'perception: {len(samples)} frames in {time.time() - t_start:.1f} s, {len(reps)} reps, {len(cues)} cues, '
        f"{sum(e.get('type') == 'fault' for e in events)} corrections")

    # ---- the cards: one per closed set, the heat map filling in ----
    closes = [k + 1 for k, e in enumerate(events) if e.get('type') == 'session' and e.get('state') in ('rest', 'done')]
    card_times = [(0.0, card_for(events, a.plan, 0))] + [(events[k - 1]['t'], card_for(events, a.plan, k)) for k in closes]
    final = card_for(events, a.plan, len(events))
    if a.save:
        from facetime.recap_video import get_recap_png
        sink = SessionSink(os.environ.get('DEMO_CLIENT_ID'), None, None, a.plan); sink.start()
        for ev in events: sink.on_event(ev)
        view = sink.finish('demo video')
        final = png_to_panel(get_recap_png(view))
        log(f"saved session {view['session']['id']}; recap {os.environ.get('WEB_URL', '')}/r/{view['session']['share_token']}")
    log(f'{len(card_times)} card states (one per closed set)')

    # ---- pass 2: render ----
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='demo-', dir=os.path.dirname(os.path.abspath(a.out)))
    silent = os.path.join(tmp, 'video.mp4')
    enc = subprocess.Popen(['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{CW}x{CH}', '-r', f'{out_fps:g}', '-i', '-',
                            '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', silent], stdin=subprocess.PIPE)
    av = Avatar(); spoken = [(e['t'], e['t'] + (bank.duration(e['text']) or 0.8), e['text']) for e in cues]
    cap = cv2.VideoCapture(a.video); i = 0; k = 0; step = src_fps / out_fps; next_out = 0.0; left = None
    st = np.array([s[0] for s in samples])
    while True:
        ok, bgr = cap.read()
        if not ok: break
        j = i; i += 1
        if j + 1e-6 < next_out: continue
        next_out += step; t = j / src_fps
        k = max(0, int(np.searchsorted(st, t, side='right')) - 1); s0 = samples[k]; s1 = samples[min(k + 1, len(samples) - 1)]
        w = 0.0 if s1[0] <= s0[0] else min(1.0, (t - s0[0]) / (s1[0] - s0[0]))
        lm = lerp_lm(s0[1], s1[1], w)
        last = [c for c in spoken if c[0] <= t]; cue, cue_t = (last[-1][2], last[-1][0]) if last else (None, 0.0)
        speaking = any(c0 <= t < c1 for c0, c1, _ in spoken)
        face = av.frame(speaking=speaking, now=t)
        mirror = compose(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), lm, s0[2], s0[3], s0[4], s0[5], cue, cue_t, face, now=t)
        left = cv2.resize(mirror, (PW, PH), interpolation=cv2.INTER_AREA)
        right = [c for ct, c in card_times if ct <= t][-1]
        enc.stdin.write(frame_canvas(left, right).tobytes())
    cap.release()
    if left is not None:                                  # the outro: the final card, the last frame dimmed
        end = frame_canvas((left * 0.35).astype(np.uint8), final)
        label(end, 'WORKOUT DONE', LX + 120, PY + PH // 2, 1.2, WHITE, 2)
        for _ in range(int(a.hold * out_fps)): enc.stdin.write(end.tobytes())
    enc.stdin.close(); enc.wait()
    total = duration + a.hold

    if a.audio and spoken:
        wav = os.path.join(tmp, 'cues.wav'); mix_audio(wav, [(c[0], c[2]) for c in spoken], bank, total)
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', silent, '-i', wav, '-c:v', 'copy', '-c:a', 'aac', '-b:a', '160k',
                        '-t', f'{total:.2f}', a.out], check=True)
    else:
        os.replace(silent, a.out)
    for f in os.listdir(tmp): os.remove(os.path.join(tmp, f))
    os.rmdir(tmp)
    if trimmed: os.remove(trimmed)
    log(f'wrote {a.out}: {total:.1f} s, {CW}x{CH} at {out_fps:g} fps')
    if hasattr(per, 'close'): per.close()


if __name__ == '__main__':
    main()
