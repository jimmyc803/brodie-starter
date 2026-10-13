"""A FaceTime line worker (BRODIE_LINE): the caller is matched to the line's reservation at the bind, the session starts then,
and the line is released when the job closes. Offline: fake room/db, Perception and the voice stubbed out."""
import asyncio
from types import SimpleNamespace

import pytest

from facetime import lines, worker
from tests.test_session_sink import ITEMS, PLAN
from tests.test_worker_recap import caller, env, settle  # noqa: F401  (env: fake sink + recap card)


@pytest.fixture
def line(monkeypatch, env):  # noqa: F811
    monkeypatch.setenv('BRODIE_LINE', 'line1')
    calls = SimpleNamespace(taken=[], released=[], loaded=[], started=0, claim={'claim_id': 'k1', 'client_id': 'cl-7'})

    def take(l): calls.taken.append(l); return calls.claim
    def load(**kw):
        calls.loaded.append(kw)
        if kw.get('guest'): return SimpleNamespace(plan=PLAN, assignment=None, client_id=None, guest=True, voice='off', handlers=None)
        return SimpleNamespace(plan=PLAN, assignment={'program_day_id': 'd1', 'items': ITEMS}, client_id=kw.get('client_id'), guest=False, voice='off', handlers=None)
    monkeypatch.setattr(worker, 'take_claim', take)
    monkeypatch.setattr(worker, 'release_line', lambda l, c=None: calls.released.append((l, c)))
    monkeypatch.setattr(worker, 'load_args', load)
    monkeypatch.setattr(worker.Config, 'from_args', staticmethod(lambda a: SimpleNamespace()))
    monkeypatch.setattr(worker.CoachJob, 'start_session', lambda self: (setattr(self, 'session_started', True), setattr(calls, 'started', calls.started + 1)))
    calls.env = env
    return calls


def make_job():
    room = SimpleNamespace(name='chert-op1', connection_state=None)
    ctx = SimpleNamespace(room=room, job=SimpleNamespace(id='j1'), shutdown=lambda reason=None: None)
    a = SimpleNamespace(plan=None, assignment=None, publish_data=False, data_topic='t', latency_probe=False, leave_grace_s=0, voice='off')
    job = worker.CoachJob(ctx, a, None, None, None, {'chert_warm': True})
    job.room_connected = lambda: True
    return job


def test_reserved_caller_gets_their_day_and_session(line):
    async def go():
        job = make_job(); assert job.line == 'line1'
        job.bind(caller(), 'video'); await settle(); return job
    job = asyncio.run(go())
    assert line.taken == ['line1'] and line.loaded == [{'client_id': 'cl-7'}]
    assert line.started == 1 and job.warm is False
    assert job.recap is not None and job.recap.sink.client_id == 'cl-7'


def test_walk_in_runs_the_demo_and_saves_nothing(line):
    line.claim = None
    async def go():
        job = make_job(); job.bind(caller(), 'video'); await settle(); return job
    job = asyncio.run(go())
    assert line.loaded == [{'guest': True}] and line.started == 1
    assert job.recap is None


def test_release_on_close_only_after_a_caller(line):
    async def go():
        idle = make_job(); await idle.aclose()
        job = make_job(); job.bind(caller(), 'video'); await settle(); await job.aclose(); await settle()
    asyncio.run(go())
    assert line.released == [('line1', 'k1')]


def test_take_claim_never_raises():
    class Boom:
        def rpc(self, *a, **k): raise RuntimeError('down')
    assert lines.take_claim('line1', db=Boom()) is None
    lines.release('line1', 'k1', db=Boom())


def test_take_claim_reads_the_row():
    class Db:
        def rpc(self, fn, **k): return [{'claim_id': 'k9', 'client_id': 'c9'}] if fn == 'take_line_claim' else None
    assert lines.take_claim('line1', db=Db()) == {'claim_id': 'k9', 'client_id': 'c9'}
