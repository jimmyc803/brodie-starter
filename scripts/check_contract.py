"""Check the data contract: the fixture is in the session view shape, every exercise/muscle key is in shared/muscles.json,
every fault label is one Brodie knows (or bicep curls, which Ryan is adding), the muscle rows match shared/scoring.py,
and the SQL tables carry the contract's columns.  python scripts/check_contract.py -> OK or problems (exit 1)."""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from shared.scoring import RULES, muscle_scores, MUSCLES

sql = (ROOT / 'db/schema.sql').read_text()
cols = {}
for name, body in re.findall(r'create table if not exists (\w+) \((.*?)\n\);', sql, re.S):
    cols[name] = {m.group(1) for m in re.finditer(r'^\s+(\w+)\s+(?:uuid|text|int|real|jsonb|timestamptz|boolean)', body, re.M)}
NEED = {'coaches': {'id', 'name', 'share_token'}, 'clients': {'id', 'coach_id', 'name', 'share_token'},
        'programs': {'id', 'coach_id', 'title', 'pdf_path', 'parsed', 'created_at'},
        'program_days': {'id', 'program_id', 'day_number', 'title', 'exercises'},
        'assignments': {'id', 'client_id', 'program_day_id', 'active', 'assigned_at'},
        'sessions': {'id', 'client_id', 'program_day_id', 'started_at', 'ended_at', 'share_token', 'recap_image_path'},
        'sets': {'id', 'session_id', 'exercise_key', 'set_number', 'planned_reps', 'completed_reps', 'started_at', 'ended_at'},
        'reps': {'id', 'set_id', 'rep_number', 't', 'faults'}, 'muscle_scores': {'session_id', 'muscle', 'score', 'color', 'coverage'}}
problems = [f'{t}: missing columns {sorted(c - cols.get(t, set()))}' for t, c in NEED.items() if c - cols.get(t, set())]

fx = json.loads((ROOT / 'db/fixtures/sample_session.json').read_text())
cues = json.loads((ROOT / 'src/rtcoach/cues.json').read_text())
for k in ('session', 'client', 'coach', 'day', 'exercises', 'muscles'):
    if k not in fx: problems.append(f'fixture missing {k}')
for e in fx['exercises']:
    key = e['exercise_key']
    if key not in RULES['exercises']: problems.append(f'unknown exercise_key {key}'); continue
    prefix = RULES['fault_prefix'][key] + ' - '
    for s in e['sets']:
        if s['completed_reps'] != len(s['reps']): problems.append(f'{key} set {s["set_number"]}: completed_reps != len(reps)')
        for r in s['reps']:
            for f in r['faults']:
                if not f.startswith(prefix) or (key != 'bicep_curl' and f not in cues): problems.append(f'{key}: bad fault label {f!r}')
want = muscle_scores(fx['exercises'])
if want != fx['muscles']: problems.append('muscles do not match shared/scoring.py')
if [m['muscle'] for m in fx['muscles']] != MUSCLES: problems.append('muscles list must cover all 15 keys in order')
for ex, e in RULES['exercises'].items():
    for m in e['primary'] + e['secondary']:
        if m not in MUSCLES: problems.append(f'{ex}: unknown muscle {m}')
print('\n'.join(problems) or f"OK: {len(cols)} tables, {len(fx['exercises'])} exercises, "
      f"{sum(len(s['reps']) for e in fx['exercises'] for s in e['sets'])} reps, {len(fx['muscles'])} muscles")
sys.exit(1 if problems else 0)
