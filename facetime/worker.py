"""LiveKit Agents worker for the hackathon starter: the coach's eyes (facetime/perception.py) and, by default, its fast mouth
(facetime/audio_out.py CuePlayer, unchanged) in ONE participant with ONE audio track, dispatched by name the way the Chert CLI
dispatches agents (reports/STARTER_PREREQS_REVIEW.md section 1: `chert dev --agent NAME` creates a room with a RoomAgentDispatch for
NAME; the call is accepted once a participant of kind AGENT is in the room; the bridge joins as chert-bridge-<call_id>).

Registers with WorkerOptions(agent_name=AGENT_NAME, default "brodie-coach"). Per job: connect (subscribe all), publish the cue audio
track at once unless --events-only / EVENTS_ONLY=1 (the bridge binds to the one participant with an unmuted audio track), then bind
to the first non-agent participant that publishes video, whoever it is (chert-bridge-<call_id>, a phone page, a fake bridge), feed the
newest frame to Perception in a worker thread with the same arrival-aligned 10 fps sampling as coach_agent, and keep the job joined
until the room closes. A job with no caller (`chert doctor --agent`, prewarm: metadata {"chert_warm": true}) does nothing but stay
joined until somebody publishes video; nothing is said or started on job start. Models and the cue bank are loaded in the prewarm
hook, so a job start costs no model load (one idle preloaded process is kept, --idle-processes).
Job end (Mac test 2026-10-09, reports/MAC_TEST_2026-10-08.md section 5): livekit-agents runs shutdown callbacks only AFTER the entrypoint
returns, so run() ends itself: on the room's `disconnected` event, when the bound participant leaves and nobody rebinds within
--leave-grace-s (default 2 s: a rejoin binds again), when connect() fails (a doctor or warm room torn down before the peer connection
completes), on --max-s and on a perception error. It then cleans up with bounded waits (feed thread join 1 s off the loop, VideoStream
closed, player stopped, cue in flight at most 1.5 s and only while still connected) and calls ctx.shutdown() so the framework finalises.

Events (one JSON object each, schema in facetime/perception.py and docs/STARTER_EVENTS.md) go to
  - an in-process asyncio.Queue, job.events, for a conversational layer (register a coroutine with @consumer, below);
  - a JSONL log, --event-log / RTCOACH_EVENT_LOG (default data/tmp/worker_events.jsonl; each line also carries room, call_id, job);
  - optionally the room data channel as JSON (--publish-data, topic --data-topic, off by default: Chert rooms hold two participants,
    the data channel is for rooms we own).
Cues the player finished or dropped go to --cue-log / RTCOACH_CUE_LOG (the coach_agent --log record shape) and to stdout.

Plan: --plan, else env PLAN, else DEMO_CLIENT_ID active assignment at call start, else starter/plan.txt, else DEFAULT_PLAN;
--exercise for one exercise, --auto for auto-detect. Job metadata is read for chert_call and media and logged (never acted on).

Voice (--voice gemini, default off: the default and events-only modes are untouched): facetime/voice.py runs Gemini Live (voice Puck)
in this same participant, its audio mixed into the cue player's one track through CuePlayer.attach_mixer() (ducked about 10 dB under a
count) and gated to the gaps between sets (session state wait/rest/done, a gesture or an armed probe outside a set, a caller's question
during a rest; the caller's audio is not forwarded during a set and a reply still streaming when a set starts is cut: interrupted,
buffers cleared, later frames dropped). The model session starts when a caller is bound (never on a warm job). Persona from
--persona (starter/persona.md); handlers from --handlers, default starter/handlers.py whenever it exists, in EVERY mode (on_event(event,
say_now, ask_voice); without the voice ask_voice returns None); model turns are logged as events of type voice {text, t, role}.
Latency probe: --latency-probe / RTCOACH_LATENCY_PROBE=1 (off by default; probe events are emitted either way; never acted on during
an active set).

Beyond reps (docs/STARTER_README.md "Your own coach: beyond reps"): --perception off runs NO Perception (no pose model in prewarm,
no session script, no rep/cue/fault events): the worker still joins, publishes its audio track, binds to the first remote participant
that publishes video (or, with no video, audio), starts the model session on the bind, emits one synthetic session event
{state: "open", exercise: null, count: 0, mode: "voice"} once the session is up (handlers greet on it) and a status event (no pose
fields) every 5 s, and ends on the same paths (leave grace, disconnect, --max-s, connect failure). The Floor is then ALWAYS OPEN
(--floor open, the default without perception): the caller's audio is always forwarded, ask_voice fires at once, nothing is cut;
say_now still plays bank strings. --vision (with --voice gemini) tees the caller's video track into the model session at about
1 fps (--vision-fps, at most 2): facetime/voice.py VideoTee, a livekit.agents VideoInput set as AgentSession.input.video, pulled by
the framework into the realtime session's push_video (JPEG). A warm job never starts a session or forwards a frame. The plan file
is then appended to the persona as free text (a recipe, a checklist), not parsed as exercises.
  .venv/bin/python -m facetime.worker --perception off --vision --voice gemini --persona starter/examples/meal_prep/persona.md \
      --plan-file starter/examples/meal_prep/recipe.md --handlers starter/examples/meal_prep/handlers.py dev
Competition (CHALLENGE_MODE=competition; default demo keeps everything above): push-ups only with the strict judge, no
DEMO_CLIENT_ID; on bind a challenge.worker CompetitionCall gatekeeps through the dispatcher (POST /calls/start; reject or
dispatcher down -> leave within 5 s, nothing recorded), then runs the 3:00 count + 0:15 reveal with the judge, liveness
and timeline cues as the only audio, checkpoints data/tmp/sessions/<call_id>.challenge.json after every rep and commits
via /calls/event (reps_committed, call_ended) before leaving. Startup refuses HANGUP_MODE=chert_api without CHERT_FACETIME_TOKEN/CHERT_PROJECT_ID, a missing
DISPATCHER_URL/DISPATCHER_TOKEN or a missing liveness module; a daemon thread beats /calls/heartbeat every 30 s. Env:
LINE_ID, CALLER_ID_SOURCE, HANGUP_MODE, REVEAL_MODE, CHALLENGE_SESSIONS_DIR, WORKER_MAX_JOBS. No media is ever written to disk.
HANGUP_MODE=delete_room: once the commit is in (reps_committed, call_ended) the worker deletes the call's LiveKit room, which
makes Chert end the FaceTime call (a failed delete falls back to leaving). A bridge caller with no video track is still
started after NO_VIDEO_START_S and ended (0 reps) and hung up NO_VIDEO_END_S after joining unless video arrives.
Run:
  .venv/bin/python -m facetime.worker --help
  .venv/bin/python -m facetime.worker [--plan "squats:10,pushups:8"] [--events-only] [--publish-data] dev     # LIVEKIT_URL/API_KEY/API_SECRET in env
  AGENT_NAME=brodie-coach EVENTS_ONLY=1 .venv/bin/python -m facetime.worker start
  GEMINI_API_KEY=... .venv/bin/python -m facetime.worker --voice gemini dev                                      # + GEMINI_LIVE_MODEL, GEMINI_VOICE
The flags before the LiveKit subcommand are ours; `dev`, `start`, `connect`, `download-files` and their options are the LiveKit Agents CLI's.
"""
import argparse, asyncio, collections, json, logging, math, os, re, sys, threading, time
from livekit import rtc
from livekit.agents import AutoSubscribe, JobContext, JobProcess, WorkerOptions, cli
from facetime import DATA, AUDIO_TRACK_NAME
from facetime.pipeline import FPS
from facetime.perception import Perception, Config, add_arguments, build_pipeline, EVENT_SCHEMA_VERSION
from facetime.coach_agent import frame_to_rgb              # the same frame conversion as the demo coach
from facetime.lines import line_id, release as release_line, take_claim

log = logging.getLogger('worker')
ARGS_ENV = 'RTCOACH_WORKER_ARGS'      # main() hands the parsed flags to the job processes as JSON (forkserver children re-import this module)
DEFAULT_PLAN = 'squats:10,pushups:8,jumping jacks:20,lunges:10'
STARTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'starter')
AGENT_KIND = rtc.ParticipantKind.PARTICIPANT_KIND_AGENT
BRIDGE_PREFIX = 'chert-bridge-'
LK_COMMANDS = ('dev', 'start', 'connect', 'download-files', 'console')
CONSUMERS = []                        # coroutines consumer(job) started per job; they read job.events (see docs/STARTER_EVENTS.md)
CHALLENGE_MODES = ('demo', 'competition')
CHERT_HANDLE_KEYS = ('caller', 'handle', 'from', 'phone', 'email')   # chert_call keys tried for the caller handle, in order
HEARTBEAT_EVERY_S = 30.0
JOB_BEAT_S = 30.0                     # job heartbeat (scope job) while a competition job runs
MIRROR_BITRATE = 2_800_000            # the push-up mirror's 720x1280 track: a static framing + 2.8 Mbps keeps the caller's picture crisp
JOB_STALL_S = 10.0                    # a counting job with no processed frame / controller tick this long is unhealthy
JOB_STALE_S = 90.0                    # an active job whose health file is older than this is wedged
IDLE_CARD_FPS = float(os.environ.get('IDLE_CARD_FPS', '4') or 4)   # coach-video rate while no caller video (warm room)
COMMIT_WAIT_S = 15.0                  # aclose waits this long for the competition commit (the checkpoint is on disk already)
NO_VIDEO_START_S = 8.0                # P0-3: a Chert bridge caller with no video track this long -> /calls/start anyway
NO_VIDEO_CUE_DELAY_S = 4.0            # ... the camera cue this long after the accept (after the welcome, never cutting it)
NO_VIDEO_END_S = 20.0                 # ... still no video this long after the caller joined -> end the call (0 reps) and hang up
NO_VIDEO_POLL_S = 0.25
CUE_DRAIN_MAX_S = 8.0                 # HANGUP_MODE=delete_room: the cue in flight may finish (a reject line is ~5 s) before the delete
DELETE_ROOM_TIMEOUT_S = 4.0           # one LiveKit DeleteRoom attempt (2 attempts, then leave the room instead)
AUDIO_PUBLISH_ATTEMPTS = 2            # P1-3: the cue audio track publish
WORKER_MAX_JOBS = 4                   # P1-5: job_count_load = active jobs / this (a call + its replacement warm room + a spare)
_chert_keys_logged = False


def _no_video_cue():
    from challenge.worker.controller import NO_VIDEO_CUE
    return NO_VIDEO_CUE


def challenge_mode():
    """CHALLENGE_MODE: demo (default; the legacy DEMO_CLIENT_ID path) or competition (challenge/worker controller)."""
    return (os.environ.get('CHALLENGE_MODE') or 'demo').strip().lower()


def is_competition():
    return challenge_mode() == 'competition'


def caller_handle(chert_call):
    """The caller handle from chert_call metadata: the first non-empty string among CHERT_HANDLE_KEYS (a nested
    {handle|phone|email} object is looked into too). None when there is none."""
    if not isinstance(chert_call, dict): return None
    for k in CHERT_HANDLE_KEYS:
        v = chert_call.get(k)
        if isinstance(v, dict): v = next((v[x] for x in ('handle', 'phone', 'email') if isinstance(v.get(x), str) and v[x].strip()), None)
        if isinstance(v, str) and v.strip(): return v.strip()
    return None


def metadata_note(md, redact):
    """The job metadata for the joined-room line. redact (competition): chert_call as its key names only (the values hold
    the caller's handle: phone or email)."""
    parts = []
    for k in ('chert_warm', 'chert_call', 'media'):
        if k not in md: continue
        v = md[k]
        if redact and k == 'chert_call':
            parts.append(f'chert_call=<keys {sorted(v) if isinstance(v, dict) else type(v).__name__}>')
        else:
            parts.append(f'{k}={json.dumps(v)[:80]}')
    return ', '.join(parts) or 'none'


def apply_judge_thresholds(pipe, thr):
    """Feed thread: the live judge thresholds on the FramePipeline (judges built later get them too) and on its current
    judge in place (buffered frames are kept: the accumulator reads its thresholds when it uses them)."""
    from challenge.judge.gates import merged_thresholds
    m = merged_thresholds(thr)
    pipe.judge_thr = dict(thr)
    j = getattr(pipe, 'judge', None)
    if j is not None:
        j.thr = m; j.acc.thr = m


def health_path():
    d = os.environ.get('WORKER_HEALTH_DIR') or os.path.join(DATA, 'tmp', 'worker_health')
    return os.path.join(d, f"{os.environ.get('LINE_ID') or 'line-1'}.json")


def supervisor_health(now=None):
    """The supervisor heartbeat's health: a job in a call must have refreshed its health file within JOB_STALE_S and
    called itself healthy; no active job = healthy. Returns (healthy, detail)."""
    now = time.time() if now is None else now
    try:
        with open(health_path()) as f: h = json.load(f)
    except FileNotFoundError:
        return True, {'job': None}
    except (OSError, ValueError) as e:
        return False, {'job': f'unreadable health file: {e!r}'}
    age = now - float(h.get('t') or 0)
    if not h.get('active'): return True, {'job': 'idle'}
    alive = True
    if h.get('pid'):
        try: os.kill(int(h['pid']), 0)
        except ProcessLookupError: alive = False
        except OSError: pass
    if not alive: return True, {'job': 'gone'}                      # the job process exited without clearing it
    ok = bool(h.get('healthy')) and age <= JOB_STALE_S
    return ok, {'job': 'in_call', 'job_age_s': round(age, 1), 'job_healthy': bool(h.get('healthy')), 'call_id': h.get('call_id')}


def log_chert_keys(chert_call):
    """Log the chert_call key names once per process (never the values: they hold the caller's handle)."""
    global _chert_keys_logged
    if _chert_keys_logged: return
    _chert_keys_logged = True
    keys = sorted(chert_call) if isinstance(chert_call, dict) else None
    print(f'[competition] chert_call keys: {keys if keys is not None else type(chert_call).__name__}', flush=True)


def consumer(fn):
    """Register `async def fn(job)`: started as a task once the job is connected; read events with `await job.events.get()`."""
    CONSUMERS.append(fn); return fn


def truthy(s):
    return str(s or '').strip().lower() in ('1', 'true', 'yes', 'on')


def pose_diag(rgb, lm):
    """One line of numbers about what the coach sees (never pixels): the picture's content box inside the frame (black bars
    trimmed), the pose's box, body angle from horizontal (0 = plank, 90 = standing), elbow angles and key-joint visibility."""
    import numpy as np
    h, w = rgb.shape[:2]; lit = rgb.max(axis=2) > 24
    cols = np.where(lit.any(axis=0))[0]; rows = np.where(lit.any(axis=1))[0]
    box = f'content x {cols[0]/w:.2f}-{cols[-1]/w:.2f} y {rows[0]/h:.2f}-{rows[-1]/h:.2f}' if len(cols) and len(rows) else 'content none (black)'
    if lm is None: return f'{w}x{h} {box}; no pose'
    a = np.asarray(lm, dtype=float); xy = a[:, :2] * [w, h]; vis = a[:, 3]
    mid = lambda i, j: (xy[i] + xy[j]) / 2
    sh, hp, an = mid(11, 12), mid(23, 24), mid(27, 28)
    def ang(v): return abs(math.degrees(math.atan2(abs(v[1]), abs(v[0]) + 1e-9)))
    def elbow(s_, e, wr):
        u, v = xy[s_] - xy[e], xy[wr] - xy[e]; return math.degrees(math.acos(max(-1, min(1, u @ v / (np.linalg.norm(u) * np.linalg.norm(v) + 1e-9)))))
    good = vis[[0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]]
    pb = a[vis > 0.5, :2]
    pbox = f'pose x {pb[:,0].min():.2f}-{pb[:,0].max():.2f} y {pb[:,1].min():.2f}-{pb[:,1].max():.2f}' if len(pb) else 'pose box n/a'
    return (f'{w}x{h} {box}; {pbox}; torso {ang(hp - sh):.0f}deg body {ang(an - sh):.0f}deg; elbows L {elbow(11, 13, 15):.0f} R {elbow(12, 14, 16):.0f}; '
            f'vis head {vis[0]:.2f} sh {vis[11]:.2f}/{vis[12]:.2f} wr {vis[15]:.2f}/{vis[16]:.2f} hip {vis[23]:.2f}/{vis[24]:.2f} ank {vis[27]:.2f}/{vis[28]:.2f} min {good.min():.2f}')


def build_parser():
    ap = argparse.ArgumentParser(prog='python -m facetime.worker', add_help=False, description=__doc__.split('\n')[0],
                                 epilog='After these flags comes the LiveKit Agents CLI subcommand: dev (registers under AGENT_NAME with debug logging; restart it '
                                        'after a code change, livekit-agents 1.8.5 has no hot reload), start (production), connect --room R (join one room directly), '
                                        'download-files. The arms-up latency probe is off unless --latency-probe (env RTCOACH_LATENCY_PROBE=1) and never acts during '
                                        'an active set. Env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, AGENT_NAME, PLAN, EVENTS_ONLY, RTCOACH_EVENT_LOG, '
                                        'RTCOACH_CUE_LOG, RTCOACH_LATENCY_PROBE, GEMINI_API_KEY, GEMINI_LIVE_MODEL, GEMINI_VOICE, GEMINI_LANGUAGE.')
    add_arguments(ap)
    for act in ap._actions:                                                 # the perception flag, with the worker's default (env) and what the worker does with it
        if act.dest == 'latency_probe':
            act.default = truthy(os.environ.get('RTCOACH_LATENCY_PROBE'))
            act.help = ('act on the arms-up probe (env RTCOACH_LATENCY_PROBE=1): beep through the cue player and open the voice floor for a few seconds, '
                        'never during an active set; off by default (a jumping jack is an arm raise). Probe events are emitted and logged either way')
    ap.add_argument('--auto', action='store_true', help='auto-detect mode (no plan, no exercise); without it and without --plan/--exercise/PLAN the demo plan runs')
    ap.add_argument('--events-only', action='store_true', default=truthy(os.environ.get('EVENTS_ONLY')), help='publish no audio at all: events only (env EVENTS_ONLY=1)')
    ap.add_argument('--publish-data', action='store_true', help='also publish every event as JSON on the room data channel (off by default)')
    ap.add_argument('--data-topic', default='brodie.events')
    ap.add_argument('--event-log', default=os.environ.get('RTCOACH_EVENT_LOG', os.path.join(DATA, 'tmp', 'worker_events.jsonl')), help='JSONL event log (appended; env RTCOACH_EVENT_LOG)')
    ap.add_argument('--cue-log', default=os.environ.get('RTCOACH_CUE_LOG', os.path.join(DATA, 'tmp', 'worker_cues.jsonl')), help='JSONL log of cues played or dropped (env RTCOACH_CUE_LOG)')
    ap.add_argument('--agent-name', default=os.environ.get('AGENT_NAME', 'brodie-coach'), help='dispatch name (env AGENT_NAME); "" = automatic dispatch to every room (local tests)')
    ap.add_argument('--audio-queue-ms', type=int, default=100, help='AudioSource queue for this worker (100; the Mac saw an underrun at 60 during one-per-second jack counts; coach_agent keeps 60)')
    ap.add_argument('--leave-grace-s', type=float, default=2.0, help='after the bound participant leaves, end the job unless somebody rebinds within this (negative = never end on a leave)')
    ap.add_argument('--no-probe-beep', dest='probe_beep', action='store_false', help='with --latency-probe: open the voice floor on the probe but do not beep')
    ap.add_argument('--video-quality', default='low', choices=['low', 'medium', 'high', 'none'], help='simulcast layer to request when the publisher simulcasts')
    ap.add_argument('--max-s', type=float, default=None, help='leave the room this long after the first video frame (default: stay until the room closes)')
    ap.add_argument('--idle-processes', type=int, default=int(os.environ.get('RTCOACH_IDLE_PROCS', '1')), help='preloaded job processes kept ready (models loaded in prewarm)')
    ap.add_argument('--voice', default=os.environ.get('VOICE', 'off'), choices=['off', 'gemini'], help='conversational layer between sets: gemini = Gemini Live through the cue track (facetime/voice.py; env VOICE)')
    ap.add_argument('--voice-model', default=os.environ.get('GEMINI_LIVE_MODEL') or None, help='Gemini Live model id (env GEMINI_LIVE_MODEL; default facetime.voice.DEFAULT_MODEL)')
    ap.add_argument('--voice-name', default=os.environ.get('GEMINI_VOICE', 'Puck'), help='Gemini Live voice (env GEMINI_VOICE; Puck is the cue bank voice)')
    ap.add_argument('--persona', default=os.environ.get('PERSONA_FILE', os.path.join(STARTER_DIR, 'persona.md')), help='the voice persona prompt file (starter/persona.md)')
    ap.add_argument('--handlers', default=os.environ.get('HANDLERS_FILE') or None, help='a module with on_event(event, say_now, ask_voice); default starter/handlers.py whenever that file exists, in every mode '
                                                                                        '(without --voice gemini, ask_voice returns None); --handlers none loads nothing')
    ap.add_argument('--log-caller', action='store_true', help='also emit and log the caller\'s transcribed turns as voice events (role caller); off by default: the caller\'s words never leave the model session (docs/STARTER_README.md section 8)')
    ap.add_argument('--plan-file', default=os.environ.get('PLAN_FILE', os.path.join(STARTER_DIR, 'plan.txt')), help='the plan when neither --plan nor PLAN is given (starter/plan.txt); '
                                                                                                                      'with --perception off the file is appended to the persona as free text (a recipe)')
    ap.add_argument('--perception', default=os.environ.get('PERCEPTION', 'on'), choices=['on', 'off'], help='off = no pose model, no rep counter, no session script (env PERCEPTION): the worker '
                                                                                                           'joins, binds to the caller, starts the voice and emits one synthetic session {state: open} event; the floor is then always open')
    ap.add_argument('--floor', default=os.environ.get('FLOOR') or None, choices=['gated', 'open'], help='gated = the voice speaks between sets only (the default with perception on); '
                                                                                                        'open = always allowed to speak, nothing is ever cut (the default with --perception off; env FLOOR)')
    ap.add_argument('--vision', action='store_true', default=truthy(os.environ.get('VISION')), help='with --voice gemini: tee the caller\'s video into the model session at --vision-fps (env VISION=1)')
    ap.add_argument('--vision-fps', type=float, default=float(os.environ.get('VISION_FPS', '1') or 1), help='frames per second handed to the model with --vision (default 1, at most 2; JPEG per frame)')
    ap.add_argument('--avatar', dest='avatar', action='store_true', default=truthy(os.environ.get('AVATAR', '1')), help='publish a "coach-video" track so the '
                    "FaceTime caller sees Brodie: the push-up mirror (--mirror) or his plain face (facetime/avatar.py); mouth moves while a cue plays "
                    '(default on; env AVATAR=0 turns it off)')
    ap.add_argument('--no-avatar', dest='avatar', action='store_false', help='publish no video track')
    ap.add_argument('--avatar-fps', type=float, default=float(os.environ.get('AVATAR_FPS', '12') or 12), help='coach-video frames per second (default 12)')
    ap.add_argument('--mirror-fps', type=float, default=float(os.environ.get('MIRROR_FPS', '15') or 15),
                    help="push-up mirror frames per second (default 15, the bridge's rate: every new caller frame is shown, the skeleton "
                         'updates at the pose rate; env MIRROR_FPS)')
    mirror_env = os.environ.get('MIRROR')
    ap.add_argument('--mirror', dest='mirror', action='store_true', default=(None if mirror_env in (None, '') else truthy(mirror_env)),
                    help="coach-video = the push-up mirror (facetime/pushup_mirror.py): the caller's own video with the judge's form skeleton, the "
                         'camera-angle status, the valid count and the rep verdicts (default: on in competition mode; env MIRROR=1/0)')
    ap.add_argument('--no-mirror', dest='mirror', action='store_false', help="coach-video = Brodie's plain face")
    ap.add_argument('-h', '--help', action='store_true', help='show this help and exit')
    return ap


def perception_off(a):
    return str(getattr(a, 'perception', 'on') or 'on').strip().lower() == 'off'


def read_plan_text(path):
    """--perception off: the plan file as free text (a recipe, a checklist), stripped; empty or missing -> None."""
    if not path: return None
    try:
        with open(path) as f: return f.read().strip() or None
    except OSError:
        return None


# Client calls from the web app's /go/<client link> join a room named client-<clients.id>-<random> (web/lib/livekit.ts):
# that call loads this client's active assignment and saves the session to them. Any other room uses DEMO_CLIENT_ID as before.
CLIENT_ROOM_RE = re.compile(r'^client-([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})-', re.I)


def client_for_room(room_name):
    """The clients.id encoded in a client call's room name, else None."""
    m = CLIENT_ROOM_RE.match(room_name or '')
    return m.group(1).lower() if m else None


def call_client_id(a):
    """Whose call this is: the room's client, else the DEMO_CLIENT_ID env (single-client demo setups); nobody for a line's walk-in
    caller (a.guest: no reservation, the demo workout, nothing saved)."""
    if getattr(a, 'guest', False): return None
    return getattr(a, 'client_id', None) or os.environ.get('DEMO_CLIENT_ID')


def resolve_mode(a, *, load_client=True):
    """--plan, else PLAN, else client assignment, else starter/demo; --exercise and --auto override.
    load_client=False defers assignment resolution for registration/prewarm (never chooses a fallback).
    Handlers: --handlers PATH, else starter/handlers.py whenever it exists (every mode, so a team's on_event runs with say_now even
    without the voice), `none` for nothing."""
    if perception_off(a):                       # no session script: the plan is free text for the persona (a recipe), kept across the two parses
        a.plan_text = getattr(a, 'plan_text', None) or a.plan or os.environ.get('PLAN') or read_plan_text(getattr(a, 'plan_file', None))
        a.plan = None; a.exercise = None; a.floor = getattr(a, 'floor', None) or 'open'
    else:
        a.plan_text = None; a.floor = getattr(a, 'floor', None) or 'gated'
        if is_competition(): a.plan = None; a.exercise = 'pushups'      # competition: one push-up set, never a client assignment
        elif a.exercise: a.plan = None
        elif getattr(a, 'auto', False): a.plan = None
        else:
            if not a.plan and not os.environ.get('PLAN') and call_client_id(a):
                # Resolve on each call, never while registering or warming a process.
                # A missing assignment must not turn into an unrelated demo workout.
                if load_client:
                    from facetime.plan_loader import AssignmentUnavailable, load_assignment
                    a.assignment = load_assignment(call_client_id(a))
                    if not a.assignment:
                        raise AssignmentUnavailable('Client assignment unavailable; check the active day and database connection.')
                    a.plan = a.assignment['plan']
                    print('[plan] loaded active client assignment', flush=True)
            else:
                a.plan = a.plan or os.environ.get('PLAN') or read_plan_file(getattr(a, 'plan_file', None)) or DEFAULT_PLAN
    a.vision_fps = max(0.1, min(float(getattr(a, 'vision_fps', 1.0) or 1.0), 2.0))
    h = getattr(a, 'handlers', None)
    if h and str(h).strip().lower() in ('none', 'off'): a.handlers = 'none'          # kept as the string: the job process resolves the flags again
    elif not h and os.path.exists(os.path.join(STARTER_DIR, 'handlers.py')): a.handlers = os.path.join(STARTER_DIR, 'handlers.py')
    return a


def handlers_path(a):
    """The handlers module to load, None for --handlers none / nothing."""
    h = getattr(a, 'handlers', None)
    return None if not h or str(h).strip().lower() in ('none', 'off') else h


def read_plan_file(path):
    """starter/plan.txt: one line like "squats:10,pushups:8" (comments with #); empty or missing -> None."""
    if not path: return None
    try:
        lines = [l.strip() for l in open(path) if l.strip() and not l.lstrip().startswith('#')]
        return ','.join(lines) if lines else None
    except OSError:
        return None


def load_args(*, load_client=True, client_id=None, guest=False):
    """The flags main() parsed, from the environment (a job process is a fresh interpreter); defaults when run without main().
    client_id: the client this call belongs to (client_for_room), else DEMO_CLIENT_ID applies."""
    a = build_parser().parse_args([])
    try: d = json.loads(os.environ.get(ARGS_ENV) or '{}')
    except ValueError: d = {}
    for k, v in d.items(): setattr(a, k, v)
    a.client_id = client_id; a.guest = guest
    return resolve_mode(a, load_client=load_client)


def parse_metadata(md):
    """Job metadata is JSON from the dispatcher (Chert: chert_warm, chert_call, media); anything else is logged and ignored."""
    if not md: return {}
    try:
        d = json.loads(md); return d if isinstance(d, dict) else {'metadata': d}
    except ValueError:
        return {'metadata_raw': md[:200]}


def prewarm(proc: JobProcess):
    """Runs in each job process before any job: models, trigger, thresholds and (unless events-only) the cue bank."""
    a = load_args(load_client=False); cfg = Config.from_args(a); t = time.time()
    proc.userdata['args'] = a; proc.userdata['cfg'] = cfg
    if perception_off(a):                                      # no pose model, no classifier: nothing to load but the bank
        proc.userdata['pipe'] = None
    else:
        proc.userdata['pipe'] = build_pipeline(cfg)
    if not a.events_only:
        from facetime.audio_out import CueBank
        proc.userdata['bank'] = CueBank()
    if perception_off(a):
        print(f'[worker] prewarm: loaded in {time.time() - t:.1f} s (perception OFF: no pose model, no session script; voice {a.voice}, vision {"on" if a.vision else "off"}, '
              f'floor {a.floor}, audio {"OFF (events only)" if a.events_only else "cue bank"})', flush=True)
    else:
        print(f'[worker] prewarm: loaded in {time.time() - t:.1f} s (pose {proc.userdata["pipe"].pose_variant}, counter {cfg.counter}, trigger {proc.userdata["pipe"].trigger_path or "off"}, '
              f'mode {cfg.mode} ({a.plan or a.exercise or "auto-detect"}), audio {"OFF (events only)" if a.events_only else "cue bank"})', flush=True)


def describe_mode(a):
    """The mode words for the console lines: plan/single/auto with perception, 'voice' without."""
    if perception_off(a): return 'voice (perception off' + (', vision on' if getattr(a, 'vision', False) else '') + f', floor {a.floor})'
    if not a.plan and not a.exercise and not getattr(a, 'auto', False) and os.environ.get('DEMO_CLIENT_ID'):
        return 'client assignment (resolved at call start)'
    return f'{"plan" if a.plan else ("single" if a.exercise else "auto")} ({a.plan or a.exercise or "auto-detect"})'


async def entrypoint(ctx: JobContext):
    ud = ctx.proc.userdata
    from facetime.plan_loader import AssignmentUnavailable
    try:
        # Re-read the active assignment after prewarm; only the model/bank are cached.
        room_name = getattr(getattr(getattr(ctx, 'job', None), 'room', None), 'name', None)
        room_client = client_for_room(room_name)
        if room_client: print(f'[worker] client call: room {room_name!r} -> client {room_client}', flush=True)
        if line_id(): a = await asyncio.to_thread(load_args, load_client=False)   # a line: the client is matched at the bind (_line_start)
        elif room_client: a = await asyncio.to_thread(load_args, client_id=room_client)
        else: a = await asyncio.to_thread(load_args)
    except AssignmentUnavailable:
        log.warning('Client assignment unavailable; refusing to start a demo workout')
        ctx.shutdown(reason='client assignment unavailable')
        return
    cfg = Config.from_args(a)
    pipe = ud.pop('pipe', None)
    if pipe is None and not perception_off(a): pipe = build_pipeline(cfg)   # single use: a Perception owns it until the job ends
    bank = ud.get('bank')
    if bank is None and not a.events_only:
        from facetime.audio_out import CueBank
        bank = CueBank()
    job = CoachJob(ctx, a, cfg, pipe, bank, parse_metadata(ctx.job.metadata))
    await job.run()


class CoachJob:
    """One dispatched job: the room, the optional cue player, the Perception and its feed thread, the event sinks."""
    def __init__(self, ctx, a, cfg, pipe, bank, md):
        self.ctx = ctx; self.a = a; self.cfg = cfg; self.pipe = pipe; self.bank = bank; self.md = md
        self.room = ctx.room; self.loop = None
        self.warm = bool(md.get('chert_warm'))
        self.events = asyncio.Queue()                 # every event, for an in-process conversational layer
        self.player = None; self.player_task = None; self.cue_log = None
        self.per = None; self.thread = None; self.stop = threading.Event(); self.done = asyncio.Event(); self.closed = False
        self.latest = None; self.seq = 0; self.processed = 0; self.dropped = 0; self.idle = 0; self.frame_event = threading.Event()
        self.video_task = None; self.bound = None; self.call_id = None; self.bridge_call_id = None; self.frame_size = None; self.first_frame_t = None
        self.worker_error = None; self.cues_played = 0; self.ts_mode = None
        self.voice = None; self.voice_seq = 0; self.event_writer = None; self.consumer_tasks = []
        self.end_reason = None; self.leave_task = None; self.ctx_shutdown_called = False; self.t_end = None
        self.session_state = None; self.probes_ignored = 0        # the probe (--latency-probe) never beeps or opens the floor during an active set
        self.voice_mode = perception_off(a)                       # --perception off: no Perception; the worker emits its own session/status events
        self.recap = None                                         # facetime/call_recap.py: save the session + heat map card (DEMO_CLIENT_ID)
        self.t0 = time.monotonic(); self.ev_seq = 0; self.vision = None; self.vision_logged = False; self.session_opened = False; self.open_task = None
        # competition (CHALLENGE_MODE=competition): challenge.worker CompetitionCall per call; all its methods run on the loop
        self.competition = is_competition() and not self.voice_mode
        self.comp = None; self.comp_task = None; self.comp_client = None
        self.clock = time.time; self.sleep = asyncio.sleep        # the controller's wall clock and sleep (tests replace them)
        self.per_wall0 = None                                     # wall time of the Perception event clock's zero
        self.pending_windows = collections.deque()                # ('win', t0, t1) event clock / ('thr', thresholds): applied by the feed thread
        self.feed_busy = False; self.last_proc_wall = None        # job health
        self.feed_lock = threading.Lock(); self.feed_sealed = False   # the feed thread processes a frame only under the lock and
                                                                  # stops once sealed: drain_feed() then knows no rep can follow
        self.hb_task = None
        self.avatar_task = None
        self.mirror_in = None; self.mirror_live = False           # newest (rgb, landmarks, seq, t_mono) for the push-up mirror (feed thread writes)
        self.reveal_frames = None                                 # challenge.worker.reveal_video.RevealFrames (REVEAL_MODE=video)
        self.mirror_state = None                                  # facetime.pushup_mirror.MirrorState (loop thread)
        self.prep = None                                          # facetime.frameprep.FramePrep: content crop + orientation lock (feed thread)
        self.hangup_mode = (os.environ.get('HANGUP_MODE') or 'unverified').strip()
        self.novideo_task = None                                  # P0-3 watch of a bridge caller that publishes no video
        self.room_deleted = None                                  # HANGUP_MODE=delete_room: True/False once the delete was tried
        self.lk_api = None                                        # () -> livekit.api.LiveKitAPI (tests replace it)
        # A FaceTime line worker (BRODIE_LINE, facetime/lines.py): the client is only known once a call arrives, so the plan, the voice
        # and Perception start at the bind (start_session), after the line's reservation is taken.
        self.line = None if self.voice_mode else line_id(); self.line_claim = None; self.line_task = None; self.session_started = False
        self.line_bound = False

    # ---- lifecycle ----
    async def run(self):
        self.loop = asyncio.get_running_loop(); ctx = self.ctx; a = self.a
        ctx.add_shutdown_callback(self.aclose)
        if not a.events_only:
            from facetime.audio_out import CuePlayer
            self.player = CuePlayer(bank=self.bank, on_record=self.log_cue, queue_ms=a.audio_queue_ms)
            os.makedirs(os.path.dirname(os.path.abspath(a.cue_log)) or '.', exist_ok=True); self.cue_log = open(a.cue_log, 'a')
        if not self.line and (getattr(a, 'voice', 'off') == 'gemini' or handlers_path(a)):
            self.voice = self.build_voice()
        self.room.on('track_subscribed', self.on_track_subscribed)
        self.room.on('participant_connected', self.on_participant_connected)
        self.room.on('participant_disconnected', self.on_participant_disconnected)
        self.room.on('disconnected', self.on_room_disconnected)
        try:
            await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
        except BaseException as e:
            if isinstance(e, asyncio.CancelledError): raise
            print(f'[worker] job {ctx.job.id}: connect failed ({type(e).__name__}: {str(e)[:120]}): the room went away before the peer connection completed '
                  f'(a doctor or warm room torn down early); leaving', flush=True)
            self.end_reason = 'connect failed'; await self.aclose(); self.shutdown_ctx(self.end_reason); return
        md_note = metadata_note(self.md, redact=self.competition)
        print(f'[worker] job {ctx.job.id}: joined room {self.room.name!r} as {self.room.local_participant.identity!r} (agent {a.agent_name!r}); '
              f'mode {describe_mode(a)}; audio {"OFF (events only)" if a.events_only else "cue player"}; '
              f'metadata: {md_note}; participants {list(self.room.remote_participants)}', flush=True)
        if self.player is not None:
            if not await self.publish_audio():                    # P1-3: a job with no audio track is useless to a caller: end it
                self.end_reason = 'audio publish failed'; await self.aclose(); self.shutdown_ctx(self.end_reason); return
            self.player_task = asyncio.create_task(self.player.run())
            print(f'[worker] published audio track {AUDIO_TRACK_NAME}', flush=True)
        if getattr(a, 'avatar', False):
            self.avatar_task = asyncio.create_task(self.avatar_loop(), name='avatar')
        if self.warm:
            print('[worker] warm job (chert_warm): no caller; staying joined, nothing is said until a participant publishes video' + (' or audio' if self.voice_mode else ''), flush=True)
        if self.line:
            print(f'[line] line {self.line!r}: the workout starts when a call arrives (the caller is matched to the line\'s reservation)', flush=True)
        else:
            self.start_session()
        for p in list(self.room.remote_participants.values()):   # a caller already in the room when the job joined
            self.watch_no_video(p)
        await self.done.wait()
        reason = self.end_reason or (f'perception error: {self.worker_error!r}' if self.worker_error is not None else 'done')
        await self.aclose(); self.shutdown_ctx(reason)

    def start_session(self):
        """Events, Perception (or the voice-mode status loop), the feed thread, the consumers and the voice: at join, or at the bind on a line."""
        a = self.a; self.session_started = True
        if self.voice_mode:                                       # no Perception: the worker's own session/status events, logged the same way
            from facetime.perception import JsonlWriter
            self.event_writer = JsonlWriter(a.event_log, extra=dict(room=self.room.name, call_id=self.call_id, job=self.ctx.job.id))
        else:
            # competition: the controller's cues are the only audio (the demo session would count and correct invalid reps aloud)
            self.per = Perception(self.cfg, pipe=self.pipe, say=(self.say_from_worker if self.player is not None and not self.competition else None),
                                  clip_s=(self.bank.duration if self.bank is not None else None))
            self.per_wall0 = time.time() - (time.monotonic() - self.per.t0)
            self.per.on_event(self.on_event)
            self.event_writer = self.per.log_to(a.event_log, extra=dict(room=self.room.name, call_id=self.call_id, job=self.ctx.job.id))
            if self.player is not None:
                self.per.audio_stats = lambda: dict(underruns=self.player.underruns, cues_played=self.cues_played, cues_dropped=self.player.n_dropped)
        print(f'[worker] events (schema v{EVENT_SCHEMA_VERSION}) -> {a.event_log}' + (f' and data topic {a.data_topic!r}' if a.publish_data else ''), flush=True)
        if self.voice_mode:
            self.consumer_tasks = [asyncio.create_task(self._status_loop(), name='status-loop')]
        else:
            self.thread = threading.Thread(target=self.feed, daemon=True, name='perception-feed'); self.thread.start()
            self.consumer_tasks = []
        self.consumer_tasks += [asyncio.create_task(fn(self), name=f'consumer-{fn.__name__}') for fn in CONSUMERS]
        if self.voice is not None:
            self.consumer_tasks.append(asyncio.create_task(self.voice.run(), name='consumer-voice'))

    async def publish_audio(self):
        """Publish the cue track: AUDIO_PUBLISH_ATTEMPTS tries 0.5 s apart. False (logged loudly) when every try failed:
        the job then ends so no caller lands in a room whose agent cannot speak (Chert's next warm room gets a new job)."""
        for i in range(1, AUDIO_PUBLISH_ATTEMPTS + 1):
            try:
                await self.room.local_participant.publish_track(self.player.track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
                return True
            except Exception as e:
                log.error('audio track publish failed (attempt %d/%d): %r', i, AUDIO_PUBLISH_ATTEMPTS, e)
                print(f'[worker] audio track publish failed (attempt {i}/{AUDIO_PUBLISH_ATTEMPTS}): {type(e).__name__}: {e}', flush=True)
            if i < AUDIO_PUBLISH_ATTEMPTS: await asyncio.sleep(0.5)
        log.critical('ALERT audio_publish_failed: job %s room %r has no cue track; ending the job', self.ctx.job.id, self.room.name)
        print(f'[worker] ERROR: could not publish the cue audio track after {AUDIO_PUBLISH_ATTEMPTS} attempts: ending job {self.ctx.job.id}', flush=True)
        return False

    def end(self, reason):
        """End the job (event loop): run() wakes, cleans up and returns, then tells the framework (shutdown_ctx)."""
        if self.end_reason is None: self.end_reason = reason
        try:
            if getattr(self, 'comp', None) is not None: self.comp.cancel_reveal()
        except Exception as e: log.debug('cancel_reveal: %r', e)
        if self.t_end is None: self.t_end = time.monotonic()
        self.done.set()

    def shutdown_ctx(self, reason):
        if self.ctx_shutdown_called: return
        self.ctx_shutdown_called = True
        try: self.ctx.shutdown(reason=reason)
        except Exception as e: log.debug('ctx.shutdown: %r', e)

    def on_room_disconnected(self, *args):
        try: why = rtc.DisconnectReason.Name(args[0]) if args else 'unknown'
        except Exception: why = str(args[0]) if args else 'unknown'
        print(f'[worker] room disconnected ({why}): leaving', flush=True); self.end(f'room disconnected ({why})')

    def mirror_wanted(self):
        m = getattr(self.a, 'mirror', None)
        return bool(getattr(self, 'competition', False)) if m is None else bool(m)

    def mirror_thresholds(self):
        """The live judge thresholds (the pipeline judge's, else its configured ones over the defaults): the mirror's
        green == passes this judge."""
        pipe = getattr(self, 'pipe', None)
        j = getattr(pipe, 'judge', None)
        if j is not None and getattr(j, 'thr', None): return j.thr
        from challenge.judge.gates import merged_thresholds
        return merged_thresholds(getattr(pipe, 'judge_thr', None))

    def mirror_rep(self, valid, reasons, in_challenge):
        """Loop thread: a judged rep for the on-screen count and stamp. Only reps the scoring counts add to the count
        (valid and not inside a liveness challenge; challenge.scoring.rep_points); challenge reps show nothing."""
        if in_challenge: return
        try:
            st = self.mirror_state
            if st is None:
                from facetime.pushup_mirror import MirrorState
                st = self.mirror_state = MirrorState()
            st.rep(bool(valid), list(reasons or []), now=time.monotonic(), counts=True)
        except Exception:
            log.exception('mirror rep update failed')                # the video is cosmetic: never the event path

    def _mirror_tick_state(self, now):
        """Loop thread: the cue playing, the count timer; returns a snapshot the render thread can read safely."""
        import dataclasses
        from facetime.pushup_mirror import MirrorState
        st = self.mirror_state
        if st is None: st = self.mirror_state = MirrorState()
        rec = self.player.playing if self.player is not None else None
        st.speaking = rec is not None
        if isinstance(rec, dict) and rec.get('intent') != 'probe' and rec.get('text'):
            if rec.get('text') != st.cue or now - st.cue_t > 1.0: st.say(rec['text'], now=now)
        comp = getattr(self, 'comp', None); t0 = getattr(comp, 't0', None)
        st.time_left_s = None
        if t0 is not None and getattr(comp, 'count_s', None):
            st.time_left_s = max(0.0, float(t0) + float(comp.count_s) - time.time())
        return dataclasses.replace(st, verdict_reasons=list(st.verdict_reasons))

    async def avatar_loop(self):
        """The "coach-video" track; Chert's bridge shows it to the FaceTime caller. With the mirror (mirror_wanted()): the
        caller's newest frame with the judge's form skeleton, camera status, valid count and verdicts (an idle card
        until frames arrive, or when they stop for 2 s); otherwise Brodie's plain face. Rendered off the loop. A mirror
        failure never touches the call: logged, that frame is the plain face, and after 10 failures in a row the mirror
        is off for the call."""
        try:
            from facetime.avatar import Avatar
            av = await asyncio.to_thread(Avatar); fps = max(1.0, float(getattr(self.a, 'avatar_fps', 12.0) or 12.0))
            renderer = None
            if self.mirror_wanted():
                try:
                    from facetime.pushup_mirror import PushupMirror
                    renderer = await asyncio.to_thread(PushupMirror)
                except Exception as e:
                    log.exception('push-up mirror unavailable'); print(f'[worker] push-up mirror unavailable ({e!r}): plain avatar', flush=True)
            if renderer is not None:
                from facetime.pushup_mirror import W as VW, H as VH
                self.mirror_live = True; kind = 'push-up mirror'; bitrate = MIRROR_BITRATE
                fps = max(1.0, float(getattr(self.a, 'mirror_fps', 15.0) or 15.0))
            else:
                VW, VH = av.W, av.H; kind = 'avatar'; bitrate = 600_000
            self.video_size = (VW, VH)
            source = rtc.VideoSource(VW, VH)
            track = rtc.LocalVideoTrack.create_video_track('coach-video', source)
            await self.room.local_participant.publish_track(track, rtc.TrackPublishOptions(
                source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False, video_encoding=rtc.VideoEncoding(max_framerate=int(round(fps)), max_bitrate=bitrate)))
            print(f'[worker] published video track coach-video {VW}x{VH} at {fps:g} fps ({kind})', flush=True)
            period = 1.0 / fps; loop = asyncio.get_running_loop(); next_t = loop.time()
            fails = [0, 0]                                                 # in a row, total
            stats = dict(n=0, ms=0.0, t=time.monotonic())
            while not self.stop.is_set():
                speaking = self.player is not None and self.player.playing is not None
                rf = getattr(self, 'reveal_frames', None)
                rv_land = (rf is not None and renderer is not None and getattr(rf, 'landscape_size', None) is not None
                           and bool(getattr(self, 'mirror_landscape', False)))       # sideways phone: landscape card
                rv_img = rf.current_frame(rv_land) if rf is not None else None
                if rv_img is not None:                                         # reveal (C7.v): the whole card, never the mirror
                    frame = await asyncio.to_thread(self._reveal_frame, rv_img, rf.landscape_size if rv_land else (VW, VH))
                    source.capture_frame(frame)
                    next_t = loop.time() + 1.0 / IDLE_CARD_FPS
                    await asyncio.sleep(max(0.0, next_t - loop.time())); continue
                if renderer is not None:
                    now = time.monotonic(); st = self._mirror_tick_state(now)
                    snap = self.mirror_in
                    if snap is not None and now - snap[3] > 2.0: snap = None; self.mirror_in = None      # frames stopped: idle card
                    lat = getattr(self, 'latest', None)                            # a caller frame newer than the pose's: show it
                    newer = lat[0] if (snap is not None and lat is not None and lat[4] > snap[2]) else None
                    landscape = snap is not None and bool(getattr(self, 'mirror_landscape', False))   # idle card: portrait
                    frame = await asyncio.to_thread(self._mirror_frame, renderer, av, snap, st, now, fails, stats, newer, landscape)
                    if fails[0] >= 10:
                        print(f'[worker] push-up mirror failed {fails[0]} frames in a row: plain avatar for the rest of the call', flush=True)
                        renderer = None; self.mirror_live = False; self.mirror_in = None
                    if stats['n'] and now - stats['t'] >= 60.0:
                        print(f"[worker] mirror render {stats['ms'] / stats['n']:.1f} ms/frame over {stats['n']} frames, {fails[1]} failures", flush=True)
                        stats.update(n=0, ms=0.0, t=now)
                else:
                    size = (VW, VH)
                    frame = await asyncio.to_thread(self._avatar_frame, av, speaking, size)
                source.capture_frame(frame)
                if renderer is not None and self.mirror_in is None:            # no caller video (warm room / idle card): a few fps is
                    next_t = loop.time() + max(period, 1.0 / IDLE_CARD_FPS)    # plenty and frees the CPU the next call's pose needs
                else:
                    next_t += period
                await asyncio.sleep(max(0.0, next_t - loop.time()))
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f'[worker] avatar stopped: {e!r}', flush=True)
        finally:
            self.mirror_live = False; self.mirror_in = None

    @staticmethod
    def _reveal_frame(img, size):
        """The reveal image as an I420 frame of `size` (letterboxed whole by the provider; resized only if it differs)."""
        if img.size != tuple(size): img = img.resize(tuple(size))
        return rtc.VideoFrame(size[0], size[1], rtc.VideoBufferType.RGB24, img.convert('RGB').tobytes()).convert(rtc.VideoBufferType.I420)

    @staticmethod
    def _avatar_frame(av, speaking, size):
        """Brodie's plain face as an I420 frame of `size` (the mirror's size after a fallback)."""
        buf = av.frame_bytes(speaking=speaking)
        if size != (av.W, av.H):
            import numpy as np, cv2
            img = cv2.resize(np.frombuffer(buf, np.uint8).reshape(av.H, av.W, 3), size, interpolation=cv2.INTER_LINEAR)
            buf = img.tobytes()
        return rtc.VideoFrame(size[0], size[1], rtc.VideoBufferType.RGB24, buf).convert(rtc.VideoBufferType.I420)

    def _mirror_frame(self, renderer, av, snap, st, now, fails, stats, newer=None, landscape=False):
        """Render thread: one mirror frame (I420); on any error the plain face for this frame. newer: a caller VideoFrame
        that arrived after snap's (the pose's) frame: shown with snap's skeleton when the feed's crop + rotation fit it.
        landscape: the caller's phone is sideways -> a 1280x720 frame on the same track (the size changes mid-stream: the
        native VideoSource passes any frame size through and WebRTC reconfigures the encoder, no republish)."""
        from facetime.pushup_mirror import W as VW, H as VH, LW, LH
        if landscape: VW, VH = LW, LH
        t0 = time.perf_counter()
        try:
            if snap is None: img = renderer.render(None, None, self.mirror_thresholds(), st, now=now)
            else:
                rgb = snap[0]; prep = getattr(self, 'prep', None)
                if newer is not None and prep is not None:
                    up = prep.apply(frame_to_rgb(newer))
                    if up is not None and up.shape == rgb.shape: rgb = up
                img = renderer.render(rgb, snap[1], self.mirror_thresholds(), st, now=now, seq=snap[2], **({'landscape': True} if landscape else {}))
            fails[0] = 0
            stats['n'] += 1; stats['ms'] += (time.perf_counter() - t0) * 1000
            ih, iw = img.shape[:2]
            return rtc.VideoFrame(iw, ih, rtc.VideoBufferType.RGB24, img.tobytes()).convert(rtc.VideoBufferType.I420)
        except Exception as e:
            fails[0] += 1; fails[1] += 1
            if fails[1] == 1 or fails[1] % 50 == 0:
                log.exception('push-up mirror render failed'); print(f'[worker] push-up mirror render failed ({fails[1]} so far): {e!r}', flush=True)
            return self._avatar_frame(av, st.speaking, (VW, VH))

    async def _leave_grace(self):
        await asyncio.sleep(max(0.0, self.a.leave_grace_s))
        self.leave_task = None
        if self.bound is None and not self.closed:
            print(f'[worker] caller left and nobody rebound within {self.a.leave_grace_s:g} s: leaving', flush=True); self.end('caller left')

    def room_connected(self):
        try: return self.room.connection_state == rtc.ConnectionState.CONN_CONNECTED
        except Exception: return True

    async def aclose(self, *_):
        """Idempotent cleanup (run() at its end, and the framework's shutdown callback): every wait is bounded, nothing blocks the loop."""
        if self.closed: return
        self.closed = True; self.stop.set(); self.done.set(); t0 = time.monotonic()
        if self.t_end is None: self.t_end = t0
        if self.leave_task is not None: self.leave_task.cancel()
        if self.open_task is not None and not self.open_task.done(): self.open_task.cancel()
        if self.novideo_task is not None and not self.novideo_task.done(): self.novideo_task.cancel()
        if self.line_task is not None and not self.line_task.done(): self.line_task.cancel()
        for t in getattr(self, 'consumer_tasks', []): t.cancel()
        if self.avatar_task is not None: self.avatar_task.cancel()
        if self.comp is not None or self.comp_task is not None: await self.close_competition()   # commit before the teardown
        recap_close = asyncio.create_task(self.recap.aclose()) if self.recap is not None else None   # hang-up save runs alongside the teardown
        if self.video_task is not None and not self.video_task.done():                 # closes the VideoStream (read_video's finally)
            self.video_task.cancel()
            try: await asyncio.wait_for(asyncio.gather(self.video_task, return_exceptions=True), 1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError): pass
        if self.thread is not None and self.thread.is_alive():                            # the feed loop polls stop every 50 ms
            await asyncio.get_running_loop().run_in_executor(None, self.thread.join, 1.0)
        if getattr(self, 'prep', None) is not None and (self.thread is None or not self.thread.is_alive()):   # the probe pose landmarker (feed thread gone)
            try: self.prep.close()
            except Exception as e: log.debug('frame prep close: %r', e)
        if self.comp is not None and getattr(self.comp, 'commit_deferred', False): await self.finish_deferred_commit()
        if self.voice is not None:
            try: await asyncio.wait_for(self.voice.aclose(), 3)
            except Exception as e: log.warning('voice close: %r', e)
        if self.player is not None:
            if self.room_connected():
                for _ in range(15):                                                       # let the cue in flight finish (max 1.5 s)
                    if not self.player.playing and self.player.pending is None: break
                    await asyncio.sleep(0.1)
            self.player.stop()
            if self.player_task is not None:
                try: await asyncio.wait_for(asyncio.gather(self.player_task, return_exceptions=True), 1.0)
                except (asyncio.TimeoutError, asyncio.CancelledError): self.player_task.cancel()
            src = getattr(self.player, 'source', None)                                    # drop the AudioSource's FFI handle here, not in a __del__
            if hasattr(src, 'aclose'):
                try: await asyncio.wait_for(src.aclose(), 1.0)
                except Exception as e: log.debug('audio source close: %r', e)
        if self.per is not None: s = self.per.summary(); self.per.close()
        else:
            s = {}
            if self.voice_mode:
                s = dict(mode='voice', events=self.ev_seq, session_opened=self.session_opened)
                if self.vision is not None: s.update(vision_offered=self.vision.n_offered, vision_sent=self.vision.n_sent, vision_early=self.vision.n_early)
                if self.event_writer is not None:
                    try: self.event_writer.close()
                    except Exception as e: log.debug('event writer close: %r', e)
            if self.pipe is not None:                                                   # connect failed before Perception took the pipe: close the
                try: self.pipe.close()                                                  # pose landmarker here (an unclosed one hangs in __del__)
                except Exception as e: log.debug('pipe close: %r', e)
        if self.cue_log: self.cue_log.close()
        if recap_close is not None:                                                    # bounded inside (12 s); a mid-plan hang-up still saves
            await asyncio.gather(recap_close, return_exceptions=True)
        if self.line and self.line_bound:                                              # the call is over: free the line (after its cooldown)
            await asyncio.to_thread(release_line, self.line, (self.line_claim or {}).get('claim_id'))
        print(f'[worker] job {self.ctx.job.id} done ({self.end_reason or "shutdown"}; cleanup {1000 * (time.monotonic() - t0):.0f} ms, '
              f'{1000 * (time.monotonic() - self.t_end):.0f} ms after the end trigger): frames received {self.seq}, processed {self.processed}, dropped {self.dropped}, idle ticks {self.idle}; {s}', flush=True)

    # ---- video ----
    def on_track_subscribed(self, track, pub, participant):
        own = participant.kind == AGENT_KIND or participant.identity == self.room.local_participant.identity
        if track.kind != rtc.TrackKind.KIND_VIDEO:
            # --perception off: a caller with audio and no video (an audio-only call) is still a caller; the model session starts on it
            if track.kind == rtc.TrackKind.KIND_AUDIO and self.voice_mode and self.bound is None and not own and not self.closed:
                self.bind(participant, f'audio {pub.name!r} (no video yet)')
            return
        if own:
            print(f'[worker] video from agent participant {participant.identity!r} ignored', flush=True); return
        if self.video_task is not None and not self.video_task.done():
            print(f'[worker] video track {pub.name!r} from {participant.identity!r} ignored: already bound to {self.bound!r}', flush=True); return
        self.bind(participant, f'video {pub.name!r} {pub.width}x{pub.height}, simulcast {getattr(pub, "simulcasted", False)}')
        if self.a.video_quality != 'none' and getattr(pub, 'simulcasted', False):
            try: pub.set_video_quality(rtc.VideoQuality.Value('VIDEO_QUALITY_' + self.a.video_quality.upper()))
            except Exception as e: print(f'[worker] set_video_quality failed: {e}', flush=True)
        self.video_task = asyncio.create_task(self.read_video(track))

    async def _line_start(self, participant):
        """A call arrived on this line: take the line's reservation (the client who tapped Start workout), load their day, start.
        No reservation, or no day assigned: the demo workout, saved to nobody."""
        from facetime.plan_loader import AssignmentUnavailable
        try:
            self.line_claim = await asyncio.to_thread(take_claim, self.line)
            cid = (self.line_claim or {}).get('client_id')
            try:
                a = await asyncio.to_thread(load_args, client_id=cid) if cid else await asyncio.to_thread(load_args, guest=True)
                print(f'[line] line {self.line!r}: ' + (f'reserved by client {cid}' if cid else 'walk-in caller (no reservation): demo workout, not saved'), flush=True)
            except AssignmentUnavailable:
                print(f'[line] line {self.line!r}: client {cid} has no workout assigned: demo workout, not saved', flush=True)
                a = await asyncio.to_thread(load_args, guest=True)
            if self.closed: return
            self.a = a; self.cfg = Config.from_args(a); self.warm = False          # a caller is here, whatever the room's metadata said
            if getattr(a, 'voice', 'off') == 'gemini' or handlers_path(a): self.voice = self.build_voice()
            self.start_session()
            if self.bound == participant.identity: self.start_call(participant)
        except Exception as e:
            log.exception('line start failed: %r', e)
            print(f'[line] could not start the call: {type(e).__name__}: {e}', flush=True)
            self.worker_error = e; self.end('line start failed')

    def probe_caller(self, participant):
        """CALLER_PROBE=1: write everything the dispatcher tells us about the caller to data/tmp/caller_probe.jsonl (local, gitignored),
        to find out whether a Chert call carries the caller's handle (to match a FaceTime call to a client)."""
        try:
            room_md = getattr(self.room, 'metadata', '')
            rec = dict(t=time.time(), room=self.room.name, room_metadata=room_md, job_metadata=self.md, identity=participant.identity,
                       name=getattr(participant, 'name', ''), metadata=getattr(participant, 'metadata', ''), attributes=dict(getattr(participant, 'attributes', {}) or {}))
            path = os.path.join(os.path.dirname(STARTER_DIR), 'data', 'tmp', 'caller_probe.jsonl'); os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'a') as f: f.write(json.dumps(rec, default=str) + '\n')
            print(f'[worker] caller probe -> {path}: fields name={bool(rec["name"])} metadata={bool(rec["metadata"])} attributes={sorted(rec["attributes"])} '
                  f'job_metadata={sorted(self.md)}', flush=True)
        except Exception as e:
            print(f'[worker] caller probe failed: {e!r}', flush=True)

    def bind(self, participant, what):
        """A caller: remember it (the leave grace is keyed on it), start the model session once (never on a warm job: this only runs
        when somebody publishes), and in voice mode emit the synthetic session {state: open} event once the session is up."""
        self.bound = participant.identity
        if participant.identity.startswith(BRIDGE_PREFIX): self.call_id = self.bridge_call_id = participant.identity[len(BRIDGE_PREFIX):]
        extra = getattr(self.event_writer, 'extra', None)                   # the JSONL lines carry the call id from the bind on (null before it)
        if isinstance(extra, dict): extra['call_id'] = self.call_id
        print(f'[worker] bound to {participant.identity!r} (call id {self.call_id or "n/a"}): {what}', flush=True)
        if os.environ.get('CALLER_PROBE'): self.probe_caller(participant)
        if self.line:
            self.line_bound = True
            if not self.session_started:                                    # first caller on this line: match them, then start
                if self.line_task is None: self.line_task = asyncio.create_task(self._line_start(participant), name='line-start')
                return
        self.start_call(participant)

    def start_call(self, participant):
        """The bound caller's recap and model session (once each)."""
        if self.competition:
            # Chert routes a real call into a prewarmed room: a chert-bridge-<call_id> caller in a warm job IS a call. Only a
            # warm job's other publishers (chert doctor's test participant) are not gatekept.
            if self.warm and not participant.identity.startswith(BRIDGE_PREFIX):
                print('[competition] warm job (chert_warm): no call to gatekeep; nothing is counted or recorded here', flush=True)
            elif self.comp is None and not self.closed: self.start_competition()
        elif self.recap is None and not self.warm and not self.voice_mode and self.a.plan and call_client_id(self.a):
            from facetime.call_recap import CallRecap
            self.recap = CallRecap(self.a.plan, getattr(self.a, 'assignment', None), client_id=call_client_id(self.a))
            self.recap.start_task = asyncio.create_task(self.recap.start(), name='session-start')
        if self.voice_mode:
            if not self.session_opened and self.open_task is None:
                self.open_task = asyncio.create_task(self._open_session(participant.identity), name='voice-start')
        elif self.voice is not None and self.voice.model is not None and not self.voice.started:
            asyncio.create_task(self.voice.on_caller(participant.identity, room=self.room), name='voice-start')

    async def _open_session(self, identity):
        """Voice mode: the model session (when there is one), then ONE session event {state: open, mode: voice} for the handlers."""
        try:
            if self.voice is not None and self.voice.model is not None:
                await self.voice.on_caller(identity, room=self.room)
            if self.closed or self.session_opened: return
            self.session_opened = True
            self.emit('session', state='open', exercise=None, target=None, count=0, item=None, done=False, mode='voice')
        finally:
            self.open_task = None

    # ---- competition (CHALLENGE_MODE=competition): challenge/worker/controller.py ----
    def start_competition(self):
        """Gatekeep and run this call through a CompetitionCall (on the loop). Any setup error fails closed: logged, the
        worker leaves, nothing is recorded."""
        from challenge.worker.client import DispatcherClient
        from challenge.worker.controller import CompetitionCall
        from facetime.pipeline import load_json_arg
        cc = self.md.get('chert_call')
        log_chert_keys(cc)
        if self.call_id is None:
            cid = (cc.get('call_id') or cc.get('id')) if isinstance(cc, dict) else None
            self.call_id = str(cid) if cid else f'job-{self.ctx.job.id}'
            extra = getattr(self.event_writer, 'extra', None)
            if isinstance(extra, dict): extra['call_id'] = self.call_id
        source = (os.environ.get('CALLER_ID_SOURCE') or 'claim_window').strip()
        handle = caller_handle(cc) if source == 'chert_meta' else None      # claim_window: the claim decides; send no PII
        if source == 'chert_meta' and handle is None:
            print(f'[competition] CALLER_ID_SOURCE=chert_meta but chert_call has no handle (keys tried {CHERT_HANDLE_KEYS}); the dispatcher decides without one', flush=True)
        try:
            hangup = (os.environ.get('HANGUP_MODE') or 'unverified').strip()
            # The Chert call id is the bridge identity's suffix (chert-bridge-<id>): real calls land in chert_warm rooms whose
            # job metadata has no chert_call (confirmed live 2026-10-13). Fall back to chert_call metadata for BYOR dispatch.
            chert_id = self.bridge_call_id or ((cc.get('call_id') or cc.get('id')) if isinstance(cc, dict) else None)
            chert_end = None
            if hangup == 'chert_api':
                from challenge.worker.chert import ChertEndClient
                chert_end = ChertEndClient.from_env()
            self.comp_client = DispatcherClient.from_env()
            self.comp = CompetitionCall(self.call_id, os.environ.get('LINE_ID') or 'line-1', handle, self.comp_client,
                                        load_json_arg(getattr(self.a, 'judge_thr', None), None), clock=self.clock, say=self.say_cue,
                                        leave=self.end, update_challenge_window=self.queue_challenge_window, sleep=self.sleep,
                                        on_config=self.queue_judge_config, drain=self.drain_feed,
                                        reveal_mode=(os.environ.get('REVEAL_MODE') or 'audio_only').strip(),
                                        hangup_mode=hangup, reveal=self.reveal_video,
                                        chert_call_id=str(chert_id) if chert_id else None, chert_end=chert_end)
        except Exception as e:
            log.exception('competition setup failed')
            print(f'[competition] setup failed ({type(e).__name__}: {e}): leaving without counting (fail closed)', flush=True)
            self.end('competition setup failed'); return
        print(f'[competition] call {self.call_id} on {self.comp.line_id}: asking the dispatcher (caller id {source}, handle {"yes" if handle else "no"})', flush=True)
        self.comp_task = asyncio.create_task(self._run_competition(), name='competition')
        self.hb_task = asyncio.create_task(self._job_heartbeat(), name='job-heartbeat')

    async def reveal_video(self, seconds, wait_committed):
        """REVEAL_MODE=video (C7.v): the card/fallback frame goes to the coach-video loop (reveal_frames); never raises."""
        from challenge.worker.reveal_video import RevealFrames
        if self.reveal_frames is None:                                     # portrait + the mirror's sideways-phone layout
            try: from facetime.pushup_mirror import LW, LH; land = (LW, LH)
            except Exception: land = None
            self.reveal_frames = RevealFrames(size=getattr(self, 'video_size', (720, 1280)), landscape_size=land)
        return await self.reveal_frames.run(self.call_id, seconds, wait_committed)

    async def _run_competition(self):
        try:
            if await self.comp.start():
                await self.comp.run()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception('competition controller failed')
            print(f'[competition] controller error ({type(e).__name__}: {e}): ending the call (the checkpoint is replayed by the reconciler)', flush=True)
            self.end('competition controller error')

    def say_cue(self, key, text, urgent):
        """The controller's cues: urgent ones cut whatever plays (say_now), corrective ones queue as a correction."""
        if self.player is None:
            print(f'[competition] cue {key}: {text!r} (no audio: events only)', flush=True); return
        if urgent: self.player.say_now(text, 'challenge', {'cue': key})
        else: self.player.say(text, 'correction', {'cue': key})

    def queue_challenge_window(self, t0_wall, t1_wall):
        """Controller (wall clock) -> the feed thread, which applies it to Perception on the event clock before its next frame."""
        if self.per_wall0 is None: return
        self.pending_windows.append(('win', t0_wall - self.per_wall0, t1_wall - self.per_wall0))

    def queue_judge_config(self, thr):
        """Controller (on accept): the live judge thresholds for the pipeline judge, applied by the feed thread before its
        next frame; the controller counts reps only after that (judge_applied, posted back to the loop in order)."""
        self.pending_windows.append(('thr', dict(thr)))

    async def drain_feed(self):
        """end(): seal the rep intake. Stop the feed (no new frame starts), wait for the frame in flight (it holds
        feed_lock), then run the loop callbacks it posted (its rep events -> comp.on_rep). Returns True: no rep event
        can arrive any more. Bounded by the controller (a wedged frame keeps the lock: the commit is deferred)."""
        self.feed_sealed = True
        while not self.feed_lock.acquire(blocking=False):
            await asyncio.sleep(0.01)
        self.feed_lock.release()
        for _ in range(3): await asyncio.sleep(0)                 # call_soon_threadsafe callbacks posted before the release
        return True

    def wall_of(self, ev_t):
        """Perception event clock (seconds since per.t0) -> wall time."""
        return (self.per_wall0 if self.per_wall0 is not None else self.clock()) + float(ev_t)

    def before_frame(self):
        """Feed thread, before each processed frame: apply queued challenge windows."""
        while self.pending_windows:
            item = self.pending_windows.popleft()
            if item[0] == 'win':
                self.per.update_challenge_window(item[1], item[2])
            else:
                apply_judge_thresholds(self.per.pipe, item[1])
                if self.comp is not None: self.loop.call_soon_threadsafe(self.comp.judge_applied)

    def after_frame(self, t_wall, size):
        """Feed thread, after each processed frame: the frame's pose (as the pipeline saw it: never mirrored) for the
        liveness challenge, handed to the controller on the loop."""
        comp = self.comp
        if comp is None or self.per is None: return
        from challenge.judge.metrics import FrameObs
        pipe = self.per.pipe; a = getattr(pipe, 'last_landmarks', None)
        obs = FrameObs(t=float(t_wall), img=(None if a is None else a.copy()), world=None, persons=int(getattr(pipe, 'persons', 0) or 0),
                       aspect=(size[0] / size[1]) if size and size[1] else 16 / 9)
        self.loop.call_soon_threadsafe(comp.on_frame, obs)

    async def close_competition(self):
        """aclose: start (or join) the commit, let the cue in flight finish, leave the room at once (the call ends on time
        whatever the dispatcher does), then wait for the commit (bounded; the checkpoint is on disk). The dispatcher
        client is closed only when no end() is running any more."""
        if self.hb_task is not None: self.hb_task.cancel()
        end_task = None
        if self.comp is not None:
            end_task = asyncio.ensure_future(self.comp.end(self.end_reason or 'shutdown'))
            # comp exists: a caller was gatekept here (never an empty warm room); a room that already went away is not deleted
            delete = self.hangup_mode == 'delete_room' and not str(self.end_reason or '').startswith('room disconnected')
            if delete: await self.wait_cue_done(CUE_DRAIN_MAX_S)      # the room goes away with the delete: let the last cue finish
            else: await self.leave_room()
            try:
                await asyncio.wait_for(asyncio.shield(end_task), COMMIT_WAIT_S)
            except asyncio.TimeoutError:
                print(f'[competition] commit still pending after {COMMIT_WAIT_S:g} s: checkpoint {self.comp.path} kept (committed:false)', flush=True)
            except Exception as e:
                log.exception('competition end failed: %r', e)
            self.write_health(active=False)
            if delete:                                                # after the commit and call_ended: Chert ends the call
                if not await self.delete_room(): await self.leave_room()
        if self.comp_task is not None and not self.comp_task.done():
            self.comp_task.cancel()
            await asyncio.gather(self.comp_task, return_exceptions=True)
        if self.comp_client is not None and not (self.comp is not None and self.comp.commit_deferred):   # still needed
            client = self.comp_client
            if self.comp is not None and self.comp.ending:
                self.comp._end_task.add_done_callback(lambda _t: asyncio.ensure_future(self._close_client(client)))
            else:
                await self._close_client(client)

    async def finish_deferred_commit(self):
        """aclose, after the feed thread was joined: the commit waited for a sealed rep intake. Thread gone -> seal and
        commit now; still alive (wedged) -> leave the checkpoint committed:false (unsealed) for the reconciler."""
        comp = self.comp
        if self.thread is None or not self.thread.is_alive():
            comp.seal()
            try:
                await asyncio.wait_for(asyncio.shield(comp.end('sealed after feed exit')), COMMIT_WAIT_S)
            except asyncio.TimeoutError:
                print(f'[competition] deferred commit still pending after {COMMIT_WAIT_S:g} s: checkpoint {comp.path} kept', flush=True)
            except Exception as e:
                log.exception('competition deferred commit failed: %r', e)
        else:
            print(f'[competition] perception feed still wedged: checkpoint {comp.path} kept unsealed, committed:false', flush=True)
        if self.comp_client is not None:
            client = self.comp_client
            if comp.ending: comp._end_task.add_done_callback(lambda _t: asyncio.ensure_future(self._close_client(client)))
            else: await self._close_client(client)

    @staticmethod
    async def _close_client(client):
        try: await client.aclose()
        except Exception as e: log.debug('dispatcher client close: %r', e)

    async def wait_cue_done(self, max_s):
        """The cue in flight (and one queued) finishes, at most max_s; only while still connected."""
        if self.player is None or not self.room_connected(): return
        for _ in range(int(max_s / 0.1)):
            if not self.player.playing and self.player.pending is None and getattr(self.player, 'urgent', None) is None: return
            await asyncio.sleep(0.1)

    async def delete_room(self):
        """HANGUP_MODE=delete_room: DeleteRoom through the LiveKit room service (LIVEKIT_URL/API_KEY/API_SECRET); Chert
        ends the FaceTime call when its room is removed. Two attempts; False (logged, never raises) -> the caller leaves."""
        name = getattr(self.room, 'name', None)
        try:
            from livekit import api
        except Exception as e:
            api = None; log.error('delete_room: livekit.api unavailable: %r', e)
        if not name or api is None:
            log.error('delete_room: cannot delete (room %r)', name); self.room_deleted = False; return False
        for i in (1, 2):
            client = None
            try:
                client = (self.lk_api or api.LiveKitAPI)()
                await asyncio.wait_for(client.room.delete_room(api.DeleteRoomRequest(room=name)), DELETE_ROOM_TIMEOUT_S)
                print(f'[competition] hang-up: deleted room {name!r} (HANGUP_MODE=delete_room)', flush=True)
                self.room_deleted = True; return True
            except Exception as e:
                log.error('delete_room %r failed (attempt %d/2): %r', name, i, e)
                print(f'[competition] delete room {name!r} failed (attempt {i}/2): {type(e).__name__}: {str(e)[:160]}', flush=True)
            finally:
                if client is not None:
                    try: await client.aclose()
                    except Exception as e: log.debug('LiveKitAPI close: %r', e)
            if i == 1: await asyncio.sleep(0.5)
        print('[competition] hang-up: room delete failed; leaving the room instead (Chert ends the call once the room empties)', flush=True)
        self.room_deleted = False
        return False

    async def leave_room(self):
        """Competition: leave the room now (after at most 1.5 s of the cue in flight), before the commit finishes."""
        if self.player is not None and self.room_connected():
            for _ in range(15):
                if not self.player.playing and self.player.pending is None and getattr(self.player, 'urgent', None) is None: break
                await asyncio.sleep(0.1)
        disconnect = getattr(self.room, 'disconnect', None)
        if disconnect is None or not self.room_connected(): return
        try: await asyncio.wait_for(disconnect(), 2.0)
        except Exception as e: log.warning('room disconnect: %r', e)

    def job_health(self):
        """(healthy, detail) of this job: the feed thread alive, frames processed recently while a caller is bound, the
        controller ticking. Sent with the job heartbeat and written for the supervisor's beat."""
        now = time.time(); comp = self.comp
        feed_alive = self.thread is None or self.thread.is_alive()
        frame_age = None if self.last_proc_wall is None else round(now - self.last_proc_wall, 1)
        tick_age = None if comp is None or comp.last_tick_wall is None else round(now - comp.last_tick_wall, 1)
        counting = comp is not None and comp.decision == 'accept' and comp.ended_at is None
        healthy = feed_alive and self.worker_error is None and not (counting and (
            (self.video_task is not None and frame_age is not None and frame_age > JOB_STALL_S) or (tick_age is not None and tick_age > JOB_STALL_S)))
        detail = dict(call_id=self.call_id, state=(comp.decision if comp is not None else None) or 'gatekeeping', counting=counting,
                      reps=len(comp.reps) if comp is not None else 0, frames_processed=self.processed, last_frame_age_s=frame_age,
                      tick_age_s=tick_age, feed_alive=feed_alive)
        return healthy, detail

    def write_health(self, active=True):
        """The job's health for the supervisor heartbeat (data/tmp/worker_health/<line>.json, atomic; no media)."""
        try:
            healthy, detail = self.job_health()
            from challenge.worker.controller import write_json_atomic
            write_json_atomic(health_path(), dict(t=time.time(), active=bool(active), healthy=healthy, pid=os.getpid(), **detail))
        except Exception as e:
            log.warning('job health file: %r', e)

    async def _job_heartbeat(self):
        """Every JOB_BEAT_S during a competition job: POST /calls/heartbeat scope job (in-call state) + the health file."""
        line = os.environ.get('LINE_ID') or 'line-1'
        while not self.closed:
            healthy, detail = self.job_health(); self.write_health()
            try:
                await self.comp_client.heartbeat(line, detail, scope='job', healthy=healthy)
            except Exception as e:
                log.warning('job heartbeat failed: %r', e)
            await asyncio.sleep(JOB_BEAT_S)

    def video_frames(self, track):
        """The VideoStream of the bound track (RGB24 for Perception; the tee hands the same frames to the model). Tests replace it."""
        return rtc.VideoStream(track, format=rtc.VideoBufferType.RGB24)

    async def read_video(self, track):
        stream = self.video_frames(track)
        try:
            async for ev in stream:
                t_mono = time.monotonic()
                self.seq += 1; self.latest = (ev.frame, ev.timestamp_us, t_mono, time.time(), self.seq); self.frame_event.set()
                if self.vision is not None and self.vision.offer(ev.frame, t_mono) and not self.vision_logged:
                    self.vision_logged = True
                    print(f'[vision] forwarding video to the model at {self.vision.fps:g} fps ({ev.frame.width}x{ev.frame.height})', flush=True)
                if self.voice_mode:                                                      # no feed thread: first frame, size and --max-s here
                    if self.first_frame_t is None:
                        self.first_frame_t = t_mono; self.frame_size = (ev.frame.width, ev.frame.height)
                        print(f'[worker] first frame {ev.frame.width}x{ev.frame.height}', flush=True)
                    if self.a.max_s and t_mono - self.first_frame_t >= self.a.max_s:
                        print(f'[worker] --max-s {self.a.max_s} reached', flush=True); self.end('max_s reached'); break
        finally:
            await stream.aclose()
        print('[worker] video stream ended (a republished track is picked up again)', flush=True)
        self.video_task = None

    # ---- voice mode (--perception off): the worker's own events ----
    def emit(self, type_, **fields):
        """A synthetic event in the perception schema (v1, t on this job's clock, own seq), through the same sinks as Perception's."""
        ev = dict(v=EVENT_SCHEMA_VERSION, t=round(time.monotonic() - self.t0, 3), t_wall=round(time.time(), 3), seq=self.ev_seq, type=type_)
        if type_ != 'status': ev['frame'] = self.seq
        ev.update(fields); self.ev_seq += 1
        if self.event_writer is not None:
            try: self.event_writer(ev)
            except Exception as e: log.warning('event log failed: %r', e)
        self.on_event(ev)
        return ev

    async def _status_loop(self):
        """Every status_every_s (5 s) while a caller is bound: frames received, the vision tee's counters, the player's stats."""
        every = float(getattr(self.cfg, 'status_every_s', 5.0) or 5.0); last_seq = self.seq; last_t = time.monotonic()
        while True:
            await asyncio.sleep(every)
            now = time.monotonic(); el = max(now - last_t, 1e-6); recv = (self.seq - last_seq) / el; last_seq = self.seq; last_t = now
            if self.bound is None and self.video_task is None: continue
            ev = dict(fps_recv=round(recv, 1), state='open' if self.session_opened else 'init', exercise=None, count=0, mode='voice',
                      voice=('on' if self.voice is not None and self.voice.model is not None and self.voice.started else 'off'))
            if self.vision is not None: ev.update(vision_frames=self.vision.n_sent, vision_fps=self.vision.fps, vision_replaced=self.vision.n_replaced)
            if self.player is not None: ev.update(underruns=self.player.underruns, cues_played=self.cues_played, cues_dropped=self.player.n_dropped)
            self.emit('status', **ev)

    def on_participant_connected(self, p):
        try: kind = rtc.ParticipantKind.Name(p.kind)
        except Exception: kind = str(getattr(p, 'kind', '?'))
        print(f'[worker] participant joined: {p.identity} (kind {kind})', flush=True)
        self.watch_no_video(p)

    def watch_no_video(self, p):
        """P0-3, competition: a Chert bridge caller (chert-bridge-<call id>) in the room starts the no-video watch (once)."""
        if not self.competition or self.closed or self.comp is not None or self.novideo_task is not None: return
        if not str(getattr(p, 'identity', '')).startswith(BRIDGE_PREFIX): return
        self.novideo_task = asyncio.create_task(self._no_video_watch(p), name='no-video-watch')

    def has_video(self):
        return self.video_task is not None or self.seq > 0

    async def _no_video_watch(self, p):
        """A bridge caller with no video track after NO_VIDEO_START_S (FaceTime Audio, camera off) is still a call: bind it
        and run /calls/start (attribution, claim and cap logic as for any call; a reject plays its cue and hangs up). On an
        accept: NO_VIDEO_CUE NO_VIDEO_CUE_DELAY_S later; still no video NO_VIDEO_END_S after the join -> end the call (the
        commit records 0 reps, then call_ended) and hang up. Video arriving at any point -> the call simply continues."""
        t_join = self.clock()
        try:
            while self.clock() - t_join < NO_VIDEO_START_S:
                await self.sleep(NO_VIDEO_POLL_S)
                if self.closed or self.comp is not None or self.has_video(): return
                if p.identity not in self.room.remote_participants: return          # the caller left before any video
            print(f'[competition] {p.identity!r}: no video after {NO_VIDEO_START_S:g} s: starting the call anyway (camera off / audio only)', flush=True)
            self.bind(p, f'no video after {NO_VIDEO_START_S:g} s')
            comp = self.comp
            if comp is None: return
            while not comp.start_done:
                if self.closed: return
                await self.sleep(NO_VIDEO_POLL_S)
            if comp.decision != 'accept': return                                    # reject / fail closed: its own cue and hang-up
            t_acc = self.clock(); cued = False
            while self.clock() - t_join < NO_VIDEO_END_S:
                if self.closed or comp.ended_at is not None or self.has_video(): return
                if not cued and self.clock() - t_acc >= NO_VIDEO_CUE_DELAY_S:
                    cued = True; comp.say(_no_video_cue())
                await self.sleep(NO_VIDEO_POLL_S)
            if self.closed or comp.ended_at is not None or self.has_video(): return
            print(f'[competition] call {self.call_id}: still no video {NO_VIDEO_END_S:g} s after the caller joined: ending the call', flush=True)
            self.end('no video')
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('no-video watch failed')

    def on_participant_disconnected(self, p):
        print(f'[worker] participant left: {p.identity}', flush=True)
        if p.identity == self.bound:
            self.bound = None
            if self.a.leave_grace_s is not None and self.a.leave_grace_s >= 0 and self.leave_task is None and not self.closed:
                self.leave_task = asyncio.create_task(self._leave_grace(), name='leave-grace')

    def capture_time(self, ts_us, t_wall):
        if self.ts_mode is None:
            self.ts_mode = 'epoch' if abs(ts_us / 1e6 - t_wall) < 5 else 'recv'
        return ts_us / 1e6 if self.ts_mode == 'epoch' else t_wall

    # ---- worker thread: arrival-aligned, >= 90 ms apart, newest frame only (coach_agent._worker) ----
    def feed(self):
        try:
            self._feed()
        except BaseException as e:
            log.exception('perception thread died: %r', e)
            print(f'[worker] perception thread died: {type(e).__name__}: {e}', flush=True)
            self.worker_error = e; self.loop.call_soon_threadsafe(self.done.set)

    def _feed(self):
        last_seq = 0; last_proc = -1e9
        while not self.stop.is_set():
            if not self.frame_event.wait(timeout=0.05): slot = None
            else:
                self.frame_event.clear(); slot = self.latest
                if slot is not None and slot[4] != last_seq:
                    since = time.monotonic() - last_proc
                    if since < 0.09:                              # too soon after the last one: wait for the 90 ms mark, then take the newest frame
                        time.sleep(0.09 - since); slot = self.latest; self.frame_event.clear()
            if slot is None or slot[4] == last_seq:
                self.idle += 1; continue
            frame, ts_us, t_mono, t_wall, seq = slot
            self.dropped += seq - last_seq - 1; last_seq = seq; last_proc = time.monotonic()
            if self.first_frame_t is None:
                self.first_frame_t = t_mono; print(f'[worker] first frame {frame.width}x{frame.height}', flush=True)
            if self.frame_size != (frame.width, frame.height):
                if self.frame_size is not None: print(f'[worker] received resolution changed {self.frame_size} -> {(frame.width, frame.height)}', flush=True)
                self.frame_size = (frame.width, frame.height)
            raw = frame_to_rgb(frame)
            rgb = self.prep_frame(raw, t_mono)                # the caller's picture only, upright (facetime/frameprep.py)
            self.per.frames_received = self.seq; self.per.frames_dropped = self.dropped
            with self.feed_lock:
                if self.feed_sealed: break                    # the call's commit is being built: no more frames, no more reps
                self.feed_busy = True
                try:
                    if self.pending_windows: self.before_frame()
                    self.per.process_frame(rgb, t_recv=t_mono, meta=dict(frame_seq=seq, ts_us=ts_us, t_capture=self.capture_time(ts_us, t_wall), t_recv=t_wall))
                    if self.comp is not None: self.after_frame(t_wall, (frame.width, frame.height))
                finally:
                    self.feed_busy = False
            self.processed += 1; self.last_proc_wall = time.time()
            lm = getattr(self.pipe, 'last_landmarks', None)
            self.check_orientation(raw, lm, t_mono)
            if self.mirror_live:                                  # newest frame + its pose for the mirror (only the newest is kept)
                self.update_layout(raw, t_mono)
                self.mirror_in = (rgb, lm, seq, time.monotonic())
            if self.comp is not None and time.monotonic() - getattr(self, 'diag_t', 0.0) >= 1.0:
                self.diag_t = time.monotonic()
                try: print(f'[posediag] {pose_diag(rgb, lm)}; {self.prep.diag() if getattr(self, "prep", None) is not None else "no prep"}', flush=True)
                except Exception as e: print(f'[posediag] failed: {e!r}', flush=True)
            if self.a.max_s and t_mono - self.first_frame_t >= self.a.max_s:
                print(f'[worker] --max-s {self.a.max_s} reached', flush=True); self.loop.call_soon_threadsafe(self.end, 'max_s reached'); break

    def prep_frame(self, raw, t_mono):
        """Feed thread: the bridge frame -> the caller's picture, upright. A failure here never stops the counting: it is
        logged and that frame goes to the pose uncropped."""
        try:
            if getattr(self, 'prep', None) is None:
                from facetime.frameprep import FramePrep
                self.prep = FramePrep(pose_variant=getattr(self.pipe, 'pose_variant', None) or 'full')
            return self.prep(raw, t_mono)
        except Exception as e:
            self.prep_fails = getattr(self, 'prep_fails', 0) + 1
            if self.prep_fails == 1 or self.prep_fails % 100 == 0:
                log.exception('frame prep failed'); print(f'[worker] frame prep failed ({self.prep_fails} so far): {e!r}; raw frame used', flush=True)
            return raw

    def update_layout(self, raw, now):
        """Feed thread: the coach-video's orientation follows the caller's physical phone (frameprep.phone_sideways through
        an OrientationGate: ~2 s sustained, no flapping) -> self.mirror_landscape, read by the avatar loop. Cosmetic: a
        failure is logged and the layout stays as it was."""
        try:
            from facetime.frameprep import OrientationGate, phone_sideways
            gate = getattr(self, 'orient_gate', None)
            if gate is None: gate = self.orient_gate = OrientationGate()
            was = gate.landscape
            self.mirror_landscape = gate.update(phone_sideways(getattr(self, 'prep', None), raw), now)
            if self.mirror_landscape != was:
                print(f"[worker] caller's phone {'sideways' if self.mirror_landscape else 'upright'}: coach-video "
                      f"{'landscape' if self.mirror_landscape else 'portrait'}", flush=True)
        except Exception as e:
            self.layout_fails = getattr(self, 'layout_fails', 0) + 1
            if self.layout_fails == 1 or self.layout_fails % 100 == 0:
                log.exception('layout update failed'); print(f'[worker] layout update failed ({self.layout_fails} so far): {e!r}', flush=True)

    def check_orientation(self, raw, lm, now=None):
        """Feed thread, after the pose: the orientation lock (FramePrep.observe; probes <= 1/s only while no plank is seen).
        A probe failure is logged; the current orientation stays."""
        if getattr(self, 'prep', None) is None: return
        try:
            sw = self.prep.observe(raw, lm, time.monotonic() if now is None else now)
        except Exception as e:
            self.orient_fails = getattr(self, 'orient_fails', 0) + 1
            if self.orient_fails == 1 or self.orient_fails % 50 == 0:
                log.exception('orientation check failed'); print(f'[worker] orientation check failed ({self.orient_fails} so far): {e!r}', flush=True)
            return
        if sw is not None:
            print(f'[worker] caller picture turned {sw[0]} -> {sw[1]} deg (sideways phone with rotation lock); {self.prep.diag()}', flush=True)

    # ---- sinks ----
    def say_from_worker(self, text, intent, meta):
        self.loop.call_soon_threadsafe(self.player.say, text, intent, meta)

    def on_event(self, ev):
        """Perception thread -> event loop: the queue, the console, the optional data channel. The arms-up probe beeps here (say_now
        from the loop, as coach_agent does) only with --latency-probe, the cue player attached and no set active (run B on 10-09: a
        jumping jack is an arm raise), and the event says so (beep) before it is logged; a probe during a set is emitted, not acted on."""
        if ev['type'] == 'session': self.session_state = ev.get('state')
        if ev['type'] == 'probe':
            armed = bool(getattr(self.a, 'latency_probe', False)); active = self.session_state == 'active'
            if active: self.probes_ignored += 1
            beep = armed and not active and self.player is not None and getattr(self.a, 'probe_beep', True)
            ev['beep'] = bool(beep)
            if beep:
                from facetime.audio_out import BEEP
                t_first = ev.get('t_first_up'); now_m = time.monotonic(); now_w = time.time()
                meta = dict(t_recv=(now_w - (now_m - t_first)) if t_first is not None else None, t_detect=now_w, on_box_ms=ev.get('on_box_ms'))
                self.loop.call_soon_threadsafe(self.player.say_now, BEEP, 'probe', meta)
        self.loop.call_soon_threadsafe(self._deliver, ev)

    def _deliver(self, ev):
        self.events.put_nowait(ev)
        t = ev['type']
        if self.recap is not None and not self.closed:
            self.recap.on_event(ev)
            if t == 'session' and (ev.get('state') == 'done' or ev.get('done')):        # plan finished, caller still here: save + show the card
                asyncio.create_task(self.recap.finish(self.room, show=self.room_connected()), name='session-finish')
        if t == 'rep' and self.comp is not None:                # also during shutdown: the controller judges by timestamp
            stored = None
            try: stored = self.comp.on_rep(ev, t=self.wall_of(ev['t']))
            except Exception: log.exception('competition on_rep failed for rep %s', ev.get('n'))
            if stored is not None and getattr(self, 'mirror_live', False):    # what the controller recorded (None = outside the count)
                self.mirror_rep(stored.get('valid') is True, stored.get('reject_reasons'), stored.get('in_challenge'))
        elif t == 'rep' and getattr(self, 'mirror_live', False):            # no competition: the judge's verdict, or every rep without a judge
            self.mirror_rep(ev.get('valid', True) is True, ev.get('reject_reasons'), ev.get('in_challenge'))
        if t == 'rep':
            c = ev.get('confidence') or {}
            print(f"[event] rep {ev['exercise']} {ev['n']} (agree {c.get('agree')}, amp {c.get('amp')}) t={ev['t']:.2f}", flush=True)
        elif t in ('session', 'gesture', 'visibility', 'fault', 'probe'):
            note = ''
            if t == 'probe' and not getattr(self.a, 'latency_probe', False): note = '  (probe off: --latency-probe to beep and open the floor)'
            elif t in ('probe', 'gesture') and self.session_state == 'active': note = '  (during a set: no beep, no floor window)'
            print(f"[event] {t} " + ' '.join(f'{k}={v}' for k, v in ev.items() if k not in ('v', 't_wall', 'seq', 'type', 'frame')) + note, flush=True)
        elif t == 'status' and ev.get('mode') == 'voice':
            vis = f"vision {ev['vision_frames']} frames sent ({ev['vision_fps']:g} fps, {ev.get('vision_replaced', 0)} replaced)" if 'vision_frames' in ev else 'vision off'
            print(f"[status] recv {ev.get('fps_recv')} fps, {vis}, voice {ev.get('voice')}, underruns {ev.get('underruns')}, cues {ev.get('cues_played')}, "
                  f"session {ev['state']} (voice mode, no perception)", flush=True)
        elif t == 'status':
            print(f"[status] recv {ev.get('fps_recv')} fps, processed {ev['fps_processed']} fps, pose {ev['pose_ms']} ms ({ev['pose_model']}), clf {ev['clf_ms']} ms, "
                  f"recv->decision p50 {ev.get('recv_to_decision_p50_ms')} ms, dropped {ev.get('dropped')}, underruns {ev.get('underruns')}, session {ev['state']}/{ev['exercise'] or '-'} count {ev['count']}", flush=True)
        if self.a.publish_data:
            asyncio.create_task(self._publish(ev))

    async def _publish(self, ev):
        try:
            await self.room.local_participant.publish_data(json.dumps(ev).encode(), reliable=True, topic=self.a.data_topic)
        except Exception as e:
            log.warning('publish_data failed: %r', e)

    # ---- the conversational layer (facetime/voice.py) ----
    def build_voice(self):
        """--voice gemini: the VoiceLayer with a GeminiModel (session started on bind, never on a warm job) and the mixer input on the
        cue player; --handlers alone: the handlers with say_now only. Returns None (with a message) when the layer cannot run."""
        from facetime.voice import VoiceLayer, GeminiModel, VideoTee, load_handlers, read_text, DEFAULT_PERSONA
        a = self.a; model = None
        if a.voice == 'gemini':
            if self.player is None:
                print('[voice] --voice gemini needs the cue player track (not --events-only): the model speaks through that one AudioSource; voice OFF', flush=True)
            elif not (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')):
                print('[voice] GEMINI_API_KEY is MISSING: voice OFF', flush=True)
            else:
                persona = read_text(a.persona, DEFAULT_PERSONA)
                if getattr(a, 'assignment', None):
                    from facetime.plan_loader import persona_text
                    persona = persona_text(persona, a.assignment)
                if a.plan: plan_line = f'\n\nFor your own reference only, never to be read aloud: the session plan, in order, is {a.plan}.'
                elif getattr(a, 'plan_text', None): plan_line = '\n\nThe plan you are coaching, step by step (follow it in order, one step at a time; never read it aloud):\n' + a.plan_text
                else: plan_line = ''
                model = GeminiModel(persona + plan_line, model=a.voice_model, voice=a.voice_name, on_turn=self.emit_voice)
        if getattr(a, 'vision', False):
            if model is None: print('[vision] --vision needs --voice gemini with a model session: no video is forwarded', flush=True)
            else: self.vision = VideoTee(fps=a.vision_fps)
        hpath = handlers_path(a); handlers = load_handlers(hpath) if hpath else None
        if model is None and handlers is None: return None
        floor_open = getattr(a, 'floor', None) == 'open'
        if floor_open and not self.voice_mode: print('[voice] --floor open with perception on: the voice is never cut by a set (it will talk over the counts)', flush=True)
        v = VoiceLayer(self, model=model, plan=a.plan, handlers=handlers, probe=bool(getattr(a, 'latency_probe', False)), floor_open=floor_open, vision=self.vision)
        if model is not None:
            v.attach()
            print(f'[voice] gemini {model.model_id} voice {model.voice} language {model.language or "model default"}; persona {a.persona} ({len(model.persona)} chars'
                  + (f', plan text {len(a.plan_text)} chars from {a.plan_file}' if getattr(a, 'plan_text', None) else '') + f'); '
                  f'handlers {hpath or "none"}; mixer on the cue track (duck {20 * __import__("math").log10(self.player.mix.duck):.0f} dB); '
                  f'floor {"ALWAYS OPEN" if floor_open else "gated to the gaps between sets"}; probe window {"on" if v.floor.probe else "off"}; '
                  f'vision {f"on ({self.vision.fps:g} fps tee)" if self.vision is not None else "off"}; session starts when a caller is bound', flush=True)
        else:
            print(f'[voice] handlers {hpath} (say_now only; no model: ask_voice returns None)', flush=True)
        return v

    def emit_voice(self, role, text):
        """A model (or caller) turn as an event of type voice {text, t, role}: the queue, the JSONL log, the console (own seq counter)."""
        if role == 'caller' and not getattr(self.a, 'log_caller', False):
            print(f'[voice] caller spoke ({len(text.split())} words; not logged, --log-caller to keep transcripts)', flush=True); return
        t = round(time.monotonic() - (self.per.t0 if self.per is not None else self.t0), 3)
        ev = dict(v=EVENT_SCHEMA_VERSION, t=t, t_wall=round(time.time(), 3), seq=self.voice_seq, type='voice', text=text, role=role, producer='voice')
        self.voice_seq += 1
        print(f'[voice] {role}: {text}', flush=True)
        self.events.put_nowait(ev)
        if self.event_writer is not None:
            try: self.event_writer(ev)
            except Exception as e: log.warning('voice event log failed: %r', e)
        if self.a.publish_data: asyncio.create_task(self._publish(ev))

    def log_cue(self, rec):
        rec = dict(rec, room=self.room.name, call_id=self.call_id)
        if self.cue_log: self.cue_log.write(json.dumps(rec) + '\n'); self.cue_log.flush()
        if rec['status'] == 'played':
            self.cues_played += 1
            lat = '' if rec.get('t_decision') is None else f"  decision->push {1000 * (rec['t_push'] - rec['t_decision']):.0f} ms"
            if rec['intent'] == 'probe' and rec.get('t_recv') is not None:
                lat = f"  first up frame recv -> beep pushed {1000 * (rec['t_push'] - rec['t_recv']):.0f} ms (detect -> push {1000 * (rec['t_push'] - rec['t_detect']):.0f}, on-box {rec.get('on_box_ms')} ms)"
            print(f"[cue] {time.strftime('%H:%M:%S')} [{rec['intent']:10}] {rec['text']!r}{lat}", flush=True)
        else:
            print(f"[cue] {rec['status']} [{rec['intent']}] {rec['text']!r} {rec.get('why_dropped', '')}", flush=True)


def max_jobs():
    try: return max(1, int(os.environ.get('WORKER_MAX_JOBS') or WORKER_MAX_JOBS))
    except ValueError: return WORKER_MAX_JOBS


def job_count_load(worker):
    """P1-5: the worker's load = active jobs / WORKER_MAX_JOBS (env overrides), not CPU. One call drives CPU to 0.6-1.0 on
    2 vCPU, and the default CPU load with its 0.7 threshold then marked the worker full exactly when Chert asks for the
    replacement warm-room job, leaving the next caller's room without an agent. A job is cheap until a caller publishes."""
    try: n = len(worker.active_jobs)
    except Exception: n = 0
    return min(1.0, n / max_jobs())


def worker_options(a):
    # load_threshold 1.0 with job_count_load: available while active (+ reserved) jobs < WORKER_MAX_JOBS
    return WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=a.agent_name, num_idle_processes=max(0, int(a.idle_processes)),
                         initialize_process_timeout=90.0, job_memory_warn_mb=3000, load_fnc=job_count_load, load_threshold=1.0)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    ap = build_parser(); a, rest = ap.parse_known_args(argv)
    if a.help or (not rest and '--help' in argv):
        ap.print_help(); return 0
    resolve_mode(a, load_client=False)
    if rest and rest[0] not in LK_COMMANDS and rest[0].startswith('-'):
        print(f'[worker] unknown flag {rest[0]!r} (our flags go before the LiveKit subcommand: {", ".join(LK_COMMANDS)})', file=sys.stderr); return 2
    err = check_competition(a)
    if err:
        print(f'[worker] CHALLENGE_MODE={challenge_mode()}: {err}', file=sys.stderr); return 2
    os.environ[ARGS_ENV] = json.dumps({k: v for k, v in vars(a).items() if k != 'help'})
    if a.vision and a.voice != 'gemini':
        print('[worker] --vision only does something with --voice gemini (the video goes to the model session); nothing is forwarded', flush=True)
    print(f'[worker] agent {a.agent_name!r}; mode {describe_mode(a)}; '
          f'audio {"OFF (events only)" if a.events_only else "cue player"}; voice {a.voice}{" (" + (a.voice_model or "default model") + ", " + a.voice_name + ")" if a.voice != "off" else ""}; '
          f'handlers {a.handlers or "none"}; data channel {"on" if a.publish_data else "off"}; events -> {a.event_log}', flush=True)
    if is_competition() and rest and rest[0] in ('dev', 'start', 'connect'):
        start_heartbeat()
    sys.argv = [sys.argv[0]] + rest                           # the LiveKit Agents CLI parses the rest (dev | start | connect | download-files)
    cli.run_app(worker_options(a))
    return 0


def check_competition(a):
    """Startup checks; logs the challenge mode. Returns an error message (the worker refuses to start) or None."""
    mode = challenge_mode()
    if mode not in CHALLENGE_MODES:
        return f'unknown challenge mode (expected one of {", ".join(CHALLENGE_MODES)})'
    if mode == 'demo':
        print('[worker] challenge mode: demo (legacy path: DEMO_CLIENT_ID assignment / plan; no gatekeeping, nothing sent to the dispatcher)', flush=True)
        return None
    from challenge.worker.controller import UnsupportedMode, check_modes
    if perception_off(a):
        return 'competition needs perception (--perception on): the judge and the liveness challenge run on the pose'
    missing = [k for k in ('DISPATCHER_URL', 'DISPATCHER_TOKEN') if not (os.environ.get(k) or '').strip()]
    if missing:
        return f'{" and ".join(missing)} not set: every call would be rejected (fail closed)'
    hangup = (os.environ.get('HANGUP_MODE') or 'unverified').strip(); reveal = (os.environ.get('REVEAL_MODE') or 'audio_only').strip()
    try:
        notes = check_modes(hangup, reveal)
    except UnsupportedMode as e:
        return str(e)
    try:
        __import__('importlib').import_module('challenge.judge.liveness')   # the anti-replay check must exist before any call is scored
    except ImportError as e:
        return f'liveness challenge unavailable ({e})'
    print(f'[worker] challenge mode: COMPETITION (line {os.environ.get("LINE_ID") or "line-1"}, dispatcher {os.environ["DISPATCHER_URL"]}, '
          f'CALLER_ID_SOURCE {(os.environ.get("CALLER_ID_SOURCE") or "claim_window").strip()}, HANGUP_MODE {hangup}, REVEAL_MODE {reveal}); '
          f'push-ups only, strict judge on, no DEMO_CLIENT_ID', flush=True)
    for n in notes: print(f'[worker] {n}', flush=True)
    return None


def start_heartbeat(every_s=HEARTBEAT_EVERY_S):
    """The worker's DB heartbeat (ch_heartbeat 'worker:<line>' and 'worker' via POST /calls/heartbeat) every 30 s from a
    daemon thread of the supervisor process (alive while the worker is, between calls too). A failed beat is logged."""
    from challenge.worker.client import DispatcherError, heartbeat_sync
    url, token = os.environ['DISPATCHER_URL'], os.environ['DISPATCHER_TOKEN']; line = os.environ.get('LINE_ID') or 'line-1'
    detail = dict(pid=os.getpid(), agent=os.environ.get('AGENT_NAME', 'brodie-coach'), hangup_mode=(os.environ.get('HANGUP_MODE') or 'unverified').strip())

    def loop():
        fails = 0
        while True:
            healthy, job = supervisor_health()
            if not healthy: log.error('worker job unhealthy: %s', job)
            try:
                heartbeat_sync(url, token, line, dict(detail, **job), healthy=healthy); fails = 0
            except DispatcherError as e:
                fails += 1
                log.error('worker heartbeat failed (%d in a row): %s', fails, e)
                if fails in (1, 10) or fails % 60 == 0: print(f'[worker] heartbeat failed ({fails} in a row): {e}', flush=True)
            time.sleep(every_s)
    t = threading.Thread(target=loop, daemon=True, name='worker-heartbeat'); t.start()
    return t


if __name__ == '__main__':
    sys.exit(main())
