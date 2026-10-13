"""HANGUP_MODE=chert_api end-call client (task 35, C7.h) against a local mock HTTP server (never the live Chert API)."""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from challenge.worker.chert import ChertEndClient, missing_env

TOKEN = "ftk_SECRET_TOKEN_VALUE_123"
PROJECT = "11111111-2222-3333-4444-555555555555"


class Mock:
    def __init__(self, statuses, delay=0.0):
        self.statuses, self.delay, self.requests = list(statuses), delay, []
        mock = self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                mock.requests.append((self.path, dict(self.headers), self.rfile.read(n)))
                if mock.delay:
                    time.sleep(mock.delay)
                st = mock.statuses.pop(0) if len(mock.statuses) > 1 else mock.statuses[0]
                self.send_response(st)
                self.send_header("Content-Length", "2")
                self.end_headers()
                try:
                    self.wfile.write(b"{}")
                except OSError:
                    pass

            def log_message(self, *a):
                pass

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/api"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture
def mock(request):
    made = []

    def make(statuses, delay=0.0):
        m = Mock(statuses, delay)
        made.append(m)
        return m
    yield make
    for m in made:
        m.close()


def end(m, **kw):
    slept = []

    async def sleep(dt):
        slept.append(dt)
    c = ChertEndClient(TOKEN, PROJECT, base_url=m.url, **kw)
    return asyncio.run(c.end_call("call-9", sleep)), slept


def test_success_sends_documented_request(mock):
    m = mock([202])
    ok, slept = end(m)
    assert ok is True and slept == [] and len(m.requests) == 1
    path, h, body = m.requests[0]
    assert path == "/api/v1/calls/call-9/end" and json.loads(body) == {}
    assert h["Authorization"] == f"Bearer {TOKEN}" and h["X-Chert-Project-Id"] == PROJECT
    assert 8 <= len(h["Idempotency-Key"]) <= 200


def test_4xx_is_final_no_retry(mock):
    m = mock([404])
    ok, slept = end(m)
    assert ok is False and len(m.requests) == 1 and slept == []


def test_5xx_retries_then_gives_up(mock):
    m = mock([503])
    ok, slept = end(m)
    assert ok is False and len(m.requests) == 3 and slept == [0.5, 1.5]


def test_5xx_then_success(mock):
    m = mock([502, 202])
    ok, _ = end(m)
    assert ok is True and len(m.requests) == 2


def test_timeout_retries_then_gives_up(mock):
    m = mock([202], delay=0.6)
    ok, slept = end(m, timeout=0.15)
    assert ok is False and len(slept) == 2


def test_token_never_logged(mock, caplog):
    caplog.set_level(logging.DEBUG)
    for st in ([202], [404], [500]):
        m = mock(st)
        end(m)
    assert caplog.records
    text = caplog.text + " ".join(str(r.__dict__) for r in caplog.records)
    assert TOKEN not in text and "SECRET_TOKEN" not in text and PROJECT not in text


def test_missing_env_and_from_env(monkeypatch):
    monkeypatch.delenv("CHERT_FACETIME_TOKEN", raising=False)
    monkeypatch.setenv("CHERT_PROJECT_ID", PROJECT)
    assert missing_env() == ["CHERT_FACETIME_TOKEN"]
    with pytest.raises(ValueError, match="CHERT_FACETIME_TOKEN"):
        ChertEndClient.from_env()
    monkeypatch.setenv("CHERT_FACETIME_TOKEN", TOKEN)
    assert missing_env() == [] and ChertEndClient.from_env().attempts == 3
