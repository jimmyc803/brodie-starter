"""CallRecap: the worker's glue. Saves once (done and hang-up share it), shows the card only when asked and the save worked."""
import asyncio

import facetime.recap_video as rv
from facetime.call_recap import CallRecap
from tests.test_session_sink import EVENTS, ITEMS, PLAN, FakeDb, S


def make(monkeypatch, shown):
    async def fake_publish(room, png, **kw): shown.append((room, len(png)))
    monkeypatch.setattr(rv, 'publish_recap', fake_publish)
    monkeypatch.setattr(rv, 'get_recap_png', lambda view: b'\x89PNG fake')
    db = FakeDb()
    return CallRecap(PLAN, {'program_day_id': 'd1', 'items': ITEMS}, client_id='c1', db=db), db


def test_done_saves_once_and_shows(monkeypatch):
    shown = []
    rec, db = make(monkeypatch, shown)
    async def go():
        await rec.start()
        for e in EVENTS: rec.on_event(e)
        rec.on_event(S(40.0, 'done', 2, 1))
        v1 = await rec.finish('room', show=True)
        v2 = await rec.finish('room', show=True)        # a repeated done event
        await rec.show_task
        await rec.aclose()                              # hang-up after done: no second save
        return v1, v2
    v1, v2 = asyncio.run(go())
    assert v1 is v2 and v1['session']['share_token']
    assert shown == [('room', 9)]
    assert sum(1 for t, _ in db.inserts if t == 'sessions') == 1
    assert len([m for m in v1['muscles']]) == len(rv.MUSCLES['muscles'])


def test_hangup_saves_without_card(monkeypatch):
    shown = []
    rec, db = make(monkeypatch, shown)
    async def go():
        await rec.start()
        for e in EVENTS: rec.on_event(e)
        await rec.aclose()
        return rec.finished.result()
    view = asyncio.run(go())
    assert view is not None and shown == []
    squat = next(e for e in view['exercises'] if e['exercise_key'] == 'squat')
    assert [s['completed_reps'] for s in squat['sets']] == [3, 3]
