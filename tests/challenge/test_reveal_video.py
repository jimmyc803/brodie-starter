"""REVEAL_MODE=video (task 33, C7.v): fake room / rtc / VideoSource; frames for the reveal, fallback, errors, no files."""
from __future__ import annotations

import asyncio
import builtins
import io
import logging
import os
import tempfile
from types import SimpleNamespace

import pytest
from PIL import Image

from challenge.worker import reveal_video as rv
from challenge.worker.controller import CompetitionCall


class FakeSource:
    def __init__(self, w, h):
        self.size, self.frames = (w, h), []

    def capture_frame(self, f):
        self.frames.append(f)


class FakeFrame:
    def __init__(self, w, h, kind, data):
        self.size, self.kind, self.data = (w, h), kind, data

    def convert(self, kind):
        return FakeFrame(*self.size, kind, self.data)


class FakeRtc:
    VideoFrame = FakeFrame
    VideoBufferType = SimpleNamespace(RGBA="RGBA", I420="I420")
    TrackSource = SimpleNamespace(SOURCE_CAMERA=1)
    TrackPublishOptions = staticmethod(lambda **k: SimpleNamespace(**k))
    VideoEncoding = staticmethod(lambda **k: SimpleNamespace(**k))

    def __init__(self):
        self.sources = []
        outer = self

        class VS(FakeSource):
            def __init__(self, w, h):
                super().__init__(w, h)
                outer.sources.append(self)
        self.VideoSource = VS
        self.LocalVideoTrack = SimpleNamespace(create_video_track=lambda name, src: SimpleNamespace(name=name, sid="TR1"))


class FakeRoom:
    def __init__(self, fail_publish=False):
        self.events, self.fail = [], fail_publish
        lp = SimpleNamespace()

        async def publish_track(track, opts):
            if self.fail:
                raise RuntimeError("publish refused")
            self.events.append(("publish", track.name, opts))
            return SimpleNamespace(sid="PUB1")

        async def unpublish_track(sid):
            self.events.append(("unpublish", sid))
        lp.publish_track, lp.unpublish_track = publish_track, unpublish_track
        self.local_participant = lp


class Clk:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    async def sleep(self, dt):
        self.t += dt
        await asyncio.sleep(0)


def png(w=1080, h=1350, color=(200, 30, 30)):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "PNG")
    return b.getvalue()


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def no_disk(monkeypatch):
    tmp = tempfile.gettempdir()
    before = set(os.listdir(tmp))
    real_open = builtins.open
    writes = []

    def guard(file, mode="r", *a, **k):
        if any(c in mode for c in "wax+"):
            writes.append(file)
        return real_open(file, mode, *a, **k)
    monkeypatch.setattr(builtins, "open", guard)
    yield
    assert writes == []
    assert set(os.listdir(tmp)) == before


def test_card_url_uses_call_id_only(monkeypatch):
    monkeypatch.delenv("WEB_URL", raising=False)
    monkeypatch.setenv("WEB_BASE_URL", "https://site.example/")
    assert rv.card_url("call-1") == "https://site.example/r/call-1/card"
    assert rv.card_url("a/b?c") == "https://site.example/r/a%2Fb%3Fc/card"
    monkeypatch.setenv("WEB_BASE_URL", "")
    assert rv.card_url("c") is None


def test_publishes_card_frames_for_the_whole_reveal(no_disk):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()

    async def fetch(call_id):
        assert call_id == "c1"
        return rv._decode_card(png())
    ok = run(rv.publish_reveal(room, "c1", 5, 2, 15, rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert ok
    src = fr.sources[0]
    assert src.size == (720, 900) and len(src.frames) >= 2 * 13
    assert src.frames[0].size == (720, 900) and src.frames[0].kind == "I420"
    assert clk.t - 100.0 <= 15
    assert [e[0] for e in room.events] == ["publish", "unpublish"] and room.events[1][1] == "PUB1"
    assert room.events[0][2].simulcast is False


def test_fallback_when_card_unavailable(no_disk):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()

    async def fetch(call_id):
        return None
    assert run(rv.publish_reveal(room, "c1", 7, None, 15, rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert fr.sources[0].frames and room.events[-1][0] == "unpublish"


def test_fallback_frame_has_text_and_no_handle():
    img = rv.render_fallback(7, 3)
    assert img.size == (720, 900)
    assert img.getbbox() and len(img.getcolors(maxcolors=1 << 20)) > 1
    assert rv.render_fallback(None, None).size == (720, 900)


def test_fetch_card_bounded_and_failures_are_none(monkeypatch):
    import httpx
    monkeypatch.setenv("WEB_BASE_URL", "https://site.example")
    real = httpx.AsyncClient

    class Slow:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url):
            await asyncio.sleep(30)
    monkeypatch.setattr(httpx, "AsyncClient", Slow)

    async def go():
        loop = asyncio.get_running_loop()
        t = loop.time()
        r = await rv.fetch_card("c1", timeout=0.2)
        return r, loop.time() - t
    r, dt = run(go())
    assert r is None and dt < 1.0

    def handler(status, ctype, body):
        def h(req):
            assert req.url.path == "/r/c1/card"
            return httpx.Response(status, headers={"content-type": ctype}, content=body)
        return h
    for status, ctype, body, want in [(200, "image/png", png(), True), (404, "text/plain", b"x", False),
                                      (200, "text/html", b"<html>", False), (200, "image/png", b"notpng", False)]:
        monkeypatch.setattr(httpx, "AsyncClient", lambda *a, _h=handler(status, ctype, body), **k: real(
            transport=httpx.MockTransport(_h), *a, **k))
        got = run(rv.fetch_card("c1"))
        assert (got is not None) is want
        if want:
            assert got.size == (720, 900)


def test_publish_error_is_warn_and_false(caplog, no_disk):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom(fail_publish=True)

    async def fetch(call_id):
        return None
    with caplog.at_level(logging.WARNING, logger="challenge.reveal_video"):
        ok = run(rv.publish_reveal(room, "c1", 1, None, 15, rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert ok is False and room.events == []
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_capture_error_still_unpublishes(caplog):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()
    orig = fr.VideoSource

    class Bad(orig):
        def capture_frame(self, f):
            raise RuntimeError("boom")
    fr.VideoSource = Bad

    async def fetch(call_id):
        return None
    assert run(rv.publish_reveal(room, "c1", 1, None, 15, rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep)) is True
    assert room.events[-1][0] == "unpublish"


# ------------------------------------------------------------------ controller hook
def _call(reveal_mode, reveal):
    c = CompetitionCall("call-9", "line-1", None, SimpleNamespace(), None, clock=lambda: 1000.0, count_s=10,
                        reveal_s=15, reveal_mode=reveal_mode, reveal=reveal)
    c.decision, c.t0 = "accept", 1000.0 - 10
    c.liveness_result, c.lc = "pass", None
    return c


def test_controller_starts_reveal_once_at_count_end_video_only():
    seen = []

    async def hook(points, seconds):
        seen.append((points, seconds))

    async def go(mode):
        c = _call(mode, hook)
        c._due = []
        c.tick(1000.0)
        c.tick(1000.1)
        await asyncio.gather(*list(c._bg))
    run(go("video"))
    assert seen == [(0, 15.0)]
    seen.clear()
    run(go("audio_only"))
    assert seen == []


def test_controller_hook_error_never_raises(caplog):
    async def hook(points, seconds):
        raise RuntimeError("nope")

    async def go():
        c = _call("video", hook)
        c._due = []
        assert c.tick(1000.0) is False
        await asyncio.gather(*list(c._bg))
    with caplog.at_level(logging.WARNING):
        run(go())
    assert any("reveal video failed" in r.getMessage() for r in caplog.records)
