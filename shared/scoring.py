"""The scoring rule from shared/muscles.json (team contract), in one place. Pure stdlib.

exercise_quality(sets) -> {clean, completion, dropoff, quality, completed, planned}
    sets: [{planned_reps, completed_reps, reps: [{faults: [...]}, ...]}, ...] for ONE exercise, in order.
muscle_scores(exercises) -> [{muscle, score, color, coverage}] x 15 (every muscle; gray ones included)
    exercises: [{exercise_key, sets: [...as above...]}, ...]
plan_name(exercise_key) / exercise_key_for(plan_name): map between contract keys and Brodie plan names.
"""
import json
from pathlib import Path

RULES = json.loads((Path(__file__).with_name('muscles.json')).read_text())
_S = RULES['scoring']
MUSCLES = list(RULES['muscles'])


def plan_name(exercise_key):
    return RULES['exercises'][exercise_key]['plan_name']


def exercise_key_for(plan_name_):
    for k, e in RULES['exercises'].items():
        if e['plan_name'] == plan_name_:
            return k
    return None


def _clean_rate(s):
    reps = s.get('reps') or []
    return (sum(1 for r in reps if not r.get('faults')) / len(reps)) if reps else 0.0


def exercise_quality(sets):
    planned = sum(int(s.get('planned_reps') or 0) for s in sets)
    completed = sum(int(s.get('completed_reps') if s.get('completed_reps') is not None else len(s.get('reps') or [])) for s in sets)
    clean_reps = sum(1 for s in sets for r in (s.get('reps') or []) if not r.get('faults'))
    clean = clean_reps / completed if completed else 0.0
    completion = min(completed / planned, 1.0) if planned else 0.0
    done = [s for s in sets if (s.get('reps') or [])]
    dropoff = max(0.0, _clean_rate(done[0]) - _clean_rate(done[-1])) if len(done) >= 2 else 0.0
    w = _S['weights']
    q = w['clean'] * clean + w['completion'] * completion + w['dropoff'] * (1 - dropoff)
    return {'clean': round(clean, 3), 'completion': round(completion, 3), 'dropoff': round(dropoff, 3),
            'quality': round(min(1.0, max(0.0, q)), 3), 'completed': completed, 'planned': planned}


def color_for(score):
    t = _S['thresholds']
    return 'green' if score >= t['green_min'] else 'yellow' if score >= t['yellow_min'] else 'red'


def muscle_scores(exercises):
    acc = {m: {'num': 0.0, 'den': 0.0, 'coverage': 'none'} for m in MUSCLES}
    for ex in exercises:
        spec = RULES['exercises'].get(ex.get('exercise_key'))
        if not spec:
            continue
        q = exercise_quality(ex.get('sets') or [])
        if q['completed'] == 0:          # never happened: hits nothing
            continue
        for role in ('primary', 'secondary'):
            wt = _S['role_weights'][role]
            for m in spec[role]:
                a = acc[m]; a['num'] += wt * q['quality']; a['den'] += wt
                if role == 'primary' or a['coverage'] == 'none':
                    a['coverage'] = role
    out = []
    for m in MUSCLES:
        a = acc[m]
        if a['den']:
            score = round(a['num'] / a['den'], 3)
            out.append({'muscle': m, 'score': score, 'color': color_for(score), 'coverage': a['coverage']})
        else:
            out.append({'muscle': m, 'score': 0.0, 'color': 'gray', 'coverage': 'none'})
    return out
