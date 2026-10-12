"""Discovery agent for the Chert line (SPEC §3 #1, #3, #4): joins every dispatched room, never touches media, and logs the full
chert_call payload, participant identities/attributes/metadata and timings to data/tmp/discover/<ts>.jsonl.

  PYTHONPATH=src:. .venv/bin/python scripts/discover_chert.py dev [--leave-after-s N]

--leave-after-s N: the agent leaves the room N s after connecting, so testers can see whether FaceTime hangs up.
Env: LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET, AGENT_NAME (default brodie-coach).
WARNING: the log contains caller handles (phone/email). data/ is gitignored; do not share the file."""
import argparse, asyncio, json, os, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / 'data' / 'tmp' / 'discover'
LEAVE_ENV = 'DISCOVER_LEAVE_AFTER_S'


def parse_json(md):
    """Metadata is usually JSON; keep the raw string when it is not."""
    if not md: return None
    try: return json.loads(md)
    except ValueError: return {'raw': md}


def describe_participant(p):
    return dict(identity=getattr(p, 'identity', None), name=getattr(p, 'name', None), kind=str(getattr(p, 'kind', None)),
                attributes=dict(getattr(p, 'attributes', None) or {}), metadata=parse_json(getattr(p, 'metadata', None)))


class DiscoveryLog:
    """Append-only JSONL writer; every line has t (epoch s), dt (s since the job started) and ev."""
    def __init__(self, path, clock=time.time):
        self.path = Path(path); self.clock = clock; self.t0 = clock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, ev, **kw):
        t = self.clock()
        rec = dict(t=t, dt=round(t - self.t0, 3), ev=ev, **kw)
        with open(self.path, 'a') as f: f.write(json.dumps(rec, default=str) + '\n')
        return rec

    def job(self, job_id, room_name, metadata, dispatch_ts=None):
        md = parse_json(metadata)
        return self.write('job', job_id=job_id, room=room_name, metadata=md, chert_call=(md or {}).get('chert_call') if isinstance(md, dict) else None,
                          dispatch_lag_s=(round(self.t0 - dispatch_ts, 3) if dispatch_ts else None))

    def connected(self, room_name, remote):
        return self.write('connected', room=room_name, participants=[describe_participant(p) for p in remote])

    def participant_joined(self, p): return self.write('participant_connected', participant=describe_participant(p))
    def participant_left(self, p): return self.write('participant_disconnected', participant=describe_participant(p))
    def first_frame(self, p, kind): return self.write('first_frame', identity=getattr(p, 'identity', None), kind=kind)  # timing only, no pixels
    def room_closed(self, reason=None): return self.write('room_disconnected', reason=str(reason) if reason is not None else None)
    def leaving(self, after_s): return self.write('agent_leaving', after_s=after_s)


async def first_frame_of(track, p, log, make_stream):
    """Wait for ONE frame from the track, log its arrival time (no pixels/samples kept), close the stream."""
    stream = make_stream(track)
    try:
        async for _ in stream:                               # the event is dropped at once; only the timing is recorded
            log.first_frame(p, str(getattr(track, 'kind', 'unknown'))); break
    finally:
        await stream.aclose()


def attach(room, log, make_stream=None, spawn=None):
    """Wire room events to the log. Returns the handlers (for tests). Media is never stored: a subscription only starts a
    task that waits for one frame (first_frame is logged on receipt, not on subscription)."""
    seen = set(); tasks = []
    if make_stream is None:
        from livekit import rtc
        def make_stream(track):
            return rtc.VideoStream(track) if track.kind == rtc.TrackKind.KIND_VIDEO else rtc.AudioStream(track)
    spawn = spawn or (lambda c: tasks.append(asyncio.ensure_future(c)))
    def on_join(p): log.participant_joined(p)
    def on_left(p): log.participant_left(p)
    def on_sub(track, pub, p):
        k = (getattr(p, 'identity', None), str(getattr(track, 'kind', '')))
        if k in seen: return
        seen.add(k); spawn(first_frame_of(track, p, log, make_stream))
    def on_attrs(changed, p): log.write('participant_attributes_changed', identity=getattr(p, 'identity', None), changed=dict(changed))
    def on_disc(reason=None): log.room_closed(reason)
    room.on('participant_connected', on_join); room.on('participant_disconnected', on_left)
    room.on('track_subscribed', on_sub); room.on('participant_attributes_changed', on_attrs); room.on('disconnected', on_disc)
    return dict(join=on_join, left=on_left, sub=on_sub, attrs=on_attrs, disc=on_disc, tasks=tasks)


async def entrypoint(ctx):
    from livekit.agents import AutoSubscribe
    log = DiscoveryLog(OUT_DIR / f'{time.strftime("%Y%m%dT%H%M%S")}-{ctx.job.id}.jsonl')
    log.job(ctx.job.id, getattr(ctx.room, 'name', None), ctx.job.metadata)
    attach(ctx.room, log)
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)   # one frame per track is awaited for timing, then dropped; nothing is stored
    log.connected(ctx.room.name, ctx.room.remote_participants.values())
    leave = float(os.environ.get(LEAVE_ENV) or 0)
    if leave > 0:
        await asyncio.sleep(leave); log.leaving(leave); ctx.shutdown(reason='discover --leave-after-s')
    print(f'[discover] logging to {log.path}', flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--leave-after-s', type=float, default=0, help='leave the room N s after connecting (0 = stay until the room closes)')
    ap.add_argument('--agent-name', default=os.environ.get('AGENT_NAME', 'brodie-coach'))
    a, rest = ap.parse_known_args(sys.argv[1:] if argv is None else argv)
    from livekit.agents import WorkerOptions, cli
    os.environ[LEAVE_ENV] = str(a.leave_after_s)
    print(f'[discover] WARNING: logs in {OUT_DIR} contain caller handles (unredacted); data/ is gitignored. Never share or commit them.', flush=True)
    sys.argv = [sys.argv[0]] + rest
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name=a.agent_name))
    return 0


if __name__ == '__main__':
    sys.exit(main())
