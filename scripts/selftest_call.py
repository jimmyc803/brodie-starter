"""End-to-end "phone call" self-test on one machine: no human, no phone. Prints a PASS/WARN/FAIL table; exit 1 on any FAIL.

Flow (all in a fresh LiveKit room selftest-<random>, so a human's dev worker registered under the same project is never dispatched):
 1. facetime.worker joins that room directly with the LiveKit Agents CLI `connect --room R --participant-identity <AGENT_IDENTITY>`
    (unregistered worker: no dispatch), flags --voice gemini --plan "squats:4,squats:4"; stdout+stderr -> data/tmp/selftest/worker.log.
 2. facetime.fake_bridge is the caller (identity BRIDGE_IDENTITY): run2.mp4 looped at --scale 720x1280 --fps 30 --no-simulcast (what
    a phone sends through the Chert bridge, per its docstring), Brodie's audio -> data/tmp/selftest/brodie.wav (+ onsets.json).
 3. A third participant "selftest-viewer" (this process) saves the first frame of the agent's `coach-video` track as card.png.
 4. Waits until the worker logs "[sink] session ... written" and the card frame arrived (or --timeout), stops the bridge (the worker
    sees the caller leave and ends its job), then stops the worker (SIGINT, then SIGTERM/SIGKILL on its process group).
 5. Checks the worker log, the event log, brodie.wav, card.png and the Supabase rows; then deletes the selftest session (rows cascade
    from sessions; the recap storage object is removed) unless --keep. Every subprocess is killed on any exit.

Run:  set -a && source ~/.beat-muse-supabase.secrets && set +a && .venv/bin/python scripts/selftest_call.py [--keep] [--timeout 240]
Env:  SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, DEMO_CLIENT_ID, LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, GEMINI_API_KEY (never printed).
"""
import argparse, datetime, asyncio, json, os, re, secrets, signal, subprocess, sys, time, wave
SAMPLE_SESSION_ID = 'fbf58a0c-2c85-502e-9e74-feec3aa1c3a5'   # db/fixtures/sample_session.json: the web demo depends on it, never delete
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
with open(os.path.join(ROOT, 'shared', 'muscles.json')) as f:
    MUSCLE_COUNT = len(json.load(f)['muscles'])
import numpy as np

from facetime import AGENT_IDENTITY, BRIDGE_IDENTITY, DATA, SAMPLE_RATE

OUT = os.path.join(DATA, 'tmp', 'selftest')
VIDEO = os.path.join(DATA, 'tmp', 'mac_handoff', 'crops', 'run2.mp4')
PLAN = 'squats:4,squats:4'
REQUIRED_ENV = ('SUPABASE_URL', 'SUPABASE_SERVICE_ROLE_KEY', 'DEMO_CLIENT_ID', 'LIVEKIT_URL', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET', 'GEMINI_API_KEY')
PY = sys.executable
PROCS = []                      # (name, Popen) started by us; killed (process group) on every exit path


def say(msg):
    print(f'[selftest] {time.strftime("%H:%M:%S")} {msg}', flush=True)


# ---------------------------------------------------------------- subprocesses
def spawn(name, argv, log_path):
    f = open(log_path, 'w')
    env = dict(os.environ, PYTHONUNBUFFERED='1')
    p = subprocess.Popen(argv, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, start_new_session=True)
    f.close()                   # the child holds its own copy of the fd
    PROCS.append((name, p))
    say(f'started {name} (pid {p.pid}) -> {os.path.relpath(log_path, ROOT)}')
    return p


def signal_group(p, sig):
    try: os.killpg(p.pid, sig)          # start_new_session: pgid == pid; covers the worker's job processes too
    except (ProcessLookupError, PermissionError): pass


def group_alive(p):
    try: os.killpg(p.pid, 0); return True
    except (ProcessLookupError, PermissionError): return False


def stop(p, name, first=signal.SIGINT, grace=20.0):
    """first signal, wait `grace`; then SIGTERM 5 s; then SIGKILL. Returns how it ended ('clean' | 'term' | 'kill' | 'already')."""
    if p.poll() is not None and not group_alive(p): return 'already'
    how = 'clean'
    for sig, wait in ((first, grace), (signal.SIGTERM, 5.0), (signal.SIGKILL, 3.0)):
        if sig is not first: how = 'term' if sig == signal.SIGTERM else 'kill'
        signal_group(p, sig)
        t = time.time() + wait
        while time.time() < t and (p.poll() is None or group_alive(p)):
            time.sleep(0.2)
        if p.poll() is not None and not group_alive(p): break
    say(f'{name} stopped ({how}, rc {p.poll()})')
    return how


def kill_all():
    for name, p in PROCS:
        if p.poll() is None or group_alive(p):
            signal_group(p, signal.SIGKILL)
            try: p.wait(3)
            except Exception: pass
            say(f'killed {name} (pid {p.pid})')


def read(path):
    try:
        with open(path, errors='replace') as f: return f.read()
    except FileNotFoundError: return ''


async def wait_for(pred, timeout, every=0.5):
    t = time.time() + timeout
    while time.time() < t:
        if pred(): return True
        await asyncio.sleep(every)
    return pred()


# ---------------------------------------------------------------- viewer
class Viewer:
    """Third participant: subscribes and saves the first frame of the agent's coach-video track."""
    def __init__(self, room_name, out_png):
        from livekit import rtc
        self.rtc = rtc; self.room_name = room_name; self.out_png = out_png
        self.room = rtc.Room(); self.task = None; self.got = asyncio.Event(); self.size = None; self.error = None; self.from_identity = None
        self.seen = set()                                  # every participant identity that was in the room

    async def connect(self):
        from facetime.mint_token import mint
        self.room.on('track_subscribed', self.on_track)
        self.room.on('participant_connected', lambda p: self.seen.add(p.identity))
        await self.room.connect(os.environ['LIVEKIT_URL'], mint('selftest-viewer', self.room_name),
                                self.rtc.RoomOptions(auto_subscribe=True))
        self.seen.update(p.identity for p in self.room.remote_participants.values())
        say(f'viewer connected; participants {list(self.room.remote_participants)}')

    def on_track(self, track, pub, participant):
        if track.kind == self.rtc.TrackKind.KIND_VIDEO and pub.name == 'coach-video' and self.task is None:
            say(f'viewer subscribed to coach-video from {participant.identity!r}')
            self.from_identity = participant.identity
            self.task = asyncio.ensure_future(self.grab(track))

    async def grab(self, track):
        from PIL import Image
        stream = self.rtc.VideoStream(track)
        try:
            async for ev in stream:
                fr = ev.frame.convert(self.rtc.VideoBufferType.RGBA)
                img = Image.frombytes('RGBA', (fr.width, fr.height), bytes(fr.data))
                img.save(self.out_png); self.size = img.size
                say(f'card frame {fr.width}x{fr.height} -> {os.path.relpath(self.out_png, ROOT)}')
                self.got.set(); break
        except Exception as e:
            self.error = f'{type(e).__name__}: {e}'
        finally:
            await stream.aclose()

    async def close(self):
        if self.task and not self.task.done(): self.task.cancel()
        try: await asyncio.wait_for(self.room.disconnect(), 5)
        except Exception: pass


async def room_participants(room_name):
    from livekit import api
    async with api.LiveKitAPI() as lk:
        try:
            r = await lk.room.list_participants(api.ListParticipantsRequest(room=room_name))
            return [p.identity for p in r.participants]
        except Exception:
            return []                   # room already gone


async def delete_room(room_name):
    from livekit import api
    try:
        async with api.LiveKitAPI() as lk:
            await lk.room.delete_room(api.DeleteRoomRequest(room=room_name))
    except Exception:
        pass


# ---------------------------------------------------------------- checks
def load_events(path):
    out = []
    for line in read(path).splitlines():
        try: out.append(json.loads(line))
        except ValueError: pass
    return out


def tracebacks(log):
    """(unexpected, known) Traceback counts; known = the livekit FfiHandle.__del__ AssertionError at process exit."""
    lines = log.splitlines(); bad = known = 0
    for i, l in enumerate(lines):
        if not l.startswith('Traceback (most recent call last)'): continue
        j = i + 1
        while j < len(lines) and (lines[j].startswith(' ') or lines[j].startswith('\t')): j += 1
        block = '\n'.join(lines[max(0, i - 2):j + 1])
        if 'FfiHandle.__del__' in block and 'AssertionError' in block: known += 1
        else: bad += 1
    return bad, known


def wav_onsets(path, thr_dbfs=-35.0, min_silence=0.15):
    """Onsets in the wav the bridge wrote (the same rule as fake_bridge): (onset count, seconds of audio, seconds loud)."""
    try:
        w = wave.open(path, 'rb'); x = np.frombuffer(w.readframes(w.getnframes()), np.int16); sr = w.getframerate(); w.close()
    except (FileNotFoundError, wave.Error, EOFError):
        return 0, 0.0, 0.0
    n = sr // 50; thr = 32767 * 10 ** (thr_dbfs / 20); off = thr / 3; silent = 1e9; onsets = 0; loud = 0.0
    for k in range(0, len(x) - n + 1, n):
        rms = float(np.sqrt(np.mean(x[k:k + n].astype(np.float32) ** 2)))
        if rms > thr:
            if silent >= min_silence: onsets += 1
            silent = 0.0; loud += n / sr
        elif rms < off:
            silent += n / sr
    return onsets, len(x) / max(sr, 1), loud


class Report:
    def __init__(self): self.rows = []
    def add(self, status, name, detail=''):
        self.rows.append((status, name, detail))
    def check(self, cond, name, detail=''):
        self.add('PASS' if cond else 'FAIL', name, detail); return cond
    def print(self):
        if not self.rows: self.add('FAIL', 'selftest ran', 'aborted before any check')
        w = max(len(r[1]) for r in self.rows)
        print('\n' + '=' * 100)
        for s, n, d in self.rows: print(f'{s:5} {n:<{w}}  {d}')
        print('=' * 100)
        fails = sum(1 for r in self.rows if r[0] == 'FAIL'); warns = sum(1 for r in self.rows if r[0] == 'WARN')
        print(f'RESULT: {"FAIL" if fails else "PASS"} ({len(self.rows) - fails - warns} pass, {warns} warn, {fails} fail)', flush=True)
        return fails


def check_all(R, room, worker_log, events, bridge_log, wav, card, viewer, stop_how, room_left, db):
    log = read(worker_log)
    m = re.search(rf"\[worker\] bound to '{re.escape(BRIDGE_IDENTITY)}'", log)
    R.check(bool(m), 'worker bound to the caller', f'bound to {BRIDGE_IDENTITY!r}' if m else 'no "[worker] bound to" line for the bridge')
    m = re.search(r"\[worker\] job \S+: joined room '([^']+)'.*?mode (plan \([^)]*\))", log)
    R.check(bool(m) and m.group(1) == room and PLAN in m.group(2), 'plan loaded', m.group(2) if m else 'no job "joined room ... mode plan" line')

    ev = load_events(events)
    reps = [e for e in ev if e.get('type') == 'rep' and 'squat' in str(e.get('exercise', '')).lower()]
    R.check(len(reps) >= 6, 'squat reps counted (>= 6)', f'{len(reps)} rep events')
    sess = [e for e in ev if e.get('type') == 'session']
    states = [e.get('state') for e in sess]
    R.check('done' in states, 'session state reached done', ' -> '.join(dict.fromkeys(s for s in states if s)) or 'no session events')

    speaking = len(re.findall(r'^\[voice\] speaking', log, re.M))
    voice_ev = [e for e in ev if e.get('type') == 'voice' and e.get('role') != 'caller']
    gem_missing = '[voice] GEMINI_API_KEY is MISSING' in log
    R.check(speaking >= 1 or len(voice_ev) >= 1, 'Brodie voice spoke',
            f'{speaking} "[voice] speaking", {len(voice_ev)} voice events' + (' (GEMINI_API_KEY missing in worker)' if gem_missing else ''))
    # what he said must be coaching, not his prompt: no drafts, bullets, rules read aloud (selftest 2026-10-11 caught all three)
    lines = [(e.get('text') or '').strip() for e in voice_ev if (e.get('text') or '').strip()]
    bad = [t for t in lines if len(t) > 220 or re.search(r'(?i)draft|private instruction|never say|do not repeat|output generation|^\s*[*(]|\n\s*[*-] ', t)]
    R.check(len(lines) >= 2 and not bad, 'voice lines are short coaching sentences',
            f'{len(lines)} lines' + (f'; BAD: {bad[0][:90]!r}' if bad else f'; e.g. {lines[0][:80]!r}' if lines else ''))
    on, secs, loud = wav_onsets(wav)
    try: bj = json.load(open(os.path.join(OUT, 'onsets.json')))
    except (FileNotFoundError, ValueError): bj = {}
    R.check(on >= 1, 'cue audio received by the caller', f'{on} onsets in brodie.wav ({secs:.1f} s, {loud:.1f} s loud); bridge counted {len(bj.get("onsets", []))}')

    written = re.search(r'^\[sink\] session (\S+) written \(([^)]*)\)', log, re.M)
    R.check(bool(written), '[sink] session written', f'{written.group(1)} ({written.group(2)})' if written else 'no "[sink] session ... written"')
    started = re.search(r'^\[sink\] session (\S+) started \(recap (/r/\S+)\)', log, re.M)
    sid = (written or started).group(1) if (written or started) else None
    url = started.group(2) if started else None

    if viewer.size:
        from PIL import Image
        a = np.asarray(Image.open(card).convert('RGB')).astype(np.float32)
        std = float(a.std()); levels = len(np.unique((a[::8, ::8] // 16).reshape(-1, 3), axis=0))
        R.check(viewer.size in ((720, 1280), (1080, 1920)) and std > 8 and levels > 4, 'card.png received 9:16 (web 1080x1920 or local 720x1280), not blank',
                f'{viewer.size[0]}x{viewer.size[1]} from {viewer.from_identity!r}, pixel std {std:.1f}, {levels} colour levels -> {os.path.relpath(card, ROOT)}')
    else:
        R.check(False, 'card.png received 9:16 (web 1080x1920 or local 720x1280), not blank', viewer.error or 'no coach-video frame')

    if db is None:
        R.check(False, 'Supabase rows', 'Supabase not configured')
    elif not sid:
        R.check(False, 'Supabase sessions row', 'no session id in the worker log')
    else:
        rows = db.select('sessions', id=f'eq.{sid}', select='id,ended_at,recap_image_path,share_token') or []
        row = rows[0] if rows else {}
        url = url or (f"/r/{row['share_token']}" if row.get('share_token') else None)
        R.check(bool(row.get('ended_at')), 'Supabase sessions row ended_at', f"ended_at {row.get('ended_at')}" if row else 'no row')
        sets = db.select('sets', session_id=f'eq.{sid}', select='exercise_key,set_number,planned_reps,completed_reps', order='set_number.asc') or []
        got = [(s['exercise_key'], s['set_number'], s['planned_reps'], s['completed_reps']) for s in sets]
        closed, prev = [], None                         # the count each time a set closes (state enters rest or done)
        for e in sess:
            st = e.get('state')
            if st in ('rest', 'done') and prev not in ('rest', 'done') and isinstance(e.get('count'), int): closed.append(e['count'])
            prev = st
        # the truth is what Brodie's session counted when each set closed (a stretched test clip can time a set out at 3/4);
        # the save must match it exactly, and both planned sets must be there with reps
        ok = len(sets) == 2 and all(s['planned_reps'] == 4 and s['completed_reps'] >= 1 for s in sets) and [s['completed_reps'] for s in sets] == closed[:2]
        R.check(ok, 'Supabase sets completed reps match', f'{got}; session close counts {closed[:4]}')
        ms = db.select('muscle_scores', session_id=f'eq.{sid}', select='muscle') or []
        R.check(len(ms) == MUSCLE_COUNT, f'Supabase {MUSCLE_COUNT} muscle_scores', f'{len(ms)} rows')
        R.check(bool(row.get('recap_image_path')), 'recap_image_path set', str(row.get('recap_image_path')))

    bad, known = tracebacks(log)
    R.check(bad == 0, 'no Python Traceback in worker.log', f'{bad} unexpected')
    if known: R.add('WARN', 'livekit FfiHandle.__del__ at exit', f'{known} (known harmless)')
    if 'job' in log and re.search(r'^\[worker\] job \S+ done', log, re.M):
        R.add('PASS', 'worker job ended on caller leave', re.search(r'^\[worker\] job \S+ done \(([^;]*)', log, re.M).group(1))
    else:
        R.add('FAIL', 'worker job ended on caller leave', 'no "[worker] job ... done" line')
    R.add('PASS' if stop_how in ('clean', 'already') else 'WARN', 'worker process stopped', stop_how)
    R.check(not room_left, 'nobody left in the room', ', '.join(room_left) or 'empty')
    return sid, url


# ---------------------------------------------------------------- main
async def run(a):
    os.makedirs(OUT, exist_ok=True)
    room = f'selftest-{secrets.token_hex(4)}'
    worker_log, bridge_log = os.path.join(OUT, 'worker.log'), os.path.join(OUT, 'bridge.log')
    events, cues = os.path.join(OUT, 'events.jsonl'), os.path.join(OUT, 'cues.jsonl')
    wav, card = os.path.join(OUT, 'brodie.wav'), os.path.join(OUT, 'card.png')
    for p in (events, cues, wav, card, os.path.join(OUT, 'onsets.json')):
        if os.path.exists(p): os.remove(p)
    say(f'room {room}; outputs in {os.path.relpath(OUT, ROOT)}')

    worker = spawn('worker', [PY, '-m', 'facetime.worker', '--voice', 'gemini', '--plan', PLAN, '--event-log', events, '--cue-log', cues,
                              '--idle-processes', '0', 'connect', '--room', room, '--participant-identity', AGENT_IDENTITY, '--log-level', 'info'], worker_log)
    joined = await wait_for(lambda: re.search(r'^\[worker\] job \S+: joined room', read(worker_log), re.M) or worker.poll() is not None, a.join_timeout)
    if worker.poll() is not None or not joined or not re.search(r'^\[worker\] job \S+: joined room', read(worker_log), re.M):
        say(f'worker did not join the room within {a.join_timeout:.0f} s (rc {worker.poll()}); last lines:')
        print('\n'.join(read(worker_log).splitlines()[-25:]))
        return None, room, worker
    say('worker joined the room')

    viewer = Viewer(room, card)
    await viewer.connect()
    bridge = spawn('bridge', [PY, '-m', 'facetime.fake_bridge', '--room', room, '--video', VIDEO, '--scale', '720x1280', '--fps', '30',
                              '--no-simulcast', '--max-bitrate', '4000000', '--loop', '--tail', '3', '--wait-agent', '30',
                              '--out', wav, '--onsets', os.path.join(OUT, 'onsets.json')], bridge_log)

    sink_re = re.compile(r'^\[sink\] session \S+ written', re.M)
    t0 = time.time(); last = ''
    while time.time() - t0 < a.timeout:
        log = read(worker_log)
        if sink_re.search(log) and viewer.got.is_set(): break
        if worker.poll() is not None: say('worker exited early'); break
        if bridge.poll() is not None: say('bridge exited early'); break
        prog = f"reps {len(re.findall(r'^\[event\] rep ', log, re.M))}, sink {'yes' if sink_re.search(log) else 'no'}, card {'yes' if viewer.got.is_set() else 'no'}"
        if prog != last and int(time.time() - t0) % 5 == 0: say(prog); last = prog
        await asyncio.sleep(1.0)
    else:
        say(f'timeout after {a.timeout:.0f} s')
    say(f'waited {time.time() - t0:.0f} s; stopping the bridge (the caller hangs up)')

    await asyncio.get_running_loop().run_in_executor(None, stop, bridge, 'bridge', signal.SIGINT, 15.0)
    await wait_for(lambda: re.search(r'^\[worker\] job \S+ done', read(worker_log), re.M) is not None or worker.poll() is not None, 30)
    await viewer.close()
    how = await asyncio.get_running_loop().run_in_executor(None, stop, worker, 'worker', signal.SIGINT, 20.0)
    await asyncio.sleep(1.0)
    left = [i for i in await room_participants(room) if i != 'selftest-viewer']
    await delete_room(room)
    return dict(worker_log=worker_log, events=events, bridge_log=bridge_log, wav=wav, card=card, viewer=viewer, stop_how=how, room_left=left), room, worker


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--keep', action='store_true', help='keep the selftest session in Supabase (default: delete rows + recap image)')
    ap.add_argument('--timeout', type=float, default=360, help='seconds to wait for the session write and the card after the bridge starts')
    ap.add_argument('--join-timeout', type=float, default=120.0, help='seconds for the worker to prewarm and join the room')
    a = ap.parse_args()
    missing = [k for k in REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        print(f'[selftest] missing env: {", ".join(missing)} (values are never printed)', file=sys.stderr); return 2
    if not os.path.exists(VIDEO):
        print(f'[selftest] missing clip {VIDEO}', file=sys.stderr); return 2

    def on_term(sig, frm): raise SystemExit(f'signal {sig}')
    signal.signal(signal.SIGTERM, on_term); signal.signal(signal.SIGHUP, on_term)
    from facetime.supa import Supa
    db = Supa()
    R = Report(); sid = None; res = None
    t_run = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        res, room, worker = asyncio.run(run(a))
        if res is None:
            R.check(False, 'worker joined the room', f'see {os.path.relpath(os.path.join(OUT, "worker.log"), ROOT)}')
        else:
            sid, url = check_all(R, room, res['worker_log'], res['events'], res['bridge_log'], res['wav'], res['card'], res['viewer'],
                                 res['stop_how'], res['room_left'], db)
            web = (os.environ.get('WEB_URL') or '').rstrip('/')
            print(f'[selftest] recap: {url or "n/a"}' + (f'  ({web}{url})' if web and url else ''))
            print(f'[selftest] card: {res["card"]}  worker log: {res["worker_log"]}  audio: {res["wav"]}')
            # a dev worker registered with agent name "" is auto-dispatched to EVERY new room: two Brodies on one call
            extra = sorted(res['viewer'].seen - {'brodie-agent', 'chert-bridge', 'selftest-viewer'})
            R.check(not extra, 'only one Brodie in the room',
                    f'also joined: {extra} (another worker is running, e.g. a dev worker in a terminal: stop it first)' if extra else 'yes')
    finally:
        kill_all()
        if not sid and any(n == "worker" for n, _ in PROCS):   # aborted mid-run: still clean up a session the worker created
            m = re.search(r'^\[sink\] session (\S+) (?:started|written)', read(os.path.join(OUT, 'worker.log')), re.M)
            sid = m.group(1) if m else None
        if sid and not a.keep:
            try:
                row = (db.select('sessions', id=f'eq.{sid}', select='recap_image_path') or [{}])[0]
                if row.get('recap_image_path'): db.remove('recaps', row['recap_image_path'])
                elif db.exists('recaps', f'{sid}.png'): db.remove('recaps', f'{sid}.png')
                db.delete('sessions', id=f'eq.{sid}')           # sets, reps, muscle_scores cascade
                say(f'deleted selftest session {sid} (rows + recap image)')
            except Exception as e:
                say(f'cleanup of session {sid} failed: {type(e).__name__}: {str(e)[:200]}')
        elif sid:
            say(f'kept session {sid} (--keep)')
        if res is not None and not a.keep and (res['viewer'].seen - {'brodie-agent', 'chert-bridge', 'selftest-viewer'}):
            try:                                            # the other worker's session of this test call: not a real workout
                # created_at is server-set; started_at is not (the seeded sample starts at 14:05 UTC and was wrongly swept as a stray)
                stray = [r['id'] for r in db.select('sessions', client_id=f"eq.{os.environ['DEMO_CLIENT_ID']}", created_at=f'gte.{t_run}', select='id') or []
                         if r['id'] not in (sid, SAMPLE_SESSION_ID)]
                for i in stray: db.delete('sessions', id=f'eq.{i}')
                if stray: say(f'deleted {len(stray)} session(s) the other worker recorded during this test')
            except Exception as e:
                say(f'stray cleanup failed: {type(e).__name__}: {str(e)[:200]}')
    return 1 if R.print() else 0


if __name__ == '__main__':
    sys.exit(main())
