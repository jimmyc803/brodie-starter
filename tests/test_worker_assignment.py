"""Assignment selection must never turn a client's missing workout into a demo."""
import pytest
from facetime import worker
from facetime import plan_loader
from tests.test_plan_loader import FakeDb, ROW


@pytest.fixture(autouse=True)
def isolated_plan_env(monkeypatch):
    for key in ('PLAN', 'PLAN_FILE', 'DEMO_CLIENT_ID', 'PERCEPTION', worker.ARGS_ENV):
        monkeypatch.delenv(key, raising=False)


def args(*flags):
    return worker.build_parser().parse_args(list(flags))


@pytest.mark.parametrize('rows', [[], [{'program_days': {'exercises': []}}]])
def test_missing_client_assignment_refuses_demo(monkeypatch, rows):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    monkeypatch.setattr('facetime.supa.Supa.available', lambda: True)
    monkeypatch.setattr('facetime.supa.Supa.__init__', lambda self: None)
    monkeypatch.setattr('facetime.supa.Supa.select', lambda self, *a, **kw: rows)
    with pytest.raises(RuntimeError, match='assignment'):
        worker.resolve_mode(args())


def test_assignment_without_database_refuses_demo(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    monkeypatch.setattr('facetime.supa.Supa.available', lambda: False)
    with pytest.raises(RuntimeError, match='assignment'):
        worker.resolve_mode(args())


def test_assigned_workout_selected(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    loaded = plan_loader.load_assignment('cid', FakeDb([ROW]))
    monkeypatch.setattr(plan_loader, 'load_assignment', lambda cid: loaded)
    result = worker.resolve_mode(args())
    assert result.plan == 'squats:10,squats:10,pushups:8'
    assert result.assignment['program_day_id'] == 'd1'


def test_no_client_retains_demo():
    result = worker.resolve_mode(args('--plan-file', '/nonexistent'))
    assert result.plan == worker.DEFAULT_PLAN


@pytest.mark.parametrize('flags,plan', [
    (('--plan', 'squats:3'), 'squats:3'),
    (('--exercise', 'squats'), None),
    (('--auto',), None),
    (('--perception', 'off'), None),
])
def test_explicit_manual_modes_preserved(monkeypatch, flags, plan):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    def unexpected_lookup(cid):
        pytest.fail('manual mode should not look up an assignment')
    monkeypatch.setattr(plan_loader, 'load_assignment', unexpected_lookup)
    assert worker.resolve_mode(args(*flags)).plan == plan


def test_explicit_env_plan_preserved(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    monkeypatch.setenv('PLAN', 'pushups:4')
    assert worker.resolve_mode(args()).plan == 'pushups:4'


def test_startup_defers_assignment_lookup(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    def unexpected_lookup(cid):
        pytest.fail('assignment must be read at call start, not startup/prewarm')
    monkeypatch.setattr(plan_loader, 'load_assignment', unexpected_lookup)
    result = worker.resolve_mode(args(), load_client=False)
    assert result.plan is None
    assert worker.load_args(load_client=False).plan is None


def test_job_uses_fresh_assignment_after_prewarm(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    old = args('--plan', 'squats:99')
    old.assignment = {'program_day_id': 'old'}
    pipe = object()
    ctx = SimpleNamespace(proc=SimpleNamespace(userdata={
        'args': old, 'cfg': worker.Config.from_args(old), 'pipe': pipe, 'bank': object()}),
        job=SimpleNamespace(metadata='{}'))
    loaded = plan_loader.load_assignment('cid', FakeDb([ROW]))
    monkeypatch.setattr(plan_loader, 'load_assignment', lambda cid: loaded)
    observed = []
    class RecordingJob:
        def __init__(self, ctx, a, cfg, actual_pipe, bank, md):
            observed.append((a, cfg, actual_pipe))
        async def run(self):
            pass
    monkeypatch.setattr(worker, 'CoachJob', RecordingJob)
    asyncio.run(worker.entrypoint(ctx))
    a, cfg, actual_pipe = observed[0]
    assert a.assignment['program_day_id'] == 'd1'
    assert a.plan == cfg.plan == 'squats:10,squats:10,pushups:8'
    assert actual_pipe is pipe


def test_job_aborts_before_starting_if_assignment_was_removed(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    monkeypatch.setenv('DEMO_CLIENT_ID', 'cid')
    monkeypatch.setattr(plan_loader, 'load_assignment', lambda cid: None)
    shutdown = []
    ctx = SimpleNamespace(proc=SimpleNamespace(userdata={
        'args': args('--plan', 'squats:99'), 'pipe': object(), 'bank': object()}),
        shutdown=lambda reason: shutdown.append(reason))
    def unexpected_job(*a, **kw):
        pytest.fail('no workout should start without the client assignment')
    monkeypatch.setattr(worker, 'CoachJob', unexpected_job)
    asyncio.run(worker.entrypoint(ctx))
    assert shutdown == ['client assignment unavailable']
