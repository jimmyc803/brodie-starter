"""Print SQL that loads db/fixtures/sample_session.json into Supabase (idempotent: on conflict do nothing).
python scripts/seed_sample_sql.py > /tmp/seed.sql && supabase db query --linked --project-ref <ref> -f /tmp/seed.sql"""
import json
from pathlib import Path
fx = json.loads((Path(__file__).resolve().parents[1] / 'db/fixtures/sample_session.json').read_text())

def lit(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, (list, dict)): return "'" + json.dumps(v).replace("'", "''") + "'::jsonb"
    return "'" + str(v).replace("'", "''") + "'"

def ins(table, row):
    cols = ', '.join(row); vals = ', '.join(lit(v) for v in row.values())
    return f'insert into {table} ({cols}) values ({vals}) on conflict do nothing;'

day = fx['program_day']
out = ['begin;', ins('coaches', fx['coach']), ins('clients', fx['client']),
       ins('programs', {'id': day['program_id'], 'coach_id': fx['coach']['id'], 'title': 'Demo starter program',
                        'pdf_path': None, 'parsed': None}),
       ins('program_days', day),
       ins('assignments', {'id': day['id'][:-4] + 'a551', 'client_id': fx['client']['id'], 'program_day_id': day['id']}),
       ins('sessions', fx['session'])]
for s in fx['sets']:
    out.append(ins('sets', {k: v for k, v in s.items() if k != 'reps'}))
    out += [ins('reps', r) for r in s['reps']]
out += [ins('muscle_scores', m) for m in fx['muscle_scores']] + ['commit;']
print('\n'.join(out))
