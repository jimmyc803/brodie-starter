"""Preflight: run right before recording the demo. Proves the live path works end to end, prints a PASS/FAIL/WARN/SKIP table.

    set -a && source .env.local && set +a && python scripts/preflight.py [--keep] [--skip-livekit]

Checks: env names, files (cue bank, models), Supabase assignment, recap card (web + local), the save path (a real session written
with synthetic events, verified, then deleted again unless --keep), a LiveKit loopback (the recap card published as coach-video
and received by a second participant), and `python -m facetime.worker --help`. Exit 1 on any FAIL.
Secret values are never printed: only env var NAMES (any secret that leaks into an error message is replaced by its name).
"""
import argparse
import asyncio
import io
import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FIXTURE = ROOT / 'db' / 'fixtures' / 'sample_session.json'
REQUIRED_ENV = ['SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'DEMO_CLIENT_ID', 'LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET']
GEMINI_ENV = ('GEMINI_API_KEY', 'GOOGLE_API_KEY')          # facetime/voice.py: either one for --voice gemini
SECRET_ENV = ['SUPABASE_SERVICE_ROLE_KEY', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET', *GEMINI_ENV, 'SUPABASE_URL', 'LIVEKIT_URL']
FILES = ['data/cues_audio_gemini/manifest.json',             # the cue bank (facetime/perception.py)
         'data/models/clf_pose.pt',                          # the fault classifier (perception MODEL_DEFAULT)
         'models/pose_landmarker_full.task',                 # MediaPipe pose, the default variant (src/rtcoach/pose.py)
         'models/pose_landmarker_lite.task',                 # the fallback variant (pipeline.switch_pose)
         'src/rtcoach/thresholds_e3c.json']                  # pipeline THR_DEFAULT
MUSCLE_COUNT = len(json.loads((ROOT / 'shared' / 'muscles.json').read_text())['muscles'])

results = []        # (name, status, detail)
state = {}          # shared between checks: 'assignment', 'png'


def scrub(text):
    text = str(text)
    for name in SECRET_ENV:
        v = os.environ.get(name) or ''
        if len(v) >= 6:
            text = text.replace(v, f'<{name}>')
    return text


def record(name, status, detail=''):
    detail = scrub(detail)
    results.append((name, status, detail))
    print(f'--> {name}: {status} {detail}', flush=True)


async def run_check(name, fn, timeout):
    """fn: an async callable returning (status, detail). A timeout or exception is a FAIL."""
    print(f'\n== {name} (timeout {timeout:g}s)', flush=True)
    try:
        status, detail = await asyncio.wait_for(fn(), timeout)
    except asyncio.TimeoutError:
        status, detail = 'FAIL', f'timed out after {timeout:g}s'
    except Exception as e:
        status, detail = 'FAIL', f'{type(e).__name__}: {str(e)[:300]}'
    record(name, status, detail)


def in_thread(fn, *args):
    return asyncio.get_running_loop().run_in_executor(None, fn, *args)


# ---- 1. env ----
async def check_env():
    missing = [n for n in REQUIRED_ENV if not os.environ.get(n)]
    if not any(os.environ.get(n) for n in GEMINI_ENV):
        missing.append('GEMINI_API_KEY (or GOOGLE_API_KEY)')
    if missing:
        return 'FAIL', 'missing: ' + ', '.join(missing)
    if not os.environ.get('WEB_URL'):
        return 'WARN', 'all required set; WEB_URL missing (recap card renders locally)'
    return 'PASS', 'all set: ' + ', '.join(REQUIRED_ENV + [next(n for n in GEMINI_ENV if os.environ.get(n)), 'WEB_URL'])


# ---- 2. files ----
async def check_files():
    missing = [f for f in FILES if not (ROOT / f).is_file()]
    if missing:
        return 'FAIL', 'missing: ' + ', '.join(missing)
    try:
        n = len(json.loads((ROOT / FILES[0]).read_text()))
    except Exception as e:
        return 'FAIL', f'{FILES[0]} unreadable: {type(e).__name__}'
    return 'PASS', f'{len(FILES)} files present (cue manifest: {n} entries)'


# ---- 3. supabase assignment ----
async def check_supabase():
    from facetime.supa import Supa
    if not Supa.available() or not os.environ.get('DEMO_CLIENT_ID'):
        return 'FAIL', 'needs SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DEMO_CLIENT_ID'
    from facetime.plan_loader import load_assignment
    a = await in_thread(load_assignment, os.environ['DEMO_CLIENT_ID'])
    if not a:
        return 'FAIL', 'load_assignment(DEMO_CLIENT_ID) returned no plan (see [plan] lines above)'
    state['assignment'] = a
    return 'PASS', f"plan={a['plan']} | day={a.get('day_title')!r} | coach={a.get('coach_name')!r} | client={a.get('client_name')!r}"


# ---- 4. recap card ----
async def check_recap_card():
    from PIL import Image
    from facetime import recap_video as rv
    view = json.loads(FIXTURE.read_text())
    png = await in_thread(rv.render_recap_png, view)
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        return 'FAIL', 'render_recap_png did not return a PNG'
    size = Image.open(io.BytesIO(png)).size
    state['png'] = png
    local = f'local render OK {size[0]}x{size[1]} ({len(png)} bytes)'
    if not os.environ.get('WEB_URL'):
        return 'WARN', f'WEB_URL unset: local render will be used; {local}'
    web = await in_thread(rv.fetch_recap_png, view['session']['share_token'], 8.0)
    if not web or rv._as_png(web) is None:
        return 'WARN', f'web recap image unavailable for the sample token (see [recap] line): local render will be used; {local}'
    wsize = Image.open(io.BytesIO(web)).size
    return 'PASS', f'web image {wsize[0]}x{wsize[1]} ({len(web)} bytes); {local}'


# ---- 5. save path ----
def fault_label(name):
    try:
        cues = json.loads((ROOT / 'src' / 'rtcoach' / 'cues.json').read_text())
        return next(k for k in cues if k.startswith(f'{name} - '))
    except Exception:
        return f'{name} - preflight'


def synthetic_events(plan):
    """The first two plan items: wait, active, reps (a fault on rep 1 of set 1), rest; then done on the second."""
    from facetime.session_sink import parse_plan
    items = parse_plan(plan)[:2]
    evs, t, sent = [], 100.0, []
    for i, (name, reps) in enumerate(items):
        evs += [{'type': 'session', 't': t, 'state': 'wait', 'item': i, 'count': 0},
                {'type': 'session', 't': t + 1, 'state': 'active', 'item': i, 'count': 0}]
        t += 2
        for n in range(1, reps + 1):
            if i == 0 and n == 1:
                evs.append({'type': 'fault', 't': t, 'label': fault_label(name)})
            evs.append({'type': 'rep', 't': t + 0.5, 'n': n}); t += 1
        last = i == len(items) - 1
        evs.append({'type': 'session', 't': t, 'state': 'done' if last else 'rest', 'item': i, 'count': reps}); t += 3
        sent.append((name, reps))
    return evs, sent


def cleanup(db, sid):
    """Delete the session's reps, sets, muscle_scores, the sessions row, the storage object and the local view file; verify gone."""
    sets = db.select('sets', session_id=f'eq.{sid}', select='id') or []
    set_ids = [s['id'] for s in sets]
    if set_ids:
        db.delete('reps', set_id=f'in.({",".join(set_ids)})')
    db.delete('sets', session_id=f'eq.{sid}')
    db.delete('muscle_scores', session_id=f'eq.{sid}')
    db.delete('sessions', id=f'eq.{sid}')
    path = f'{sid}.png'
    if db.exists('recaps', path):
        db.remove('recaps', path)
    local = ROOT / 'data' / 'tmp' / 'sessions' / f'{sid}.json'
    local.unlink(missing_ok=True)
    left = {'sessions': len(db.select('sessions', id=f'eq.{sid}', select='id') or []),
            'sets': len(db.select('sets', session_id=f'eq.{sid}', select='id') or []),
            'reps': len(db.select('reps', set_id=f'in.({",".join(set_ids)})', select='id') or []) if set_ids else 0,
            'muscle_scores': len(db.select('muscle_scores', session_id=f'eq.{sid}', select='muscle') or []),
            'storage': int(db.exists('recaps', path)), 'file': int(local.exists())}
    return left


async def check_save(keep):
    a = state.get('assignment')
    if not a:
        return 'SKIP', 'no plan (supabase check failed)'
    from facetime.call_recap import CallRecap
    from facetime.recap_video import get_recap_png
    from facetime.supa import Supa
    db = Supa()
    rec = CallRecap(a['plan'], a, client_id=os.environ['DEMO_CLIENT_ID'])
    sid = None
    try:
        await rec.start()
        sid = rec.sink.session_id
        evs, sent = synthetic_events(a['plan'])
        for e in evs:
            rec.on_event(e)
        view = await rec.finish(room=None, show=False, reason='preflight')
        sid = rec.sink.session_id
        if view is None:
            return 'FAIL', 'CallRecap.finish returned no view (see [sink] lines)'
        await asyncio.wait_for(in_thread(get_recap_png, view), 20)      # what the call does on done: render + upload + path

        problems = []
        rows = db.select('sessions', id=f'eq.{sid}', select='id,ended_at,recap_image_path') or []
        if not rows:
            return 'FAIL', f'no sessions row for {sid}'
        row = rows[0]
        if not row.get('ended_at'):
            problems.append('ended_at not set')
        want_sets = sum(len(ex['sets']) for ex in view['exercises'])
        want_reps = sum(len(st['reps']) for ex in view['exercises'] for st in ex['sets'])
        sets = db.select('sets', session_id=f'eq.{sid}', select='id,exercise_key,set_number,completed_reps') or []
        reps = db.select('reps', set_id=f'in.({",".join(s["id"] for s in sets)})', select='id,faults') if sets else []
        ms = db.select('muscle_scores', session_id=f'eq.{sid}', select='muscle') or []
        if len(sets) != want_sets: problems.append(f'sets {len(sets)} != {want_sets}')
        if len(reps) != want_reps: problems.append(f'reps {len(reps)} != {want_reps}')
        if want_reps != sum(r for _, r in sent): problems.append(f'view reps {want_reps} != sent {sum(r for _, r in sent)}')
        if not any(r.get('faults') for r in reps): problems.append('no rep carries the fault')
        if len(ms) != MUSCLE_COUNT: problems.append(f'muscle_scores {len(ms)} != {MUSCLE_COUNT}')
        path = row.get('recap_image_path')
        if not path:
            problems.append('recap_image_path not set')
        elif not db.exists('recaps', path):
            problems.append(f'recaps/{path} not in storage')
        summary = f'session {sid}: {len(sets)} sets, {len(reps)} reps, {len(ms)} muscles, image {path}'
        return ('FAIL', f'{summary}; ' + '; '.join(problems)) if problems else ('PASS', summary)
    finally:
        if sid is None:
            pass
        elif keep:
            state['cleanup'] = ('SKIP', f'--keep: session {sid} left in place (recap /r/{rec.sink.share_token})')
        else:
            try:
                left = await asyncio.wait_for(in_thread(cleanup, db, sid), 30)
                bad = {k: v for k, v in left.items() if v}
                state['cleanup'] = ('FAIL' if bad else 'PASS',
                                    f'left behind: {bad}' if bad else f'session {sid} removed (sessions/sets/reps/muscle_scores 0, storage + file gone)')
            except Exception as e:
                state['cleanup'] = ('FAIL', f'session {sid}: {type(e).__name__}: {str(e)[:200]}')


# ---- 6. livekit loopback ----
async def check_livekit():
    need = [n for n in ('LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET') if not os.environ.get(n)]
    if need:
        return 'FAIL', 'missing: ' + ', '.join(need)
    from livekit import rtc
    from facetime.mint_token import mint
    from facetime.recap_video import publish_recap, render_recap_png
    png = state.get('png') or render_recap_png(json.loads(FIXTURE.read_text()))
    room_name = f'preflight-{secrets.token_hex(4)}'
    url = os.environ['LIVEKIT_URL']
    worker, viewer = rtc.Room(), rtc.Room()
    got_track = asyncio.get_running_loop().create_future()

    @viewer.on('track_subscribed')
    def _on_track(track, publication, participant):
        if track.kind == rtc.TrackKind.KIND_VIDEO and publication.name == 'coach-video' and not got_track.done():
            got_track.set_result(track)

    pub_task = stream = None
    try:
        await asyncio.wait_for(viewer.connect(url, mint('viewer', room_name, 600), rtc.RoomOptions(auto_subscribe=True)), 10)
        await asyncio.wait_for(worker.connect(url, mint('worker', room_name, 600)), 10)
        pub_task = asyncio.create_task(publish_recap(worker, png, seconds=6))
        t0 = time.monotonic()
        try:
            track = await asyncio.wait_for(got_track, 15)
        except asyncio.TimeoutError:
            return 'FAIL', f'room {room_name}: viewer never subscribed to coach-video within 15s'
        stream = rtc.VideoStream(track)
        try:
            ev = await asyncio.wait_for(stream.__anext__(), max(1.0, 15 - (time.monotonic() - t0)))
        except asyncio.TimeoutError:
            return 'FAIL', f'room {room_name}: coach-video subscribed but no frame within 15s'
        f = ev.frame
        return 'PASS', f'room {room_name}: frame {f.width}x{f.height} after {time.monotonic() - t0:.1f}s'
    finally:
        if stream is not None:
            try: await asyncio.wait_for(stream.aclose(), 5)
            except Exception: pass
        if pub_task is not None:
            pub_task.cancel()
            try: await asyncio.wait_for(pub_task, 8)
            except (Exception, asyncio.CancelledError): pass
        for r in (viewer, worker):
            try: await asyncio.wait_for(r.disconnect(), 5)
            except Exception: pass


# ---- 7. worker import ----
async def check_worker():
    def run():
        return subprocess.run([sys.executable, '-m', 'facetime.worker', '--help'], cwd=ROOT, capture_output=True, text=True, timeout=90)
    p = await in_thread(run)
    if p.returncode != 0:
        tail = (p.stderr or p.stdout).strip().splitlines()[-3:]
        return 'FAIL', f'exit {p.returncode}: ' + ' | '.join(tail)
    return 'PASS', 'python -m facetime.worker --help exits 0'


async def main(a):
    await run_check('env', check_env, 5)
    await run_check('files', check_files, 10)
    await run_check('supabase', check_supabase, 25)
    await run_check('recap card', check_recap_card, 25)
    await run_check('save path', lambda: check_save(a.keep), 90)
    if 'cleanup' in state:
        record('cleanup', *state['cleanup'])
    if a.skip_livekit:
        record('livekit loopback', 'SKIP', '--skip-livekit')
    else:
        await run_check('livekit loopback', check_livekit, 50)
    await run_check('worker import', check_worker, 100)


def table():
    w = max(len(n) for n, _, _ in results)
    print('\n' + '=' * 72 + '\nPREFLIGHT')
    for n, s, d in results:
        print(f'  {n:<{w}}  {s:<4}  {d}')
    fails = sum(1 for _, s, _ in results if s == 'FAIL')
    print('=' * 72)
    print(f'{"FAIL" if fails else "READY"}: {fails} failed, {sum(1 for _, s, _ in results if s == "WARN")} warnings, '
          f'{sum(1 for _, s, _ in results if s == "SKIP")} skipped')
    return 1 if fails else 0


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Pre-demo check of the live path (PASS/FAIL/WARN/SKIP table; exit 1 on any FAIL).')
    ap.add_argument('--keep', action='store_true', help='keep the test session (rows + recap image) instead of deleting it')
    ap.add_argument('--skip-livekit', action='store_true', help='skip the LiveKit loopback check')
    args = ap.parse_args()
    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        record('interrupted', 'FAIL', 'Ctrl-C')
    code = table()
    sys.stdout.flush(); sys.stderr.flush()
    os._exit(code)      # do not wait on a timed-out worker thread
