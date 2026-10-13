"""Annotate a recorded push-up video with the live push-up mirror: the worker's pipeline (pose, RepCounter2 counter, the
strict judge) and facetime/pushup_mirror.py's renderer, written to a portrait 720x1280 mp4 + a JSON summary.

The pipeline steps at the live rate (~10 fps, every `step`-th frame) like on a call, so counts and verdicts match what
the worker would judge; the mirror renders every frame (the skeleton and status update on the pose frames). Valid reps
increment the on-screen count; every judged rep flashes GOOD REP / NO REP with its first reason. Optionally writes a
PNG contact sheet of evenly spaced frames (plus the idle card) for eyeballing the look.

Run:  PYTHONPATH=src:. .venv/bin/python -m facetime.annotate_pushups --video clip.mp4 [--out out.mp4] [--sheet sheet.png]
"""
import argparse, json, os, subprocess, tempfile, time

import cv2
import numpy as np

from facetime import DATA
from facetime.pipeline import FPS, FramePipeline, COUNTERS, load_json_arg
from challenge.judge.cues import CUES
from facetime.pushup_mirror import PushupMirror, MirrorState, STATUS_TEXT, W, H

SPEAK_S = 1.8                      # how long a cue "plays" here (Brodie's mouth moves, the bubble shows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--video', required=True); ap.add_argument('--out', default=None)
    ap.add_argument('--model', default=os.path.join(DATA, 'models', 'clf_pose.pt'), help='exercise/form classifier (the live default)')
    ap.add_argument('--pose', default='full'); ap.add_argument('--counter', default='v2', choices=sorted(COUNTERS))
    ap.add_argument('--trigger', default='auto'); ap.add_argument('--judge-thr', default=None, help='JSON (or .json file) judge thresholds')
    ap.add_argument('--sheet', default=None, help='also write a PNG contact sheet here')
    ap.add_argument('--sheet-n', type=int, default=8)
    a = ap.parse_args(argv)
    out = a.out or os.path.splitext(a.video)[0] + '.pushups.mp4'
    cap = cv2.VideoCapture(a.video)
    if not cap.isOpened(): raise SystemExit(f"can't open {a.video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0; n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    step = max(1, round(fps / FPS))
    thr = load_json_arg(a.judge_thr, None)
    pipe = FramePipeline(a.model if os.path.exists(a.model) else None, None, a.pose, {}, None, rep_params=COUNTERS[a.counter],
                         trigger=a.trigger, judge=True, judge_thr=thr)
    pipe.set_exercise('pushups')
    pm = PushupMirror(); st = MirrorState()
    want = set(np.linspace(0, max(0, n_frames - 1), a.sheet_n).astype(int).tolist()) if a.sheet else set()
    tiles = []; picks = {}
    tmp = tempfile.NamedTemporaryFile(suffix='.mp4', delete=False).name
    wr = cv2.VideoWriter(tmp, cv2.VideoWriter_fourcc(*'mp4v'), fps, (W, H))
    reps, statuses, i, lm, seq, render_ms = [], {}, 0, None, 0, []
    try:
        while True:
            ok, bgr = cap.read()
            if not ok: break
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); t = i / fps
            if i % step == 0:
                r = pipe.process(rgb, int(t * 1000)); lm = pipe.last_landmarks; seq += 1
                for n, v in sorted((r.get('judge') or {}).items()):
                    counts = v['valid'] and not v.get('in_challenge')
                    st.rep(v['valid'], v['reject_reasons'], now=t, counts=counts)
                    if v.get('cue') in CUES: st.say(CUES[v['cue']], now=t)
                    reps.append(dict(n=n, t=round(t, 2), valid=v['valid'], reasons=v['reject_reasons']))
                    print(f"  t={t:6.2f}s  rep {n}: {'VALID' if v['valid'] else 'no rep ' + ','.join(v['reject_reasons'])}")
            st.speaking = st.cue is not None and 0 <= t - st.cue_t < SPEAK_S
            t0 = time.perf_counter()
            img = pm.render(rgb, lm, pipe.judge.thr if pipe.judge is not None else thr, st, now=t, seq=seq)
            render_ms.append((time.perf_counter() - t0) * 1000)
            statuses[pm.status.shown] = statuses.get(pm.status.shown, 0) + 1
            if i in want: tiles.append(img.copy())
            # extra sheet picks: the first red-form frame and the first non-good camera status after a second
            if a.sheet:
                body = pm._colors()
                if 'red' not in picks and (body[3] or body[4]) and i % 3 == 0: picks['red'] = img.copy()
                if 'status' not in picks and t > 1.0 and pm.status.shown not in (None, 'good'): picks['status'] = img.copy()
            wr.write(cv2.cvtColor(img, cv2.COLOR_RGB2BGR)); i += 1
    finally:
        cap.release(); wr.release(); pipe.close()
    if i == 0: raise SystemExit('no frames read')
    r = subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-c:v', 'libx264', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out])
    if r.returncode: os.replace(tmp, out)
    else: os.remove(tmp)
    valid = sum(1 for x in reps if x['valid'])
    summary = dict(video=a.video, frames=i, fps=fps, reps=len(reps), valid=valid, rep_events=reps,
                   status_frames={STATUS_TEXT[k][0] if k else 'none': v for k, v in statuses.items()},
                   render_ms=dict(mean=round(float(np.mean(render_ms)), 2), p95=round(float(np.percentile(render_ms, 95)), 2)))
    with open(os.path.splitext(out)[0] + '.json', 'w') as f: json.dump(summary, f, indent=1, default=float)
    print(f"{len(reps)} reps ({valid} valid), {i / fps:.1f} s, render {summary['render_ms']} ms -> {out}")
    if a.sheet:
        tiles += [picks[k] for k in ('red', 'status') if k in picks]
        tiles.append(pm.render(None, None, state=MirrorState(), now=1.0))
        cols = 5; th, tw = H // 2, W // 2
        small = [cv2.resize(x, (tw, th), interpolation=cv2.INTER_AREA) for x in tiles]
        while len(small) % cols: small.append(np.full((th, tw, 3), 255, np.uint8))
        rows = [np.concatenate(small[k:k + cols], axis=1) for k in range(0, len(small), cols)]
        sheet = np.concatenate(rows, axis=0)
        os.makedirs(os.path.dirname(os.path.abspath(a.sheet)) or '.', exist_ok=True)
        cv2.imwrite(a.sheet, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR)); print('sheet ->', a.sheet)


if __name__ == '__main__':
    main()
