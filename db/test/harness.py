"""Throwaway local Postgres 17 cluster with Supabase shims, for DB tests.

Usage (see tests/challenge/conftest.py):
    cluster = PgCluster.start()          # initdb + pg_ctl in a temp dir, unix socket + free TCP port on 127.0.0.1
    cluster.build_template()             # db `ch_template`: shim, db/schema.sql, every db/migrations/*.sql in name order
    dsn = cluster.clone("t_mod")         # fresh database copied from the template (fast file copy)
    cluster.stop()

Each pytest-xdist worker starts its own cluster (own temp dir, own port), so workers never share state.
SQL files are applied with psql (ON_ERROR_STOP) exactly like the Supabase SQL editor would run them.
"""
from __future__ import annotations

import atexit
import os
import re
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import psycopg

PG_BIN = Path(os.environ.get("PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
ROOT = Path(__file__).resolve().parents[2]
SHIM = ROOT / "db" / "test" / "supabase_shim.sql"
SCHEMA = ROOT / "db" / "schema.sql"
MIGRATIONS = ROOT / "db" / "migrations"
TEMPLATE_DB = "ch_template"
SUPERUSER = "postgres"
_SAFE_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"), key=lambda p: p.name)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def connect(dsn: str, autocommit: bool = True) -> psycopg.Connection:
    return psycopg.connect(dsn, autocommit=autocommit)


class PgCluster:
    def __init__(self, root: Path, port: int):
        self.root = root
        self.data = root / "data"
        self.sock = root / "s"
        self.port = port
        self._stopped = False

    # ------------------------------------------------------------------ lifecycle
    @classmethod
    def start(cls, attempts: int = 5) -> "PgCluster":
        if not (PG_BIN / "initdb").exists():
            raise RuntimeError(f"Postgres binaries not found in {PG_BIN} (set PG_BIN)")
        # Short base dir: unix socket paths are limited to ~103 bytes on macOS.
        root = Path(tempfile.mkdtemp(prefix="chpg", dir="/tmp" if Path("/tmp").is_dir() else None))
        (root / "s").mkdir()
        try:
            subprocess.run(
                [str(PG_BIN / "initdb"), "-D", str(root / "data"), "-U", SUPERUSER, "-A", "trust",
                 "-E", "UTF8", "--no-locale", "--no-sync"],
                check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            shutil.rmtree(root, ignore_errors=True)
            raise RuntimeError(f"initdb failed: {e.stderr}") from e
        last_err = ""
        for _ in range(attempts):
            cluster = cls(root, _free_port())
            opts = (f"-c port={cluster.port} -c listen_addresses=127.0.0.1 "
                    f"-c unix_socket_directories={cluster.sock} -c fsync=off -c synchronous_commit=off "
                    f"-c full_page_writes=off -c timezone=UTC -c max_connections=50")
            proc = subprocess.run(
                [str(PG_BIN / "pg_ctl"), "-D", str(cluster.data), "-l", str(root / "log"), "-w", "-t", "30",
                 "-o", opts, "start"],
                capture_output=True, text=True)
            if proc.returncode == 0:
                atexit.register(cluster.stop)
                return cluster
            last_err = proc.stderr + _tail(root / "log")
            time.sleep(0.2)  # port taken between probe and bind: retry on a new port
        shutil.rmtree(root, ignore_errors=True)
        raise RuntimeError(f"pg_ctl start failed: {last_err}")

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        subprocess.run([str(PG_BIN / "pg_ctl"), "-D", str(self.data), "-m", "immediate", "-w", "stop"],
                       capture_output=True, text=True)
        shutil.rmtree(self.root, ignore_errors=True)

    # ------------------------------------------------------------------ databases
    def dsn(self, dbname: str = "postgres", user: str = SUPERUSER) -> str:
        return f"host={self.sock} port={self.port} dbname={dbname} user={user}"

    def tcp_dsn(self, dbname: str = "postgres", user: str = SUPERUSER) -> str:
        return f"postgresql://{user}@127.0.0.1:{self.port}/{dbname}"

    def apply_file(self, dbname: str, path: Path) -> None:
        proc = subprocess.run(
            [str(PG_BIN / "psql"), "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", str(self.sock), "-p", str(self.port),
             "-U", SUPERUSER, "-d", dbname, "-f", str(path)],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"applying {path.name} to {dbname} failed:\n{proc.stderr}")

    def build_template(self) -> str:
        with connect(self.dsn()) as conn:
            conn.execute(f'drop database if exists "{TEMPLATE_DB}"')
            conn.execute(f'create database "{TEMPLATE_DB}"')
        for path in [SHIM, SCHEMA, *migration_files()]:
            self.apply_file(TEMPLATE_DB, path)
        return self.dsn(TEMPLATE_DB)

    def clone(self, name: str) -> str:
        """Fresh database copied from the template. Template must have no open connections."""
        if not _SAFE_NAME.match(name):
            raise ValueError(f"bad database name {name!r}")
        with connect(self.dsn()) as conn:
            conn.execute(f'drop database if exists "{name}" with (force)')
            conn.execute(f'create database "{name}" template "{TEMPLATE_DB}" strategy file_copy')
        return self.dsn(name)

    def drop(self, name: str) -> None:
        if not _SAFE_NAME.match(name):
            raise ValueError(f"bad database name {name!r}")
        with connect(self.dsn()) as conn:
            conn.execute(f'drop database if exists "{name}" with (force)')


def _tail(path: Path, n: int = 2000) -> str:
    try:
        return path.read_text()[-n:]
    except OSError:
        return ""
