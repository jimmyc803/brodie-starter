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


def _watch(frames, wait, fetch, seconds=0.6, size=(720, 1280)):
    """Run the provider; sample current_frame() the way the coach-video loop does. Returns (samples, result)."""
    async def go():
        t = asyncio.ensure_future(frames.run("c1", seconds, wait, fetch=fetch))
        out = []
        while not t.done():
            out.append(frames.current_frame())
            await asyncio.sleep(0.02)
        out.append(frames.current_frame())
        return out, t.result()
    return run(go())


def test_card_frames_through_the_loop_hook_and_no_track(no_disk):
    frames = rv.RevealFrames(size=(720, 1280))
    assert frames.current_frame() is None                 # no reveal active: the loop keeps the mirror

    async def fetch(call_id, timeout=2.0):
        assert call_id == "c1"
        return rv._decode_card(png())
    out, ok = _watch(frames, done(None), fetch)
    assert ok is True
    shown = [f for f in out if f is not None]
    assert shown and shown[0].size == (720, 1280)
    assert shown[-1].tobytes() != shown[0].tobytes()       # the card replaced the neutral frame
    assert out[-1] is None and frames.current_frame() is None
    # no LiveKit track API is touched at all
    assert not hasattr(rv, "publish_reveal") and "rtc" not in vars(rv)


def test_fallback_when_card_unavailable(no_disk):
    frames = rv.RevealFrames(size=(720, 1280))

    async def fetch(call_id, timeout=2.0):
        return None
    out, ok = _watch(frames, done({"points": 7, "rank": 2}), fetch)
    shown = [f for f in out if f is not None]
    assert ok and shown[-1].tobytes() == rv.render_fallback(7, 2, (720, 1280)).tobytes()


def test_card_is_letterboxed_whole_never_cropped(no_disk):
    img = rv._frame((720, 1280), (), rv._decode_card(png(color=(255, 0, 0))))
    assert img.size == (720, 1280)
    px = img.load()
    red = (255, 0, 0)
    assert px[360, 640] == red and px[2, 195] == red and px[717, 1085] == red      # all four card edges present (no crop)
    assert px[2, 100] != red and px[2, 1120] != red and px[360, 20] != red         # canvas above/below


def test_landscape_card_is_letterboxed_whole_beside_the_pills(no_disk):
    img = rv._frame((1280, 720), (), rv._decode_card(png(color=(255, 0, 0))))
    assert img.size == (1280, 720)
    px = img.load()
    red = (255, 0, 0)
    xs = [x for x in range(1280) if px[x, 360] == red]
    ys = [y for y in range(720) if px[350, y] == red]
    w, h = xs[-1] - xs[0] + 1, ys[-1] - ys[0] + 1
    assert abs(w / h - 1080 / 1350) < 0.01                                     # whole card, aspect kept (no crop/stretch)
    assert h >= 600 and xs[-1] < int(1280 * 0.55)                              # big, in the left column
    right = [px[x, y] for x in range(720, 1280, 8) for y in range(0, 720, 8)]
    assert red not in right and len(set(right)) > 1                            # pills on the right, clear of the card


def test_landscape_frames_follow_the_phone(no_disk):
    frames = rv.RevealFrames(size=(720, 1280), landscape_size=(1280, 720))

    async def fetch(call_id, timeout=2.0):
        return None

    async def go():
        t = asyncio.ensure_future(frames.run("c1", 0.4, done({"points": 7, "rank": 2}), fetch=fetch))
        await asyncio.sleep(0.2)
        both = frames.current_frame(), frames.current_frame(landscape=True)
        await t
        return both
    portrait, land = run(go())
    assert portrait.size == (720, 1280) and land.size == (1280, 720)
    assert land.tobytes() == rv.render_fallback(7, 2, (1280, 720)).tobytes()
    assert frames.current_frame(landscape=True) is None                       # dropped with the portrait frame

    plain = rv.RevealFrames(size=(720, 1280))                                  # no landscape layout: portrait either way

    async def go_plain():
        t = asyncio.ensure_future(plain.run("c2", 0.3, None))
        await asyncio.sleep(0.15)
        f = plain.current_frame(landscape=True)
        await t
        return f
    assert run(go_plain()).size == (720, 1280)


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


def test_render_error_is_warn_and_no_frame(caplog, monkeypatch):
    frames = rv.RevealFrames(size=(720, 1280))

    def boom(size):
        raise RuntimeError("boom")
    monkeypatch.setattr(rv, "render_tallying", boom)
    with caplog.at_level(logging.WARNING, logger="challenge.reveal_video"):
        ok = run(frames.run("c1", 0.2, done(None)))
    assert ok is False and frames.current_frame() is None
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_cancel_drops_the_frame_and_current_frame_never_blocks():
    frames = rv.RevealFrames(size=(720, 1280))

    async def go():
        async def wait():
            await asyncio.sleep(3600)
        t = asyncio.ensure_future(frames.run("c1", 30, wait))
        await asyncio.sleep(0.1)
        assert frames.current_frame() is not None          # cached neutral frame, synchronous
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
        assert frames.current_frame() is None
    run(go())


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
    frames = rv.RevealFrames(size=(720, 1280))
    order = []

    async def go():
        ev = asyncio.Event()

        async def wait():
            await ev.wait()
            order.append("committed")
            return {"points": 4, "rank": 1}

        async def fetch(call_id, timeout=2.0):
            order.append("fetch")
            return None
        t = asyncio.ensure_future(frames.run("c1", 1.0, wait, fetch=fetch))
        await asyncio.sleep(0.1)
        first = frames.current_frame()
        assert order == []
        ev.set()
        await asyncio.sleep(0.2)
        last = frames.current_frame()
        await t
        return first, last
    first, last = run(go())
    assert order == ["committed", "fetch"]
    assert first.tobytes() == rv.render_tallying((720, 1280)).tobytes()
    assert last.tobytes() == rv.render_fallback(4, 1, (720, 1280)).tobytes()


def test_never_committed_shows_neutral_only():
    frames = rv.RevealFrames(size=(720, 1280))
    fetched = []

    async def wait():
        await asyncio.sleep(3600)

    async def fetch(call_id, timeout=2.0):
        fetched.append(1)
    out, ok = _watch(frames, wait, fetch, seconds=0.4)
    neutral = rv.render_tallying((720, 1280)).tobytes()
    assert fetched == [] and {f.tobytes() for f in out if f is not None} == {neutral}
