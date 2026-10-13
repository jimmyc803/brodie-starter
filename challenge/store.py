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


PG_CONNECT_TIMEOUT_S = 5
PG_STATEMENT_TIMEOUT_MS = 10_000


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError as e:
        raise StoreError(f"{name} must be an integer, got {raw!r}") from e


class PgStore:
    """psycopg 3; dict/list args are sent as jsonb; `select fn(p_a => %(p_a)s, ...)`; one transaction per call.

    Bounded: connect_timeout (PG_CONNECT_TIMEOUT_S, default 5 s) and a per-call statement_timeout
    (PG_STATEMENT_TIMEOUT_MS, default 10 s; 0 = none), set with set_config(..., is_local => true) so it never leaks
    into a pooled server session. A timeout surfaces as StoreError like any other DB error."""

    def __init__(self, dsn: str, connect_timeout_s: int | None = None, statement_timeout_ms: int | None = None):
        self.dsn = dsn
        self.connect_timeout_s = (connect_timeout_s if connect_timeout_s is not None
                                  else _env_int("PG_CONNECT_TIMEOUT_S", PG_CONNECT_TIMEOUT_S))
        self.statement_timeout_ms = (statement_timeout_ms if statement_timeout_ms is not None
                                     else _env_int("PG_STATEMENT_TIMEOUT_MS", PG_STATEMENT_TIMEOUT_MS))
        if self.connect_timeout_s < 1 or self.statement_timeout_ms < 0:
            raise StoreError("PgStore: connect_timeout_s must be >= 1 and statement_timeout_ms >= 0")

    def rpc(self, fn: str, args: dict | None = None) -> Any:
        import psycopg
        from psycopg.types.json import Jsonb

        args = args or {}
        if not _IDENT.match(fn) or not all(_IDENT.match(k) for k in args):
            raise StoreError(f"bad rpc identifier: {fn}")
        params = {k: Jsonb(_jsonable(v)) if isinstance(v, (dict, list, tuple, Json)) else v for k, v in args.items()}
        sql = f"select {fn}({', '.join(f'{k} => %({k})s' for k in args)}) as r"
        try:
            with psycopg.connect(self.dsn, autocommit=True, connect_timeout=self.connect_timeout_s) as conn:
                with conn.transaction():
                    conn.execute("select set_config('statement_timeout', %s, true)", (str(self.statement_timeout_ms),))
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
