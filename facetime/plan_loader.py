"""Load a client's assigned program day + coach persona from Supabase (see docs/STARTER_EVENTS.md section 2)."""
import os


def _known():
    from facetime.pipeline import accepted_names
    return set(accepted_names())


def load_assignment(client_id, db=None):
    """Newest assignment for the client -> {'plan','program_day_id','day_title','client_name','coach_name','persona'}, else None. Never raises."""
    if not client_id:
        return None
    try:
        if db is None:
            from facetime.supa import Supa
            if not Supa.available():
                print('[plan] no Supabase env (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY): cannot load assignment', flush=True)
                return None
            db = Supa()
        rows = db.select('assignments', client_id=f'eq.{client_id}', active='eq.true', order='assigned_at.desc', limit=1,
                         select='program_day_id,clients(name),program_days(id,day_number,title,exercises,programs(coach_id,coaches(name,persona)))')
        if not rows:
            print(f'[plan] no assignment found for client {client_id}', flush=True)
            return None
        row = rows[0]; day = row.get('program_days') or {}
        coach = ((day.get('programs') or {}).get('coaches')) or {}
        known = _known(); items = []
        from shared.scoring import plan_name
        exercises = day.get('exercises') or []
        for ex in exercises:
            key = ex.get('exercise_key')
            try: name = plan_name(key) if key and ex.get('supported', True) else None
            except KeyError: name = None
            if name not in known:
                print(f"[plan] warning: skipping {ex.get('name') or key!r} (not supported by Brodie yet)", flush=True); continue
            items += [f'{name}:{int(ex.get("reps", 10))}'] * max(1, int(ex.get('sets', 1) or 1))
        if not items:
            print('[plan] assignment has no supported exercises', flush=True)
            return None
        client = row.get('clients') or {}
        if not client.get('name'):
            try:
                c = db.select('clients', id=f'eq.{client_id}', select='name', limit=1); client = c[0] if c else {}
            except Exception:
                client = {}
        return {'plan': ','.join(items), 'program_day_id': row.get('program_day_id') or day.get('id'), 'day_title': day.get('title'), 'day_number': day.get('day_number'), 'items': exercises,
                'client_name': client.get('name'), 'coach_name': coach.get('name'), 'persona': coach.get('persona')}
    except Exception as e:
        print(f'[plan] could not load assignment: {type(e).__name__}: {str(e)[:200]}', flush=True)
        return None


def persona_text(base_text, loaded):
    """Base persona plus the client's name and the coach's persona when loaded has them."""
    if not loaded or not (loaded.get('persona') or loaded.get('client_name')):
        return base_text
    who = f"The client's name is {loaded.get('client_name')}." if loaded.get('client_name') else ''
    coach = f"Their coach {loaded['coach_name']}" if loaded.get('coach_name') else 'Their coach'
    extra = f"{who} {coach} says: {loaded['persona']}." if loaded.get('persona') else who
    return f'{base_text}\n\n{extra.strip()}'
