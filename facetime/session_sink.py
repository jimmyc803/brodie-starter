"""Session sink: collect Brodie's events during a call, write the session to Supabase when it ends (db/schema.sql contract).

    sink = SessionSink(client_id, program_day_id, items, plan)   # items: the day's exercises (program_days.exercises)
    ids = sink.start()          # {'session_id', 'share_token'}: inserts the sessions row (network, call before the loop)
    sink.on_event(ev)           # every event, on the worker loop: in memory only
    view = sink.finish()        # off the loop: sets, reps, muscle_scores rows, sessions.ended_at; the session view dict

Plan item i (the session event's `item`) is one set: the plan 'squats:10,squats:10,pushups:8' runs squat sets 1, 2 then
pushup set 1. Each plan item takes the next unused set of its exercise in the day's items, so items Brodie cannot run (bicep
curls) keep their sets with completed_reps 0. The view (db/fixtures/sample_session.json shape) is always dumped to
data/tmp/sessions/<session_id>.json; network errors are logged and never raised.
"""
import json
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.scoring import exercise_key_for, muscle_scores

OUT_DIR = Path(__file__).resolve().parents[1] / 'data/tmp/sessions'


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _log(msg):
    print(f'[sink] {msg}', flush=True)


def parse_plan(plan):
    """'squats:10,pushups:8' -> [('squats', 10), ('pushups', 8)]."""
    out = []
    for part in (plan or '').split(','):
        name, _, n = part.strip().rpartition(':')
        if name:
            out.append((name.strip(), int(n)))
    return out


class SessionSink:
    def __init__(self, client_id, program_day_id, items, plan, db=None):
        self.client_id, self.program_day_id, self.plan = client_id, program_day_id, plan
        if db is None:
            from facetime.supa import Supa
            db = Supa() if Supa.available() else None
        self.db = db                              # None = local-only (the view file, no writes)
        self._lock = threading.Lock()             # on_event on the loop, finish() on a thread
        self._exercises = []                      # view exercises, every planned set present
        by_key = {}
        for it in items or [{'exercise_key': exercise_key_for(n), 'name': n, 'sets': 1, 'reps': r} for n, r in parse_plan(plan)]:
            key = it.get('exercise_key')
            if not key or it.get('supported') is False:
                continue                          # sets.exercise_key is not null: an unknown exercise cannot be stored
            ex = by_key.get(key)
            if ex is None:                        # the same exercise twice in a day (or a derived plan): one exercise, more sets
                ex = by_key[key] = {'exercise_key': key, 'name': it.get('name') or key, 'planned_sets': 0,
                                    'planned_reps': int(it.get('reps') or 0), 'sets': []}
                self._exercises.append(ex)
            for _ in range(int(it.get('sets') or 0)):
                ex['planned_sets'] += 1
                ex['sets'].append(self._new_set(len(ex['sets']) + 1, int(it.get('reps') or 0)))
        # plan item index -> the set it runs: the next unused set of that exercise (a plan item with no day set adds one)
        self._plan_sets, used = [], {}
        for name, reps in parse_plan(plan):
            key = exercise_key_for(name)
            if key is None:
                self._plan_sets.append(None); continue
            ex = by_key.get(key)
            if ex is None:
                ex = by_key[key] = {'exercise_key': key, 'name': name, 'planned_sets': 0, 'planned_reps': reps, 'sets': []}
                self._exercises.append(ex)
            i = used.get(key, 0); used[key] = i + 1
            if i >= len(ex['sets']):
                ex['planned_sets'] += 1
                ex['sets'].append(self._new_set(i + 1, reps))
            self._plan_sets.append(ex['sets'][i])
        self._cur = None                          # the open set
        self._pending = []                        # faults waiting for the next counted rep
        self._t0 = None                           # the first event's t
        self.session_id, self.share_token = str(uuid.uuid4()), secrets.token_urlsafe(24)   # local ids: no network needed to know them
        self.started_at = None
        self._start_lock = threading.Lock()       # the sessions insert: start() and _write() never both insert (no duplicate row)
        self._row_ok = False                      # the sessions row exists in the db
        self._view = None
        self.view_path = None                     # data/tmp/sessions/<id>.json once finished

    @staticmethod
    def _new_set(n, reps):
        return {'set_number': n, 'planned_reps': reps, 'completed_reps': 0, 'started_at': None, 'ended_at': None, 'reps': []}

    def start(self):
        """Insert the sessions row (network; call off the loop). Never holds _lock, so events keep flowing meanwhile."""
        self.started_at = self.started_at or _now()
        if self.db is not None:
            with self._start_lock:
                self._insert_session()
        return {'session_id': self.session_id, 'share_token': self.share_token}

    def _insert_session(self):
        """Under _start_lock. Once only; a failure leaves _row_ok False and _write() tries again."""
        if self._row_ok: return
        try:
            self.db.insert('sessions', {'id': self.session_id, 'client_id': self.client_id, 'program_day_id': self.program_day_id,
                                        'started_at': self.started_at, 'share_token': self.share_token})
            self._row_ok = True
        except Exception as e:
            _log(f'could not insert the session row (retried at finish): {type(e).__name__}: {str(e)[:200]}')

    # ---- the loop side: memory only ----
    def on_event(self, ev):
        with self._lock:
            if self._view is not None:
                return
            if self._t0 is None and ev.get('t') is not None:
                self._t0 = ev['t']
            t = ev.get('type')
            if t == 'session':
                st, item = ev.get('state'), ev.get('item')
                if st in ('wait', 'active'):
                    s = self._plan_sets[item] if isinstance(item, int) and 0 <= item < len(self._plan_sets) else None
                    if s is not self._cur:        # a new item (skipped to without a rest: close the old one)
                        self._close(None)
                        self._cur = s
                        if s is not None and s['started_at'] is None:
                            s['started_at'] = _now()
                elif st in ('rest', 'done'):
                    self._close(ev.get('count'))
            elif t == 'rep' and self._cur is not None:
                reps = self._cur['reps']
                n = ev.get('n')
                if isinstance(n, int) and (not reps or n > reps[-1]['rep_number']):   # (set_id, rep_number) is unique
                    rel = round(float(ev.get('t') or 0.0) - (self._t0 or 0.0), 2)
                    reps.append({'rep_number': n, 't': rel, 'faults': self._pending})
                    self._pending = []
            elif t == 'fault' and self._cur is not None and ev.get('label'):
                if ev['label'] not in self._pending:
                    self._pending.append(ev['label'])

    def _close(self, count):
        """Close the open set: leftover faults go to its last rep; completed_reps = the session's count (else reps seen)."""
        s, self._cur = self._cur, None
        if s is None:
            self._pending = []
            return
        if self._pending and s['reps']:
            last = s['reps'][-1]['faults']
            last += [f for f in self._pending if f not in last]
        self._pending = []
        s['completed_reps'] = int(count) if isinstance(count, int) else len(s['reps'])
        s['ended_at'] = _now()

    # ---- the end: network allowed, never raises ----
    def finish(self, reason='done'):
        try:
            with self._lock:
                if self._view is not None:
                    return self._view
                self.started_at = self.started_at or _now()     # no network under _lock: the row is inserted in _write
                self._close(None)                 # the call ended mid-set
                exercises = json.loads(json.dumps(self._exercises))
                view = {'session': {'id': self.session_id, 'started_at': self.started_at, 'ended_at': _now(),
                                    'share_token': self.share_token},
                        'client': {'id': self.client_id}, 'coach': {}, 'day': {'id': self.program_day_id},
                        'exercises': exercises, 'muscles': muscle_scores(exercises)}
                self._view = view                 # from here on finish() returns it and on_event ignores events
        except Exception as e:
            _log(f'finish failed building the view: {type(e).__name__}: {str(e)[:200]}')
            return None
        if self.db is not None:
            try:                                  # the rows first: on a hang-up the time is short
                self._write(view)
                _log(f'session {self.session_id} written ({reason})')
            except Exception as e:
                _log(f'could not write session {self.session_id} (kept the file): {type(e).__name__}: {str(e)[:200]}')
            self._lookup(view)                    # names for the card and the file, after the rows are safe
        try:
            OUT_DIR.mkdir(parents=True, exist_ok=True)
            self.view_path = OUT_DIR / f'{self.session_id}.json'
            self.view_path.write_text(json.dumps(view, indent=2))
        except Exception as e:
            _log(f'could not dump the view: {type(e).__name__}: {e}')
        return view

    def _lookup(self, view):
        """Best effort: client and coach names, the day's title, for the view (the recap page reads the same from the db)."""
        try:
            if self.client_id:
                rows = self.db.select('clients', id=f'eq.{self.client_id}', select='id,name,coaches(id,name,share_token)') or []
                if rows:
                    view['coach'] = rows[0].pop('coaches', None) or {}
                    view['client'] = rows[0]
            if self.program_day_id:
                rows = self.db.select('program_days', id=f'eq.{self.program_day_id}', select='id,title,day_number') or []
                if rows:
                    view['day'] = rows[0]
        except Exception as e:
            _log(f'name lookup failed (view keeps ids only): {type(e).__name__}: {str(e)[:200]}')

    def _write(self, view):
        sid, s = self.session_id, view['session']
        with self._start_lock:                    # waits for a start() still in flight instead of inserting a second row
            self._insert_session()
        if not self._row_ok:
            raise RuntimeError('no sessions row')
        rows = [{'session_id': sid, 'exercise_key': ex['exercise_key'], **{k: st[k] for k in
                 ('set_number', 'planned_reps', 'completed_reps', 'started_at', 'ended_at')}}
                for ex in view['exercises'] for st in ex['sets']]
        ids = {(r['exercise_key'], r['set_number']): r['id'] for r in (self.db.insert('sets', rows) if rows else [])}
        reps = [{'set_id': ids[(ex['exercise_key'], st['set_number'])], **r}
                for ex in view['exercises'] for st in ex['sets'] for r in st['reps']]
        if reps:
            self.db.insert('reps', reps)
        self.db.insert('muscle_scores', [{'session_id': sid, **m} for m in view['muscles']])
        self.db.update('sessions', {'ended_at': s['ended_at']}, id=f'eq.{sid}')
