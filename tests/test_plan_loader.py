from facetime.plan_loader import load_assignment, persona_text


class FakeDb:
    def __init__(self, rows): self.rows = rows
    def select(self, table, **kw): return self.rows


ROW = {'program_day_id': 'd1', 'clients': {'name': 'Ryan'},
       'program_days': {'id': 'd1', 'title': 'Day 1 - Full body',
                        'day_number': 1, 'exercises': [{'exercise_key': 'squat', 'name': 'Squats', 'sets': 2, 'reps': 10, 'supported': True},
                                      {'exercise_key': None, 'name': 'Bicep curls', 'sets': 1, 'reps': 5, 'supported': False},
                                      {'exercise_key': 'pushup', 'name': 'Pushups', 'sets': 1, 'reps': 8, 'supported': True}],
                        'programs': {'coach_id': 'c', 'coaches': {'name': 'Tristan', 'persona': 'Be blunt'}}}}


def test_plan():
    r = load_assignment('cid', FakeDb([ROW]))
    assert r['plan'] == 'squats:10,squats:10,pushups:8'
    assert (r['coach_name'], r['client_name'], r['program_day_id'], r['persona']) == ('Tristan', 'Ryan', 'd1', 'Be blunt')


def test_items():
    r = load_assignment('cid', FakeDb([ROW]))
    assert len(r['items']) == 3 and r['day_number'] == 1


def test_none():
    assert load_assignment('cid', FakeDb([])) is None
    assert load_assignment(None) is None


def test_persona_text():
    r = load_assignment('cid', FakeDb([ROW]))
    assert persona_text('BASE', r) == "BASE\n\nThe client's name is Ryan. Their coach Tristan says: Be blunt."
    assert persona_text('BASE', None) == 'BASE'
