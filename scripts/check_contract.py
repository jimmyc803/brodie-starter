"""Check the data contract: every row in db/fixtures/sample_session.json has exactly the columns of its table in db/schema.sql,
every exercise and fault label is one Brodie knows, and the stored scores match shared/scoring.py.
python scripts/check_contract.py   -> prints OK or the problems, exit 1 on problems."""
import json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from shared.scoring import RULES, set_scores, muscle_scores

sql = (ROOT / 'db/schema.sql').read_text()
cols = {}
for name, body in re.findall(r'create table if not exists (\w+) \((.*?)\n\);', sql, re.S):
    cols[name] = {m.group(1) for m in re.finditer(r'^\s+(\w+)\s+(?:uuid|text|int|real|jsonb|timestamptz)\b', body, re.M)}
fx = json.loads((ROOT / 'db/fixtures/sample_session.json').read_text())
cues = json.loads((ROOT / 'src/rtcoach/cues.json').read_text())
FAULT_PREFIX = {'lunges': 'alternating forward lunges'}   # Brodie's lunge fault labels use the classifier name
problems = []
def check(table, row, extra=()):
    keys = set(row) - set(extra)
    if keys != cols[table]: problems.append(f'{table}: missing {sorted(cols[table] - keys)} extra {sorted(keys - cols[table])}')
check('sessions', fx['session']); check('clients', fx['client']); check('coaches', fx['coach'])
check('program_days', fx['program_day'])
for s in fx['sets']:
    check('sets', s, extra=('reps',))
    if s['exercise'] not in RULES['exercises']: problems.append(f"unknown exercise {s['exercise']}")
    if s['done_reps'] != len(s['reps']): problems.append(f"set {s['set_number']}: done_reps != len(reps)")
    for r in s['reps']:
        check('reps', r)
        for f in r['faults']:
            if f not in cues or not f.startswith(FAULT_PREFIX.get(s['exercise'], s['exercise']) + ' - '):
                problems.append(f'set {s["set_number"]}: bad fault label {f!r}')
    want = set_scores(s['planned_reps'], [r['faults'] for r in s['reps']])
    if any(s[k] != v for k, v in want.items()): problems.append(f"set {s['set_number']}: scores {want} != stored")
want = muscle_scores([{'set_number': s['set_number'], 'exercise': s['exercise'], 'quality': s['quality'],
                       'faults': [f for r in s['reps'] for f in r['faults']]} for s in fx['sets']])
got = [{k: m[k] for k in ('muscle', 'score', 'color', 'detail')} for m in fx['muscle_scores']]
if want != got: problems.append('muscle_scores do not match shared/scoring.py')
for m in fx['muscle_scores']:
    check('muscle_scores', m)
    if m['muscle'] not in RULES['muscles']: problems.append(f"unknown muscle {m['muscle']}")
for ex, e in RULES['exercises'].items():
    for m in e['primary'] + e['secondary']:
        if m not in RULES['muscles']: problems.append(f'{ex}: unknown muscle {m}')
print('\n'.join(problems) or f"OK: {len(cols)} tables, {len(fx['sets'])} sets, {sum(len(s['reps']) for s in fx['sets'])} reps, {len(fx['muscle_scores'])} muscles")
sys.exit(1 if problems else 0)
