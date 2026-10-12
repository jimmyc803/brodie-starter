"""DB access via RPC only (CONTRACTS C3)."""
from __future__ import annotations

import os
import re
from datetime import date, datetime
from typing import Any, Protocol

import httpx


class StoreError(RuntimeError):
    pass


class Store(Protocol):
    def rpc(self, fn: str, args: dict) -> Any: ...


_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class Json:
    """Explicit jsonb marker. Callers pass Json(x) for jsonb params whose value is a scalar
    (e.g. ch_config_set.p_value = Json(5)); dicts/lists are always sent as jsonb."""

    def __init__(self, value: Any):
        self.value = value

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Json) and other.value == self.value

    def __repr__(self) -> str:
        return f"Json({self.value!r})"


def _jsonable(v: Any) -> Any:
    if isinstance(v, Json):
        return _jsonable(v.value)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


class PgStore:
    """psycopg 3; dict/list args are sent as jsonb; `select fn(p_a => %(p_a)s, ...)`; autocommit per call."""

    def __init__(self, dsn: str):
        self.dsn = dsn

    def rpc(self, fn: str, args: dict | None = None) -> Any:
        import psycopg
        from psycopg.types.json import Jsonb

        args = args or {}
        if not _IDENT.match(fn) or not all(_IDENT.match(k) for k in args):
            raise StoreError(f"bad rpc identifier: {fn}")
        params = {k: Jsonb(_jsonable(v)) if isinstance(v, (dict, list, tuple, Json)) else v for k, v in args.items()}
        sql = f"select {fn}({', '.join(f'{k} => %({k})s' for k in args)}) as r"
        try:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                row = conn.execute(sql, params).fetchone()
        except psycopg.Error as e:
            raise StoreError(f"{fn}: {e}") from e
        return row[0] if row else None


class SupaStore:
    """PostgREST POST {url}/rest/v1/rpc/{fn} with service role headers."""

    def __init__(self, url: str, key: str, timeout: float = 10.0, transport: httpx.BaseTransport | None = None):
        self.url = url.rstrip("/")
        self._h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        self.c = httpx.Client(timeout=timeout, transport=transport)

    def rpc(self, fn: str, args: dict | None = None) -> Any:
        if not _IDENT.match(fn):
            raise StoreError(f"bad rpc identifier: {fn}")
        try:
            r = self.c.post(f"{self.url}/rest/v1/rpc/{fn}", headers=self._h, json=_jsonable(args or {}))
        except httpx.HTTPError as e:
            raise StoreError(f"{fn}: {e}") from e
        if r.status_code >= 300:
            raise StoreError(f"{fn}: {r.status_code} {r.text[:300]}")
        return r.json() if r.content else None


def store_from_env() -> Store:
    dsn = os.environ.get("CHALLENGE_DB_DSN")
    if dsn:
        return PgStore(dsn)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise StoreError("set CHALLENGE_DB_DSN or SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY")
    return SupaStore(url, key)
