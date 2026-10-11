import copy

import pytest

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


@pytest.mark.parametrize('field,value', [
    ('sets', 0), ('sets', -1), ('sets', 101), ('sets', True),
    ('sets', '2'), ('sets', 1.5), ('sets', None),
    ('reps', 0), ('reps', -2), ('reps', 1001), ('reps', False),
    ('reps', '10'), ('reps', 2.5), ('reps', None),
])
def test_rejects_invalid_supported_counts(field, value):
    row = copy.deepcopy(ROW)
    row['program_days']['exercises'][0][field] = value
    assert load_assignment('cid', FakeDb([row])) is None


@pytest.mark.parametrize('field', ['sets', 'reps'])
def test_rejects_missing_supported_counts(field):
    row = copy.deepcopy(ROW)
    del row['program_days']['exercises'][0][field]
    assert load_assignment('cid', FakeDb([row])) is None


def test_accepts_count_boundaries():
    row = copy.deepcopy(ROW)
    row['program_days']['exercises'] = [
        {'exercise_key': 'bicep_curl', 'supported': True, 'sets': 100, 'reps': 1000}]
    result = load_assignment('cid', FakeDb([row]))
    assert len(result['plan'].split(',')) == 100
    assert result['plan'].split(',')[0] == 'bicep curls:1000'


def test_no_raw_database_error_in_logs(capsys):
    class BrokenDb:
        def select(self, *args, **kwargs):
            raise RuntimeError('secret-token-and-private-response')
    assert load_assignment('cid', BrokenDb()) is None
    assert 'secret-token-and-private-response' not in capsys.readouterr().out


def test_manual_only_assignment_is_unavailable():
    row = copy.deepcopy(ROW)
    row['program_days']['exercises'] = [
        {'exercise_key': None, 'name': 'Bench press', 'supported': False, 'sets': 3, 'reps': 8}]
    assert load_assignment('cid', FakeDb([row])) is None
