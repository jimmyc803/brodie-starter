"""SessionSink on synthetic events: squat 2x3, pushup 1x2, the call ends during pushup set 1 after 1 rep."""
import json
import uuid
from pathlib import Path

from facetime.session_sink import SessionSink

MUSCLE_COUNT = len(json.loads((Path(__file__).resolve().parents[1] / 'shared' / 'muscles.json').read_text())['muscles'])

ITEMS = [{'exercise_key': 'squat', 'name': 'Squats', 'sets': 2, 'reps': 3, 'supported': True},
         {'exercise_key': 'pushup', 'name': 'Push-ups', 'sets': 1, 'reps': 2, 'supported': True}]
PLAN = 'squats:3,squats:3,pushups:2'


class FakeDb:
    def __init__(self): self.inserts, self.updates = [], []
    def insert(self, table, rows):
        one = isinstance(rows, dict)
        out = [{'id': str(uuid.uuid4()), 'share_token': 'tok', **r} for r in ([rows] if one else rows)]
        self.inserts.append((table, out))
        return out[0] if one else out
    def select(self, table, **kw): return []
    def update(self, table, patch, **kw): self.updates.append((table, patch, kw)); return []


def S(t, state, item, count=0): return {'type': 'session', 't': t, 'state': state, 'item': item, 'count': count}
def R(t, n): return {'type': 'rep', 't': t, 'n': n}
def F(t, label): return {'type': 'fault', 't': t, 'label': label}


EVENTS = [S(10.0, 'wait', 0), S(12.0, 'active', 0), R(13.0, 1), F(13.5, 'squats - shallow'), R(14.0, 2), R(15.0, 3),
          F(15.5, 'squats - knees over toes'), S(16.0, 'rest', 0, 3),
          S(21.0, 'wait', 1), S(22.0, 'active', 1), R(23.0, 1), R(24.0, 2), R(25.0, 3), S(26.0, 'rest', 1, 3),
          S(31.0, 'wait', 2), S(32.0, 'active', 2), R(33.0, 1)]


def run():
    db = FakeDb()
    sink = SessionSink('c1', 'd1', ITEMS, PLAN, db=db)
    assert sink.start()['session_id']
    for e in EVENTS:
        sink.on_event(e)
    return sink, db, sink.finish('hangup')


def test_sets_and_faults():
    _, _, v = run()
    sets = [(ex['exercise_key'], s['set_number'], s['completed_reps']) for ex in v['exercises'] for s in ex['sets']]
    assert sets == [('squat', 1, 3), ('squat', 2, 3), ('pushup', 1, 1)]
    s1 = v['exercises'][0]['sets'][0]['reps']
    assert [r['faults'] for r in s1] == [[], ['squats - shallow'], ['squats - knees over toes']]
    assert s1[0]['t'] == 3.0                                      # relative to the first event's t
    assert all(s['started_at'] and s['ended_at'] for ex in v['exercises'] for s in ex['sets'])


def test_muscles():
    _, _, v = run()
    m = {r['muscle']: r for r in v['muscles']}
    assert len(v['muscles']) == MUSCLE_COUNT
    assert m['chest']['color'] != 'gray' and m['triceps']['coverage'] == 'primary'   # the one pushup counts
    assert m['quads']['color'] != 'gray' and m['biceps']['color'] == 'gray'


def test_finish_once_and_db_matches_view():
    sink, db, v = run()
    n = len(db.inserts)
    assert sink.finish() is v and len(db.inserts) == n and len(db.updates) == 1
    got = {t: rows for t, rows in db.inserts}
    assert [t for t, _ in db.inserts] == ['sessions', 'sets', 'reps', 'muscle_scores']
    view_sets = [{'exercise_key': ex['exercise_key'], **{k: s[k] for k in s if k != 'reps'}} for ex in v['exercises'] for s in ex['sets']]
    assert [{k: r[k] for k in view_sets[0]} for r in got['sets']] == view_sets
    assert all(r['session_id'] == v['session']['id'] for r in got['sets'] + got['muscle_scores'])
    set_of = {r['id']: (r['exercise_key'], r['set_number']) for r in got['sets']}
    db_reps = [(set_of[r['set_id']], r['rep_number'], r['t'], r['faults']) for r in got['reps']]
    assert db_reps == [((ex['exercise_key'], s['set_number']), r['rep_number'], r['t'], r['faults'])
                       for ex in v['exercises'] for s in ex['sets'] for r in s['reps']]
    assert [{k: r[k] for k in ('muscle', 'score', 'color', 'coverage')} for r in got['muscle_scores']] == v['muscles']
    assert db.updates[0][1] == {'ended_at': v['session']['ended_at']}
    row = got['sessions'][0]                     # ids are made locally; the row carries exactly them (one row)
    assert (row['id'], row['share_token']) == (v['session']['id'], v['session']['share_token']) and len(row['share_token']) == 32


def test_unplanned_sets_and_derived_items():
    # a day item Brodie never runs keeps its sets at 0; no items -> one set per plan item
    items = ITEMS + [{'exercise_key': 'bicep_curl', 'name': 'Bicep curls', 'sets': 3, 'reps': 12, 'supported': True}]
    sink = SessionSink('c1', 'd1', items, PLAN, db=FakeDb()); sink.start()
    v = sink.finish()
    assert [(e['exercise_key'], len(e['sets'])) for e in v['exercises']] == [('squat', 2), ('pushup', 1), ('bicep_curl', 3)]
    assert all(s['completed_reps'] == 0 and s['reps'] == [] for e in v['exercises'] for s in e['sets'])
    sink = SessionSink('c1', 'd1', None, PLAN, db=FakeDb()); sink.start()
    v = sink.finish()
    assert [(e['exercise_key'], e['planned_sets'], e['planned_reps']) for e in v['exercises']] == [('squat', 2, 3), ('pushup', 1, 2)]


def test_db_errors_never_raise():
    class Broken(FakeDb):
        def insert(self, table, rows): raise RuntimeError('down')
    sink = SessionSink('c1', 'd1', ITEMS, PLAN, db=Broken())
    ids = sink.start()
    assert ids['session_id'] and len(ids['share_token']) >= 24
    for e in EVENTS:
        sink.on_event(e)
    v = sink.finish()
    assert v['session']['id'] == ids['session_id'] and sink.view_path.exists()


def test_start_in_flight_never_duplicates_and_events_flow():
    """finish() while start()'s insert is still running: one sessions row, and on_event never waits on the network."""
    import threading, time
    gate = threading.Event()
    class SlowDb(FakeDb):
        def insert(self, table, rows):
            if table == 'sessions': gate.wait(2)
            return super().insert(table, rows)
    db = SlowDb()
    sink = SessionSink('c1', 'd1', ITEMS, PLAN, db=db)
    th = threading.Thread(target=sink.start); th.start()
    t0 = time.monotonic()
    for e in EVENTS: sink.on_event(e)
    assert time.monotonic() - t0 < 0.5                 # not blocked by the slow insert
    fin = threading.Thread(target=sink.finish, args=('hangup',)); fin.start()
    time.sleep(0.1); gate.set(); th.join(3); fin.join(3)
    assert sum(1 for t, _ in db.inserts if t == 'sessions') == 1
    assert [t for t, _ in db.inserts] == ['sessions', 'sets', 'reps', 'muscle_scores']
