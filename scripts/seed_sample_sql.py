"""Print SQL that loads db/fixtures/sample_session.json (session view shape) into the contract tables. Idempotent.
python scripts/seed_sample_sql.py > /tmp/x.sql && supabase db query --linked --project-ref <ref> -f /tmp/x.sql
Needs db/seed.sql applied first (the coach, client and day rows)."""
import json, uuid
from pathlib import Path
fx = json.loads((Path(__file__).resolve().parents[1] / 'db/fixtures/sample_session.json').read_text())
NS = uuid.UUID('6f1c2d3e-0000-4000-8000-00000000b347')
def uid(name): return str(uuid.uuid5(NS, name))

def lit(v):
    if v is None: return 'null'
    if isinstance(v, bool): return 'true' if v else 'false'
    if isinstance(v, (int, float)): return repr(v)
    if isinstance(v, list): return 'array[' + ', '.join(lit(x) for x in v) + ']::text[]' if v else "'{}'::text[]"
    return "'" + str(v).replace("'", "''") + "'"

def ins(table, row):
    return f"insert into {table} ({', '.join(row)}) values ({', '.join(lit(v) for v in row.values())}) on conflict do nothing;"

s = fx['session']; sid = s['id']
out = ['begin;', ins('sessions', {'id': sid, 'client_id': fx['client']['id'], 'program_day_id': fx['day']['id'], 'started_at': s['started_at'],
                                  'ended_at': s['ended_at'], 'share_token': s['share_token'], 'recap_image_path': s.get('recap_image_path')})]
for e in fx['exercises']:
    for st in e['sets']:
        set_id = uid(f"{sid}-{e['exercise_key']}-{st['set_number']}")
        out.append(ins('sets', {'id': set_id, 'session_id': sid, 'exercise_key': e['exercise_key'], 'set_number': st['set_number'],
                                'planned_reps': st['planned_reps'], 'completed_reps': st['completed_reps'],
                                'started_at': st.get('started_at'), 'ended_at': st.get('ended_at')}))
        out += [ins('reps', {'id': uid(f'{set_id}-{r["rep_number"]}'), 'set_id': set_id, 'rep_number': r['rep_number'], 't': r['t'], 'faults': r['faults']})
                for r in st['reps']]
out += [ins('muscle_scores', {'session_id': sid, **m}) for m in fx['muscles']] + ['commit;']
print('\n'.join(out))
