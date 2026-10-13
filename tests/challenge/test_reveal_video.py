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
        self.size, self.frames, self.closed = (w, h), [], False

    def capture_frame(self, f):
        self.frames.append(f)

    async def aclose(self):
        self.closed = True


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
    def __init__(self, fail_publish=False, hang_publish=False):
        self.events, self.fail = [], fail_publish
        lp = SimpleNamespace()

        async def publish_track(track, opts):
            if hang_publish:
                self.events.append(("publish_started",))
                await asyncio.sleep(3600)
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


def done(res):
    async def w():
        return res
    return w


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

    async def fetch(call_id, timeout=2.0):
        assert call_id == "c1"
        return rv._decode_card(png())
    ok = run(rv.publish_reveal(room, "c1", 15, done(None), rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert ok
    src = fr.sources[0]
    assert src.size == (720, 900) and len(src.frames) >= 2 * 13
    assert src.frames[0].size == (720, 900) and src.frames[0].kind == "I420"
    assert src.frames[-1].data == rv._decode_card(png()).convert("RGBA").tobytes()     # the card replaced the neutral frame
    assert clk.t - 100.0 <= 15
    assert [e[0] for e in room.events] == ["publish", "unpublish"] and room.events[1][1] == "PUB1"
    assert room.events[0][2].simulcast is False


def test_fallback_when_card_unavailable(no_disk):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()

    async def fetch(call_id, timeout=2.0):
        return None
    assert run(rv.publish_reveal(room, "c1", 15, done({"points": 7, "rank": 2}), rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert fr.sources[0].frames and room.events[-1][0] == "unpublish"
    assert fr.sources[0].frames[-1].data == rv.render_fallback(7, 2).convert("RGBA").tobytes()


def test_fallback_frame_has_text_and_no_handle():
    img = rv.render_fallback(7, 3)
    assert img.size == (720, 900)
    assert rv.render_fallback(None, None).tobytes() != rv.render_tallying().tobytes()
    assert rv.render_fallback(None, 3).tobytes() == rv.render_fallback(None, None).tobytes()   # no number without points
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

    async def fetch(call_id, timeout=2.0):
        return None
    with caplog.at_level(logging.WARNING, logger="challenge.reveal_video"):
        ok = run(rv.publish_reveal(room, "c1", 15, done(None), rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    assert ok is False and not any(e[0] == "publish" for e in room.events)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_capture_error_still_unpublishes(caplog):
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()
    orig = fr.VideoSource

    class Bad(orig):
        def capture_frame(self, f):
            raise RuntimeError("boom")
    fr.VideoSource = Bad

    async def fetch(call_id, timeout=2.0):
        return None
    assert run(rv.publish_reveal(room, "c1", 15, done(None), rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep)) is True
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

    async def hook(seconds, wait):
        seen.append(seconds)

    async def go(mode):
        c = _call(mode, hook)
        c._due = []
        c.tick(1000.0)
        c.tick(1000.1)
        await asyncio.gather(*list(c._bg))
    run(go("video"))
    assert seen == [15.0]
    seen.clear()
    run(go("audio_only"))
    assert seen == []


def test_controller_hook_error_never_raises(caplog):
    async def hook(seconds, wait):
        raise RuntimeError("nope")

    async def go():
        c = _call("video", hook)
        c._due = []
        assert c.tick(1000.0) is False
        await asyncio.gather(*list(c._bg))
    with caplog.at_level(logging.WARNING):
        run(go())
    assert any("reveal video failed" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------------------ review fixes (rv-33)
def _png_header(w, h):
    import struct
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", w, h) + b"\x08\x02\x00\x00\x00"


def _mock_card(monkeypatch, handler):
    import httpx
    real = httpx.AsyncClient
    monkeypatch.setenv("WEB_BASE_URL", "https://site.example")
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(transport=httpx.MockTransport(handler), *a, **k))


def test_oversized_dimensions_rejected_before_decoding(monkeypatch):
    import httpx
    called = []
    monkeypatch.setattr(Image, "open", lambda *a, **k: called.append(1))
    _mock_card(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "image/png"},
                                                       content=_png_header(60000, 60000) + b"\0" * 64))
    assert run(rv.fetch_card("c1")) is None and called == []


def test_oversized_body_is_capped(monkeypatch):
    import httpx
    body = png()
    big = body + b"\0" * (rv.MAX_BYTES + 10)
    _mock_card(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "image/png"}, content=big))
    assert run(rv.fetch_card("c1")) is None


def test_decode_runs_off_the_event_loop(monkeypatch):
    import httpx
    import threading
    seen = []
    real = rv._decode_card

    def spy(data):
        seen.append(threading.current_thread() is threading.main_thread())
        return real(data)
    monkeypatch.setattr(rv, "_decode_card", spy)
    _mock_card(monkeypatch, lambda req: httpx.Response(200, headers={"content-type": "image/png"}, content=png()))
    assert run(rv.fetch_card("c1")) is not None
    assert seen == [False]


def test_neutral_frame_until_commit_and_fetch_only_after():
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()
    order = []
    gate = asyncio.Event() if False else None

    async def go():
        ev = asyncio.Event()

        async def wait():
            await ev.wait()
            order.append("committed")
            return {"points": 4, "rank": 1}

        async def fetch(call_id, timeout=2.0):
            order.append("fetch")
            return None

        async def slow_sleep(dt):
            clk.t += dt
            if clk.t > 104:
                ev.set()
            await asyncio.sleep(0)
        assert await rv.publish_reveal(room, "c1", 15, wait, rtc=fr, fetch=fetch, clock=clk, sleep=slow_sleep)
    run(go())
    assert order == ["committed", "fetch"]
    frames = [f.data for f in fr.sources[0].frames]
    neutral = rv.render_tallying().convert("RGBA").tobytes()
    assert frames[0] == neutral and frames[-1] == rv.render_fallback(4, 1).convert("RGBA").tobytes()
    assert 1 < frames.count(neutral) < len(frames)


def test_never_committed_shows_neutral_only():
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()
    fetched = []

    async def wait():
        await asyncio.sleep(3600)

    async def fetch(call_id, timeout=2.0):
        fetched.append(1)
    run(rv.publish_reveal(room, "c1", 15, wait, rtc=fr, fetch=fetch, clock=clk, sleep=clk.sleep))
    neutral = rv.render_tallying().convert("RGBA").tobytes()
    assert fetched == [] and {f.data for f in fr.sources[0].frames} == {neutral}


def test_controller_wait_resolves_only_after_ack_and_carries_points():
    got = {}

    async def hook(seconds, wait):
        got["res"] = await wait()

    async def go():
        c = _call("video", hook)
        c._due = []
        c.tick(1000.0)
        await asyncio.sleep(0.05)
        assert "res" not in got
        c.commit_result = {"points": 6, "rank": 2}
        c._commit_evt.set()
        await asyncio.sleep(0.05)
    run(go())
    assert got["res"] == {"points": 6, "rank": 2}


def test_controller_cancels_reveal_on_end_and_leave():
    async def hook(seconds, wait):
        await asyncio.sleep(3600)

    async def go(how):
        left = []
        c = _call("video", hook)
        c._leave_fn = left.append
        c._due = []
        c.tick(1000.0)
        await asyncio.sleep(0)
        t = c._reveal_task
        assert t is not None and not t.done()
        if how == "leave":
            c._leave("x")
        else:
            await c.end("x")
        await asyncio.sleep(0)
        assert t.cancelled() or t.done()
        assert c._reveal_task is None
    run(go("leave"))
    run(go("end"))


def test_stalled_publish_is_bounded_and_cleaned_up():
    fr, room = FakeRtc(), FakeRoom(hang_publish=True)

    async def go():
        loop = asyncio.get_running_loop()
        t = loop.time()
        ok = await rv.publish_reveal(room, "c1", 1.6, done(None), rtc=fr)
        return ok, loop.time() - t
    ok, dt = run(go())
    assert ok is False and dt < 1.6
    assert fr.sources[0].closed is True


def test_cancel_during_reveal_unpublishes_and_closes_source():
    clk, fr, room = Clk(), FakeRtc(), FakeRoom()

    async def go():
        t = asyncio.ensure_future(rv.publish_reveal(room, "c1", 15, done(None), rtc=fr,
                                                    fetch=lambda *a, **k: done(None)()))
        await asyncio.sleep(0.2)
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
    run(go())
    assert room.events[-1][0] == "unpublish" and fr.sources[0].closed is True
