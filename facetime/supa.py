"""Tiny Supabase REST client (PostgREST) on httpx. Service role key from the environment, never logged.

    from facetime.supa import Supa
    db = Supa()                                  # raises RuntimeError if SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are missing
    db.insert('sessions', {...}) -> dict          # the inserted row (Prefer: return=representation)
    db.insert('reps', [{...}, {...}]) -> list
    db.select('assignments', client_id=f'eq.{cid}', order='assigned_at.desc', limit=1, select='*,program_days(*)') -> list
    db.update('sessions', {'status': 'done'}, id=f'eq.{sid}') -> list
    db.upload('recaps', 'path/file.png', png_bytes, 'image/png') -> storage path
Filters are PostgREST query params (eq., in.(...), etc.). Errors raise SupaError with the server's message.
"""
import os
import httpx

TIMEOUT = 10.0


class SupaError(RuntimeError):
    pass


class Supa:
    def __init__(self, url=None, key=None, timeout=TIMEOUT):
        self.url = (url or os.environ.get('SUPABASE_URL') or '').rstrip('/')
        key = key or os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or ''
        if not self.url or not key:
            raise RuntimeError('SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see .env.local)')
        self._h = {'apikey': key, 'Authorization': f'Bearer {key}'}
        self.c = httpx.Client(timeout=timeout)

    @staticmethod
    def available():
        return bool(os.environ.get('SUPABASE_URL') and os.environ.get('SUPABASE_SERVICE_ROLE_KEY'))

    def _check(self, r):
        if r.status_code >= 300:
            raise SupaError(f'{r.request.method} {r.request.url.path}: {r.status_code} {r.text[:300]}')
        return r.json() if r.content else None

    def select(self, table, **params):
        return self._check(self.c.get(f'{self.url}/rest/v1/{table}', headers=self._h, params=params))

    def insert(self, table, rows):
        one = isinstance(rows, dict)
        out = self._check(self.c.post(f'{self.url}/rest/v1/{table}', headers={**self._h, 'Prefer': 'return=representation'},
                                      json=[rows] if one else rows))
        return out[0] if one and out else out

    def update(self, table, patch, **filters):
        return self._check(self.c.patch(f'{self.url}/rest/v1/{table}', headers={**self._h, 'Prefer': 'return=representation'},
                                        params=filters, json=patch))

    def upload(self, bucket, path, data, content_type='application/octet-stream'):
        self._check(self.c.post(f'{self.url}/storage/v1/object/{bucket}/{path}', headers={**self._h, 'Content-Type': content_type, 'x-upsert': 'true'},
                                content=data))
        return path
