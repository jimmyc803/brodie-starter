"""Supa delete / exists / remove helpers against a mock transport (no network)."""
import json

import httpx
import pytest

from facetime.supa import Supa, SupaError


def make(handler):
    db = Supa(url='https://x.supabase.co', key='k')
    db.c = httpx.Client(transport=httpx.MockTransport(handler))
    return db


def test_delete_sends_filters_and_returns_rows():
    seen = []
    def h(req):
        seen.append(req)
        return httpx.Response(200, json=[{'id': 's1'}])
    db = make(h)
    assert db.delete('sessions', id='eq.s1') == [{'id': 's1'}]
    r = seen[0]
    assert r.method == 'DELETE' and r.url.path == '/rest/v1/sessions' and r.url.params['id'] == 'eq.s1'
    assert r.headers['Prefer'] == 'return=representation'


def test_delete_without_filter_refuses():
    db = make(lambda req: pytest.fail('no request expected'))
    with pytest.raises(ValueError):
        db.delete('sessions')


def test_delete_error_raises():
    db = make(lambda req: httpx.Response(400, text='bad filter'))
    with pytest.raises(SupaError):
        db.delete('sessions', id='eq.x')


def test_exists():
    db = make(lambda req: httpx.Response(200 if req.url.path.endswith('/a.png') else 404))
    assert db.exists('recaps', 'a.png') is True
    assert db.exists('recaps', 'b.png') is False
    db = make(lambda req: httpx.Response(500))
    with pytest.raises(SupaError):
        db.exists('recaps', 'a.png')


def test_remove():
    seen = []
    def h(req):
        seen.append(req)
        return httpx.Response(200, json=[{'name': 'a.png'}])
    db = make(h)
    assert db.remove('recaps', 'a.png') == [{'name': 'a.png'}]
    assert seen[0].method == 'DELETE' and seen[0].url.path == '/storage/v1/object/recaps'
    assert json.loads(seen[0].content) == {'prefixes': ['a.png']}
    with pytest.raises(ValueError):
        db.remove('recaps')
