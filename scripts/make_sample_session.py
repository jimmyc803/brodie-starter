"""Write db/fixtures/sample_session.json: one finished session in the shape of db/schema.sql, scored with shared/scoring.py.

python scripts/make_sample_session.py          # rewrites the fixture (deterministic: fixed ids, tokens and times)

The story (modeled on the run3 recording): squats 9 of 10 (timeout) with two 'knees over toes', pushups 5 of 8 with form
falling apart late, jumping jacks 20 of 20 with two 'only arms' near the end, lunges 8 of 10 with two late 'leaning forward'.
That gives the recap all three colors: chest and triceps red, shoulders yellow, legs green.
"""
import json, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shared.scoring import set_scores, muscle_scores  # noqa: E402

NS = uuid.UUID('6f1c2d3e-0000-4000-8000-00000000b347')
def uid(name): return str(uuid.uuid5(NS, name))
T0 = datetime(2026, 10, 11, 14, 5, 0, tzinfo=timezone.utc)
def ts(s): return (T0 + timedelta(seconds=s)).isoformat().replace('+00:00', 'Z')

KOT, INS, HIPS = 'squats - knees over toes', 'pushups - insufficient', 'pushups - elevated hips'
ARMS, LEAN = 'jumping jacks - only arms', 'alternating forward lunges - leaning forward'
# (exercise, planned, closed_by, start_s, rep interval s, faults per counted rep)
PLAN = [
    ('squats', 10, 'timeout', 3.0, 3.0, [[], [], [KOT], [], [], [], [KOT], [], []]),
    ('pushups', 8, 'timeout', 86.0, 2.6, [[], [], [INS], [INS, HIPS], [INS]]),
    ('jumping jacks', 20, 'target', 172.0, 1.1, [[]] * 16 + [[ARMS], [], [ARMS], []]),
    ('lunges', 10, 'timeout', 205.0, 2.8, [[]] * 5 + [[LEAN], [], [LEAN]]),
]
REST_S = 5.0

coach = {'id': uid('coach'), 'name': 'Coach Demo', 'persona': 'High energy gym coach. Short, punchy encouragement.',
         'phone': None, 'dashboard_token': 'demo-coach-dash-Q2b9xVt0mLr4Kp7NwZs1', 'created_at': ts(-86400)}
client = {'id': uid('client'), 'coach_id': coach['id'], 'name': 'Alex Rivera', 'phone': None, 'created_at': ts(-86400)}
day = {'id': uid('day1'), 'program_id': uid('program'), 'day_number': 1, 'title': 'Day 1 - Full body starter',
       'exercises': [{'exercise': e, 'sets': 1, 'reps': p} for e, p, *_ in PLAN], 'created_at': ts(-86400)}

sets_out, scoring_in, t_end = [], [], 0.0
for i, (ex, planned, closed_by, start, step, faults) in enumerate(PLAN, 1):
    set_id = uid(f'set{i}')
    reps = [{'id': uid(f'set{i}-rep{n}'), 'set_id': set_id, 'rep_number': n, 'exercise': ex,
             't_offset_s': round(start + 1.5 + step * (n - 1), 1), 'confidence': 1.0 if n % 4 else 0.67, 'faults': f}
            for n, f in enumerate(faults, 1)]
    end = start + (75.0 if closed_by == 'timeout' else step * len(faults) + 1.5)
    sc = set_scores(planned, faults)
    sets_out.append({'id': set_id, 'session_id': uid('session'), 'set_number': i, 'exercise': ex, 'planned_reps': planned,
                     'done_reps': len(faults), 'closed_by': closed_by, 'status': 'done' if len(faults) >= planned else 'partial', 'source': 'brodie', 'started_at': ts(start), 'ended_at': ts(end), **sc,
                     'reps': reps})
    scoring_in.append({'set_number': i, 'exercise': ex, 'quality': sc['quality'], 'faults': [x for f in faults for x in f]})
    t_end = end

session = {'id': uid('session'), 'client_id': client['id'], 'program_day_id': day['id'], 'status': 'done',
           'started_at': ts(0), 'ended_at': ts(t_end + 3), 'room': 'beatmuse-demo-01',
           'plan': ','.join(f'{e}:{p}' for e, p, *_ in PLAN),
           'client_token': 'demo-client-7hK2pXq9LmV4sTz8RwN3', 'coach_token': 'demo-coach-Jf5cY1nB8eQ6uA0dGh2W',
           'recap_image_path': f"recaps/{uid('session')}.png",
           'overall_score': round(sum(s['quality'] for s in sets_out) / len(sets_out), 3), 'created_at': ts(0)}
ms = [{'id': uid(f"ms-{m['muscle']}"), 'session_id': session['id'], **m} for m in muscle_scores(scoring_in)]

fixture = {'_doc': 'One finished session, shaped like db/schema.sql rows. Nested for convenience: sets[].reps[] are the reps '
                   'rows. Regenerate with python scripts/make_sample_session.py. Tokens here are fake demo values.',
           'session': session, 'client': client, 'coach': coach, 'program_day': day, 'sets': sets_out, 'muscle_scores': ms}
out = ROOT / 'db/fixtures/sample_session.json'
out.write_text(json.dumps(fixture, indent=2) + '\n')
print(f'wrote {out.relative_to(ROOT)}')
for s in sets_out: print(f"  set {s['set_number']} {s['exercise']:14} {s['done_reps']}/{s['planned_reps']} quality {s['quality']}")
for m in ms: print(f"  {m['muscle']:11} {m['score']:.3f} {m['color']}")
