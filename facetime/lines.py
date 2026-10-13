"""FaceTime lines (Chert): which client is on this call. Calls carry no caller identity we rely on, so the client reserves a
line from their /go link first (web/lib/lines.ts, claim_line) and the worker on that line takes the reservation when the call
arrives (db/migrations/20261012_call_lines.sql). Run one worker per line with BRODIE_LINE=<call_lines.id> and AGENT_NAME set to
that line's Chert dispatch name.

    claim = take_claim('line1')        # {'claim_id', 'client_id'} or None (a walk-in: no reservation) -- never raises
    release('line1', claim_id)         # the call ended: close the claim, start the line's cooldown -- never raises
"""
import os


def line_id():
    """This worker's line (BRODIE_LINE), else None: not a line worker."""
    return (os.environ.get('BRODIE_LINE') or '').strip() or None


def _db(db):
    if db is not None: return db
    from facetime.supa import Supa
    return Supa() if Supa.available() else None


def take_claim(line, db=None):
    try:
        db = _db(db)
        if db is None:
            print('[line] no Supabase env: cannot match the caller to a client', flush=True); return None
        rows = db.rpc('take_line_claim', p_line=line) or []
        row = rows[0] if isinstance(rows, list) and rows else None
        if not row or not row.get('client_id'): return None
        return {'claim_id': row['claim_id'], 'client_id': row['client_id']}
    except Exception as e:
        print(f'[line] take_line_claim failed: {type(e).__name__}: {str(e)[:160]}', flush=True); return None


def release(line, claim_id=None, db=None):
    try:
        db = _db(db)
        if db is not None: db.rpc('release_line', p_line=line, p_claim=claim_id)
    except Exception as e:
        print(f'[line] release_line failed: {type(e).__name__}: {str(e)[:160]}', flush=True)
