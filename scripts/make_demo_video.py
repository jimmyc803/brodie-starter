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

from facetime.pullup import COUNT_WORDS as COUNT_TEXT
COUNT_WORDS_L = [w.lower() for w in COUNT_TEXT]
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


def roast_caption(img, line, top=True):
    """Roast mode: the line as a big meme caption (white, black outline, a red ROAST tag), wrapped to two lines, in place."""
    h, w = img.shape[:2]; font = cv2.FONT_HERSHEY_DUPLEX; scale = 1.45 * w / 720; th = max(2, int(3 * w / 720))
    words = line.upper().split(); lines = [words[0]]
    for wd in words[1:]:
        cand = lines[-1] + ' ' + wd
        if cv2.getTextSize(cand, font, scale, th)[0][0] <= w * 0.86: lines[-1] = cand
        else: lines.append(wd)
    while max(cv2.getTextSize(l, font, scale, th)[0][0] for l in lines) > w * 0.9: scale *= 0.92
    lh = int(cv2.getTextSize('A', font, scale, th)[0][1] * 1.6); y = int(h * (0.52 if top else 0.62))
    tag = 'ROAST'; (tw, tth), _ = cv2.getTextSize(tag, font, scale * 0.5, 2)
    cv2.rectangle(img, ((w - tw) // 2 - 12, y - lh - tth - 14), ((w + tw) // 2 + 12, y - lh + 2), (225, 40, 40), -1)
    cv2.putText(img, tag, ((w - tw) // 2, y - lh - 6), font, scale * 0.5, (255, 255, 255), 2, cv2.LINE_AA)
    for k, l in enumerate(lines):
        lw = cv2.getTextSize(l, font, scale, th)[0][0]; org = ((w - lw) // 2, y + k * lh)
        cv2.putText(img, l, org, font, scale, (0, 0, 0), th + 8, cv2.LINE_AA)
        cv2.putText(img, l, org, font, scale, (255, 255, 255), th, cv2.LINE_AA)


ROAST_SHOW_S = 3.0
from facetime.roast import ROAST_LINES
ROAST_SET = set(ROAST_LINES)


def add_roasts(events, bank, duration, gap=6.0):
    """Roast mode: the opener after the first announce, a roast line after a spoken correction (at most one per `gap` s, after the
    correction clip so the two don't overlap) and a closing roast after the workout. All bank strings (facetime/roast.py)."""
    from facetime.roast import ROAST_START, roast_for, close_line
    ann = next((e for e in events if e.get('type') == 'cue' and e.get('intent') == 'announce'), None)
    t0 = ann['t'] + (bank.duration(ann['text']) or 1.0) + 0.3 if ann else 0.0
    added = [dict(type='cue', t=round(t0, 2), text=ROAST_START, intent='roast')]
    last = -gap; n = 0
    for e in sorted((e for e in events if e.get('type') == 'fault'), key=lambda e: e['t']):
        if e['t'] - last < gap: continue
        corr = next((c for c in events if c.get('type') == 'cue' and c.get('intent') == 'correction' and 0 <= c['t'] - e['t'] < 1.0), None)
        t = (corr['t'] + (bank.duration(corr['text']) or 0.8) + 0.2) if corr else e['t']
        added.append(dict(type='cue', t=round(t, 2), text=roast_for(e.get('label'), n), intent='roast')); last = e['t']; n += 1
    added.append(dict(type='cue', t=round(duration + 0.4, 2), text=close_line(n), intent='roast'))
    events.extend(added)


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
    ap.add_argument('--fit', default='auto', choices=['auto', 'crop', 'letterbox'], help='landscape footage in the portrait call view: crop to the person '
                    '(standing exercises) or letterbox the whole frame (floor exercises from the side); auto = letterbox for push-ups and planks')
    ap.add_argument('--roast', action='store_true', help='roast mode (facetime/roast.py): a roast line after corrections and at the end, on screen and spoken')
    add_arguments(ap)
    a = ap.parse_args()
    if not a.plan and not a.exercise: a.plan = 'squats:10'
    pull_target = None                                    # pull-up mode: facetime/pullup.py counts, not the Session
    if a.plan and a.plan.split(':')[0].strip().lower().replace('-', ' ') in ('pull ups', 'pullups', 'pull up', 'pullup'):
        pull_target = int(a.plan.rpartition(':')[2] or 5); a.plan = f'pull ups:{pull_target}'
    floor = any(k in (a.plan or a.exercise or '').lower() for k in ('push', 'plank'))
    mirror.LETTERBOX = a.fit == 'letterbox' or (a.fit == 'auto' and floor)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    # normalise first: any phone file (HEVC .mov, rotated portrait, variable frame rate, 4K) -> upright H.264, constant
    # 30 fps, at most 1280 px tall, trimmed; every time below is then video time from 0
    if not os.path.exists(a.video): sys.exit(f'no such video: {a.video}')
    trimmed = os.path.join(os.path.dirname(os.path.abspath(a.out)), '.normalised.mp4')
    cmd = ['ffmpeg', '-v', 'error', '-y'] + (['-ss', str(a.start)] if a.start else []) + ['-i', a.video]
    if a.end is not None: cmd += ['-t', str(a.end - (a.start or 0.0))]
    fps = min(30.0, a.max_fps)
    subprocess.run(cmd + ['-an', '-vf', f"fps={fps:g},scale='if(gt(iw,ih),min(1280,iw),-2)':'if(gt(iw,ih),-2,min(1280,ih))'",
                          '-c:v', 'libx264', '-crf', '16', '-preset', 'fast', '-pix_fmt', 'yuv420p', trimmed], check=True)
    a.video = trimmed

    # ---- pass 1: perception at 10 fps, exactly as on a call ----
    cap = cv2.VideoCapture(a.video); src_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    n_src = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); out_fps = min(src_fps, a.max_fps)
    log(f'{a.video}: {n_src} frames at {src_fps:g} fps; plan {a.plan or a.exercise}')
    bank = CueBank(); events = []
    if pull_target is None:
        per = Perception(Config.from_args(a), clip_s=bank.duration, t0=0.0); per.on_event(events.append); pipe = per.pipe
    else:
        from facetime.pipeline import FramePipeline, load_json_arg, COUNTERS
        from facetime.pullup import PullupCounter
        per = None; pc = PullupCounter(target=pull_target); started = done = False
        pipe = FramePipeline(a.model, None, a.pose, load_json_arg(a.params, {}), load_json_arg(a.thr), rep_params=COUNTERS[a.counter], trigger='none')
        def ev(type_, t, **kw): events.append(dict(type=type_, t=round(t, 2), **kw))
        ev('cue', 0.0, text="Let's do pull ups", intent='announce'); ev('session', 0.0, state='wait', item=0, exercise='pull ups', target=pull_target, count=0)
    samples = []                         # (t, landmarks, count, target, exercise, state[, PullupState])
    next_t = 0.0; i = 0; t_start = time.time()
    while True:
        ok, bgr = cap.read()
        if not ok: break
        t = i / src_fps; i += 1
        if t + 1e-6 < next_t: continue
        next_t += 1.0 / FPS
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        if per is not None:
            per.process_frame(rgb, t_recv=t, t_ms=t * 1000.0, meta=dict(frame=len(samples), t_clip=t))
            lm = pipe.last_landmarks; s = per.session
            samples.append((t, None if lm is None else np.array(lm, np.float32), s.last_count, getattr(s, 'target', None), pipe.exercise, s.state))
            continue
        pipe.process(rgb, t_ms=t * 1000.0); lm = pipe.last_landmarks
        lm = None if lm is None else np.array(lm, np.float32)
        pst = pc.update(lm, t)
        if pst.on_bar and not started:
            started = True; ev('session', t, state='active', item=0, exercise='pull ups', target=pull_target, count=0)
        for kind, val in pst.events:
            if kind == 'rep': ev('rep', t, n=val)
            elif kind == 'fault': ev('fault', t, label=val)
            else: ev('cue', t, text=val, intent='count' if val[0].isupper() and val in COUNT_TEXT else 'correction')
        if started and not done and pst.count >= pull_target:
            done = True; ev('cue', t + 1.0, text=f"That's {COUNT_WORDS_L[pull_target - 1]}, nice work", intent='milestone')
        import copy
        samples.append((t, lm, pst.count, pull_target, 'pull ups', 'active' if pst.on_bar else ('done' if done else 'wait'), copy.copy(pst)))
    cap.release(); duration = i / src_fps
    if pull_target is not None:                           # every rep counts, extra reps past the target too
        ev('session', duration, state='done', item=0, exercise=None, target=pull_target, count=pc.st.count, done=True)
    if a.roast: add_roasts(events, bank, duration)
    events.sort(key=lambda e: e['t'])
    reps = [e for e in events if e.get('type') == 'rep']; cues = [e for e in events if e.get('type') == 'cue']
    log(f'perception: {len(samples)} frames in {time.time() - t_start:.1f} s, {len(reps)} reps, {len(cues)} cues, '
        f"{sum(e.get('type') == 'fault' for e in events)} corrections")

    # ---- the cards: one per closed set, the heat map filling in ----
    # the card after every rep and every closed set (an open set is closed with the reps so far), so it fills in live
    closes = [k + 1 for k, e in enumerate(events) if e.get('type') == 'rep' or (e.get('type') == 'session' and e.get('state') in ('rest', 'done'))]
    card_times = [(0.0, card_for(events, a.plan, 0))] + [(events[k - 1]['t'], card_for(events, a.plan, k)) for k in closes]
    final = card_for(events, a.plan, len(events))
    if a.save:
        from facetime.recap_video import get_recap_png
        sink = SessionSink(os.environ.get('DEMO_CLIENT_ID'), None, None, a.plan); sink.start()
        for ev in events: sink.on_event(ev)
        view = sink.finish('demo video')
        final = png_to_panel(get_recap_png(view))
        log(f"saved session {view['session']['id']}; recap {os.environ.get('WEB_URL', '')}/r/{view['session']['share_token']}")
    log(f'{len(card_times)} card states (one per rep and closed set)')

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
        if pull_target is None:
            pane = compose(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), lm, s0[2], s0[3], s0[4], s0[5], cue, cue_t, face, now=t)
        else:
            from facetime.pullup import compose_pullup
            pane = compose_pullup(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), lm, s0[6], cue, cue_t, face, now=t)
        if a.roast and cue in ROAST_SET and t - cue_t <= ROAST_SHOW_S: roast_caption(pane, cue)
        left = cv2.resize(pane, (PW, PH), interpolation=cv2.INTER_AREA)
        right = [c for ct, c in card_times if ct <= t][-1]
        enc.stdin.write(frame_canvas(left, right).tobytes())
    cap.release()
    if left is not None:                                  # the outro: the final card, the last frame dimmed
        dim = (left * 0.35).astype(np.uint8)
        closer = [c[2] for c in spoken if c[2] in ROAST_SET and c[0] >= duration] if a.roast else []
        if closer: roast_caption(dim, closer[-1], top=False)
        end = frame_canvas(dim, final)
        label(end, 'WORKOUT DONE', LX + 120, PY + PH // 2 - (160 if closer else 0), 1.2, WHITE, 2)
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
    if per is not None and hasattr(per, 'close'): per.close()


if __name__ == '__main__':
    main()
