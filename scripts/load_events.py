"""Replay an .events.jsonl (facetime/replay_local --events, or a worker log) through SessionSink and write the session.

.venv/bin/python scripts/load_events.py data/tmp/run3.fresh.events.jsonl --dry-run          # no Supabase, prints the view path
.venv/bin/python scripts/load_events.py EVENTS.jsonl [--client-id ..] [--program-day-id ..] [--plan "..."] [--items-from-db]
Without --plan the plan comes from the events' session items (item i = exercise:target), completed by RUN3_PLAN when they are
a prefix of it (a call that ended early never announces its last items); --items-from-db takes the day's items from Supabase.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from facetime.session_sink import SessionSink, parse_plan  # noqa: E402

CLIENT = '00000000-0000-4000-8000-00000000c11e'     # db/seed.sql: Ryan
DAY = '00000000-0000-4000-8000-00000000da01'        # db/seed.sql: Day 1 - Full body
RUN3_PLAN = 'squats:10,pushups:8,jumping jacks:20,lunges:10'


class StubDb:
    """--dry-run: answers like PostgREST (ids, tokens), writes nothing."""
    def insert(self, table, rows):
        one = isinstance(rows, dict)
        out = [{'id': str(uuid.uuid4()), 'share_token': 'dry-run', **r} for r in ([rows] if one else rows)]
        return out[0] if one else out
    def select(self, table, **kw): return []
    def update(self, table, patch, **kw): return []


def implied_plan(events):
    items = {}
    for e in events:
        if e.get('type') == 'session' and isinstance(e.get('item'), int) and e.get('exercise') and e.get('target'):
            items.setdefault(e['item'], (e['exercise'], int(e['target'])))
    seen = [items[i] for i in sorted(items)]
    if not seen or seen == parse_plan(RUN3_PLAN)[:len(seen)]:
        return RUN3_PLAN
    return ','.join(f'{n}:{r}' for n, r in seen)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('events')
    ap.add_argument('--client-id', default=CLIENT)
    ap.add_argument('--program-day-id', default=DAY)
    ap.add_argument('--plan')
    ap.add_argument('--items-from-db', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    events = [json.loads(l) for l in Path(a.events).read_text().splitlines() if l.strip()]
    plan = a.plan or implied_plan(events)
    if a.dry_run:
        db = StubDb()
    else:
        from facetime.supa import Supa
        db = Supa()                                    # raises without SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
    items = None
    if a.items_from_db:
        if a.dry_run:
            sys.exit('--items-from-db needs Supabase (drop --dry-run)')
        rows = db.select('program_days', id=f'eq.{a.program_day_id}', select='exercises')
        if not rows:
            sys.exit(f'program_day {a.program_day_id} not found')
        items = rows[0]['exercises']
    sink = SessionSink(a.client_id, a.program_day_id, items, plan, db=db)
    ids = sink.start()
    for e in events:
        sink.on_event(e)
    view = sink.finish()
    if view is None:
        sys.exit('finish() returned no view (see [sink] log)')
    print(f"plan {plan}\nsession {ids['session_id']}  share_token {ids['share_token']}")
    for ex in view['exercises']:
        done = sum(s['completed_reps'] for s in ex['sets'])
        per = ' '.join(f"{s['completed_reps']}/{s['planned_reps']}" for s in ex['sets'])
        print(f"  {ex['exercise_key']:<13} sets {per}  ({done}/{ex['planned_sets'] * ex['planned_reps']} reps)")
    for m in view['muscles']:
        if m['color'] != 'gray':
            print(f"  muscle {m['muscle']:<12} {m['score']:.3f} {m['color']} ({m['coverage']})")
    print(f"  {len(view['muscles'])} muscle rows")
    if a.dry_run:
        print(f'view {sink.view_path}')


if __name__ == '__main__':
    main()
