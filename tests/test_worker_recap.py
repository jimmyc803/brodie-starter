"""CoachJob's session-save / heat-map hooks (bind, _deliver, aclose), offline: fake room, FakeDb, patched recap_video."""
import asyncio
from types import SimpleNamespace

import pytest

import facetime.call_recap as cr
import facetime.recap_video as rv
from facetime import worker
from tests.test_session_sink import EVENTS, ITEMS, PLAN, FakeDb, S


class BadDb(FakeDb):
    def insert(self, table, rows): raise RuntimeError('supabase down')
    def update(self, table, patch, **kw): raise RuntimeError('supabase down')


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'c1')
    shown, dbs = [], []

    async def fake_publish(room, png, **kw): shown.append(room)
    monkeypatch.setattr(rv, 'publish_recap', fake_publish)
    monkeypatch.setattr(rv, 'get_recap_png', lambda view: b'\x89PNG fake')
    real = cr.SessionSink
    state = SimpleNamespace(db_cls=FakeDb, shown=shown, db=None)

    def sink(*args, db=None, **kw):
        state.db = state.db_cls()
        return real(*args, db=state.db, **kw)
    monkeypatch.setattr(cr, 'SessionSink', sink)
    return state


def make_job(plan=PLAN, warm=False, connected=True):
    room = SimpleNamespace(name='room-1', connection_state=None)
    ctx = SimpleNamespace(room=room, job=SimpleNamespace(id='j1'), shutdown=lambda reason=None: None)
    a = SimpleNamespace(plan=plan, assignment={'program_day_id': 'd1', 'items': ITEMS}, publish_data=False, data_topic='t',
                        latency_probe=False, leave_grace_s=0)
    job = worker.CoachJob(ctx, a, None, None, None, {'chert_warm': True} if warm else {})
    job.room_connected = lambda: connected
    return job


def real_event(e):
    return {**e, 'exercise': 'squats'} if e['type'] == 'rep' else dict(e)   # the worker's console line reads ev['exercise']


def caller(): return SimpleNamespace(identity='caller-1')


async def settle():
    for _ in range(5):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending: return
        await asyncio.gather(*pending, return_exceptions=True)


def sessions(db): return sum(1 for t, _ in db.inserts if t == 'sessions')


def test_bind_creates_and_starts_recap(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle(); return job
    job = asyncio.run(go())
    assert job.recap is not None and job.recap.started
    assert sessions(env.db) == 1


@pytest.mark.parametrize('kind', ['warm', 'no_client', 'no_plan'])
def test_bind_no_recap(env, monkeypatch, kind):
    if kind == 'no_client': monkeypatch.delenv('DEMO_CLIENT_ID')
    async def go():
        job = make_job(plan=None if kind == 'no_plan' else PLAN, warm=kind == 'warm')
        job.bind(caller(), 'test'); await settle(); return job
    assert asyncio.run(go()).recap is None
    assert env.db is None


def test_events_reach_sink(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        for e in EVENTS: job._deliver(real_event(e))
        await job.aclose()
        return job.recap.finished.result()
    view = asyncio.run(go())
    squat = next(e for e in view['exercises'] if e['exercise_key'] == 'squat')
    assert [s['completed_reps'] for s in squat['sets']] == [3, 3]
    assert env.shown == []


def test_done_saves_once_and_publishes_once(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        for e in EVENTS: job._deliver(real_event(e))
        job._deliver(S(40.0, 'done', 2, 1)); await settle()
        job._deliver(S(41.0, 'done', 2, 1)); await settle()
        await job.aclose(); await settle()
        return job
    job = asyncio.run(go())
    assert sessions(env.db) == 1
    assert env.shown == [job.room]
    assert len([u for u in env.db.updates if u[0] == 'sessions']) == 1


def test_done_flag_variant(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        job._deliver({'type': 'session', 't': 5.0, 'state': 'active', 'item': 0, 'count': 0, 'done': True}); await settle()
    asyncio.run(go())
    assert len(env.shown) == 1


def test_hangup_saves_without_card_and_no_double_save(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        for e in EVENTS: job._deliver(real_event(e))
        await job.aclose(); await settle()
        n = len(env.db.updates)
        return job, n
    job, n = asyncio.run(go())
    assert job.recap.finished.result() is not None
    assert env.shown == []
    assert n >= 1 and len(env.db.updates) == n

    async def go2():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        job._deliver(S(40.0, 'done', 2, 1)); await settle()
        n = len(env.db.updates)
        await job.aclose(); await settle()
        return n
    n2 = asyncio.run(go2())
    assert len(env.db.updates) == n2 and len(env.shown) == 1


def test_supabase_errors_never_raise(env):
    env.db_cls = BadDb
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        for e in EVENTS: job._deliver(real_event(e))
        job._deliver(S(40.0, 'done', 2, 1)); await settle()
        await job.aclose()
        return job
    job = asyncio.run(go())
    assert job.closed
    view = job.recap.finished.result()
    assert view is not None and view['exercises']
    assert env.shown == [job.room]  # card still shown from the dumped view


def test_disconnected_at_done_saves_without_publish(env):
    async def go():
        job = make_job(connected=False); job.bind(caller(), 'test'); await settle()
        for e in EVENTS: job._deliver(real_event(e))
        job._deliver(S(40.0, 'done', 2, 1)); await settle()
        return job
    job = asyncio.run(go())
    assert job.recap.finished.result() is not None
    assert env.shown == []


def test_events_after_close_ignored(env):
    async def go():
        job = make_job(); job.bind(caller(), 'test'); await settle()
        await job.aclose(); await settle()
        before = (len(env.db.inserts), len(env.db.updates))
        for e in EVENTS: job._deliver(real_event(e))
        job._deliver(S(40.0, 'done', 2, 1)); await settle()
        return before, (len(env.db.inserts), len(env.db.updates))
    before, after = asyncio.run(go())
    assert before == after and env.shown == []
