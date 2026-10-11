import asyncio
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from facetime import recap_video as rv

ROOT = Path(__file__).resolve().parent.parent
VIEW = json.loads((ROOT / 'db' / 'fixtures' / 'sample_session.json').read_text())
MUSCLES = json.loads((ROOT / 'shared' / 'muscles.json').read_text())['muscles']


@pytest.mark.parametrize('size', [(720, 1280), (360, 640)])
def test_render_png_size(size):
    data = rv.render_recap_png(VIEW, size=size)
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    assert Image.open(io.BytesIO(data)).size == size


def test_render_handles_sparse_view():
    assert Image.open(io.BytesIO(rv.render_recap_png({}))).size == (720, 1280)


def test_every_muscle_has_coordinates_per_view():
    for muscle, meta in MUSCLES.items():
        views = ('front', 'back') if meta['view'] == 'both' else (meta['view'],)
        for v in views:
            assert rv.REGIONS[v].get(muscle), f'{muscle} missing in {v}'
    for v, regions in rv.REGIONS.items():
        assert set(regions) <= set(MUSCLES), f'unknown muscle in {v}'


def test_fetch_none_without_web_url(monkeypatch):
    monkeypatch.delenv('WEB_URL', raising=False)
    assert rv.fetch_recap_png('tok') is None


def test_fetch_none_with_bogus_url(monkeypatch):
    monkeypatch.setenv('WEB_URL', 'http://127.0.0.1:9')
    assert rv.fetch_recap_png('tok', timeout=1.0) is None
    monkeypatch.setenv('WEB_URL', 'http://nonexistent.invalid')
    assert rv.fetch_recap_png('tok', timeout=1.0) is None


def test_get_recap_png_falls_back_to_render(monkeypatch):
    monkeypatch.delenv('WEB_URL', raising=False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_SERVICE_ROLE_KEY', raising=False)
    assert rv.get_recap_png(VIEW)[:8] == b'\x89PNG\r\n\x1a\n'


class FakePub:
    sid = 'TR_fake'


class FakeParticipant:
    def __init__(self):
        self.published, self.unpublished = [], []

    async def publish_track(self, track, opts):
        self.published.append((track, opts))
        return FakePub()

    async def unpublish_track(self, sid):
        self.unpublished.append(sid)


class FakeRoom:
    def __init__(self):
        self.local_participant = FakeParticipant()


def _rtc():
    try:
        from livekit import rtc
        return rtc
    except Exception as e:
        pytest.skip(f'livekit rtc not importable: {e!r}')


def test_publish_recap_pushes_and_unpublishes(monkeypatch):
    rtc = _rtc()
    frames = []
    orig = rtc.VideoSource.capture_frame
    monkeypatch.setattr(rtc.VideoSource, 'capture_frame', lambda self, f, *a, **k: (frames.append(f), orig(self, f, *a, **k)))
    room = FakeRoom()
    png = rv.render_recap_png(VIEW, size=(360, 640))
    asyncio.run(rv.publish_recap(room, png, seconds=1.0, fps=4))
    lp = room.local_participant
    assert len(lp.published) == 1 and lp.published[0][0].name == 'coach-video'
    assert len(frames) >= 1 and frames[0].width == 360 and frames[0].height == 640
    assert lp.unpublished == ['TR_fake']


def test_publish_recap_cancel_unpublishes_and_never_raises():
    _rtc()
    room = FakeRoom()

    async def go():
        t = asyncio.create_task(rv.publish_recap(room, rv.render_recap_png(VIEW, size=(360, 640)), seconds=30, fps=2))
        await asyncio.sleep(0.3)
        t.cancel()
        await t

    asyncio.run(go())
    assert room.local_participant.unpublished == ['TR_fake']


def test_publish_recap_bad_png_never_raises():
    _rtc()
    room = FakeRoom()
    asyncio.run(rv.publish_recap(room, b'not a png', seconds=1))
    assert room.local_participant.published == [] and room.local_participant.unpublished == []
