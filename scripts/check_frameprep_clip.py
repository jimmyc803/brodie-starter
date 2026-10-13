"""Manual real-clip check (needs data/tmp/pushup_clips/mk11544.mp4 + ffmpeg, both local-only): mk11544 turned sideways
inside a bridge frame (a portrait-locked phone on its side) is turned upright within ~2.5 s and counted like the upright clip.

Run:  PYTHONPATH=src:. .venv/bin/python scripts/check_frameprep_clip.py
"""
import json, os, sys, tempfile
from facetime import ROOT, annotate_pushups

CLIP = os.path.join(ROOT, 'data', 'tmp', 'pushup_clips', 'mk11544.mp4')


def main():
    if not os.path.exists(CLIP): sys.exit(f'missing {CLIP}')
    d = tempfile.mkdtemp(); up = os.path.join(d, 'up.mp4')
    annotate_pushups.main(['--video', CLIP, '--out', up]); a = json.load(open(os.path.join(d, 'up.json')))
    for held, fix in ((90, 270), (270, 90)):
        side = os.path.join(d, f'side{held}.mp4')
        annotate_pushups.main(['--video', CLIP, '--out', side, '--rotate', str(held), '--bridge'])
        b = json.load(open(os.path.join(d, f'side{held}.json')))
        good = b['status_frames'].get(next((k for k in b['status_frames'] if 'GOOD' in k), ''), 0)
        ok = (b['rotation'] == fix and len(b['rotations']) == 1 and b['rotations'][0]['t'] <= 2.5
              and a['reps'] >= 4 and b['reps'] >= a['reps'] - 1 and good > 0.6 * b['frames'])
        print(f'held {held}: rotation {b["rotation"]} reps {b["reps"]} (upright {a["reps"]}) good {good}/{b["frames"]} -> {"OK" if ok else "FAIL"}')
        if not ok: sys.exit(1)


if __name__ == '__main__':
    main()
