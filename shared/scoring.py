"""The green/yellow/red rule from shared/muscles.json, in one place. Pure stdlib, no I/O beyond reading the JSON once.

set_scores(planned, rep_faults)  -> {fault_rate, completion, dropoff, quality} for one set
muscle_scores(sets)              -> [{muscle, score, color, detail}] for a session; muscles no set worked are left out
The worker (task 3) and scripts/make_sample_session.py both use these, so the fixture and real sessions agree.
"""
import json
from collections import Counter
from pathlib import Path

RULES = json.loads((Path(__file__).with_name('muscles.json')).read_text())
_R = RULES['color_rule']


def set_scores(planned, rep_faults):
    """planned: target reps. rep_faults: one list of fault labels per counted rep, in order (len = done reps)."""
    done = len(rep_faults)
    flags = [1 if f else 0 for f in rep_faults]
    fault_rate = sum(flags) / done if done else 0.0
    completion = min(1.0, done / planned) if planned else 1.0
    dropoff = 0.0
    if done >= _R['dropoff_min_reps']:
        half = done // 2
        early, late = flags[:half], flags[half:]
        dropoff = max(0.0, sum(late) / len(late) - sum(early) / len(early))
    w = _R['weights']
    q = 1 - w['fault_rate'] * fault_rate - w['missed'] * (1 - completion) - w['dropoff'] * dropoff
    return {'fault_rate': round(fault_rate, 3), 'completion': round(completion, 3),
            'dropoff': round(dropoff, 3), 'quality': round(min(1.0, max(0.0, q)), 3)}


def color_for(score):
    t = _R['thresholds']
    return 'green' if score >= t['green_min'] else 'yellow' if score >= t['yellow_min'] else 'red'


def muscle_scores(sets):
    """sets: [{set_number, exercise, quality, faults: [label, ...] (every fault in the set)}]. Unknown exercises are skipped."""
    acc = {}
    for s in sets:
        ex = RULES['exercises'].get(s['exercise'])
        if not ex:
            continue
        for role in ('primary', 'secondary'):
            for m in ex[role]:
                a = acc.setdefault(m, {'num': 0.0, 'den': 0.0, 'sets': [], 'faults': Counter()})
                wt = _R['role_weights'][role]
                a['num'] += wt * s['quality']; a['den'] += wt
                a['sets'].append({'set_number': s['set_number'], 'exercise': s['exercise'], 'role': role, 'quality': s['quality']})
                a['faults'].update(s.get('faults', []))
    out = []
    for m in RULES['muscles']:             # stable order: the order in muscles.json
        if m not in acc:
            continue
        a = acc[m]; score = round(a['num'] / a['den'], 3)
        top = a['faults'].most_common(1)
        out.append({'muscle': m, 'score': score, 'color': color_for(score),
                    'detail': {'sets': a['sets'], 'top_fault': top[0][0] if top else None}})
    return out
