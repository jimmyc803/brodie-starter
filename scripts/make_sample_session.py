"""Write db/fixtures/sample_session.json in the SESSION VIEW shape (what GET /api/session/[token] returns and what the recap
page and image read), scored with shared/scoring.py. Deterministic (fixed ids, tokens, times).

python scripts/make_sample_session.py

Story: coach Tristan, client Ryan, Day 1 = squats 3x10, pushups 3x8, lunges 2x10, bicep curls 3x12. A few faults, a weaker
last set of squats and pushups, lunges and curls cut short, so every color appears.
"""
import json, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.scoring import muscle_scores, RULES  # noqa: E402

NS = uuid.UUID('6f1c2d3e-0000-4000-8000-00000000b347')
def uid(name): return str(uuid.uuid5(NS, name))
T0 = datetime(2026, 10, 11, 14, 5, 0, tzinfo=timezone.utc)
def ts(s): return (T0 + timedelta(seconds=s)).isoformat().replace('+00:00', 'Z')

KOT, SHAL, INS, HIPS, LEAN, CURL = ('squats - knees over toes', 'squats - shallow', 'pushups - insufficient',
                                    'pushups - elevated hips', 'alternating forward lunges - leaning forward', 'bicep curls - swinging')
# exercise_key, planned sets, planned reps, per set: list of faults per counted rep (len = completed reps)
DAY = [
    ('squat', 3, 10, [[[]] * 10, [[], [], [KOT], [], [], [], [], [], [], []], [[], [SHAL], [], [SHAL], [KOT], [], [SHAL], [], []]]),
    ('pushup', 3, 8, [[[]] * 8, [[], [], [], [INS], [], [], [], [INS]], [[], [INS], [INS, HIPS], [INS], [HIPS], []]]),
    ('lunge', 2, 10, [[[], [], [], [LEAN], [], [], [], [], [], []], [[], [], [], [], [LEAN], [], [LEAN]]]),
    ('bicep_curl', 3, 12, [[[CURL], [], [CURL], [], [CURL], [], [], [CURL], [], [CURL], [], []], [[CURL]] * 10, []]),
]
t = 3.0
exercises = []
for key, nsets, reps, sets_faults in DAY:
    sets = []
    for n in range(1, nsets + 1):
        faults = sets_faults[n - 1] if n - 1 < len(sets_faults) else []
        start = t; step = 2.6
        rep_rows = [{'rep_number': i, 't': round(start + 1.5 + step * (i - 1), 1), 'faults': f} for i, f in enumerate(faults, 1)]
        end = start + step * len(faults) + 2 if faults else None
        sets.append({'set_number': n, 'planned_reps': reps, 'completed_reps': len(faults),
                     'started_at': ts(start) if faults else None, 'ended_at': ts(end) if faults else None, 'reps': rep_rows})
        t = (end or t) + 20.0        # rest
    exercises.append({'exercise_key': key, 'name': RULES['exercises'][key]['name'], 'planned_sets': nsets, 'planned_reps': reps, 'sets': sets})

view = {
    '_doc': 'Session view shape: GET /api/session/[share_token]. Regenerate with python scripts/make_sample_session.py. Demo tokens are fake.',
    'session': {'id': uid('session'), 'started_at': ts(0), 'ended_at': ts(t), 'share_token': 'demo-session-7hK2pXq9LmV4sTz8RwN3bC6d',
                'recap_image_path': f"{uid('session')}.png"},
    'client': {'id': '00000000-0000-4000-8000-00000000c11e', 'name': 'Ryan'},
    'coach': {'id': '00000000-0000-4000-8000-00000000c0ac', 'name': 'Tristan', 'share_token': 'demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c'},
    'day': {'id': '00000000-0000-4000-8000-00000000da01', 'title': 'Day 1 - Full body', 'day_number': 1},
    'exercises': exercises,
    'muscles': muscle_scores(exercises),
}
out = ROOT / 'db/fixtures/sample_session.json'
out.write_text(json.dumps(view, indent=2) + '\n')
print(f'wrote {out.relative_to(ROOT)}')
for e in exercises:
    print(f"  {e['exercise_key']:12} " + ' '.join(f"{s['completed_reps']}/{s['planned_reps']}" for s in e['sets']))
for m in view['muscles']:
    print(f"  {m['muscle']:12} {m['score']:.3f} {m['color']:6} {m['coverage']}")
