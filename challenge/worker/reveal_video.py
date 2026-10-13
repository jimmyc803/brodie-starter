"""REVEAL_MODE=video (task 33, SPEC §3 row 9, CONTRACTS C7.v): during the reveal publish the result card (or a local
fallback frame) as a 720x900 LiveKit video track at 2 fps, then unpublish.

    await publish_reveal(room, call_id, points=3, rank=None, seconds=15)

The card is the web route GET <WEB_BASE_URL>/r/<call_id>/card (1080x1350 PNG, same call id the dispatcher uses; never a
handle or phone). Fetching is bounded at FETCH_TIMEOUT_S in total; on any miss a Pillow frame with points and rank text
(no handle) is drawn instead. Everything stays in memory: nothing is written to disk. Any error is logged at WARN and
publish_reveal returns False (the caller keeps the audio_only reveal); it never raises and finishes within `seconds`
of its start.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import time
from typing import Any
from urllib.parse import quote

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger("challenge.reveal_video")

W, H = 720, 900
FPS = 2.0
FETCH_TIMEOUT_S = 2.0
UNPUBLISH_TIMEOUT_S = 1.0
TRACK_NAME = "reveal-video"
BG, FG, ACCENT = (13, 27, 34), (240, 244, 246), (255, 140, 40)


def card_url(call_id: str, base: str | None = None) -> str | None:
    """<base>/r/<call_id>/card, base from WEB_BASE_URL (else WEB_URL); None when unset or not http(s)."""
    if base is None:
        base = os.environ.get("WEB_BASE_URL") or os.environ.get("WEB_URL") or ""
    base = base.strip().rstrip("/")
    if not re.match(r"^https?://", base) or not call_id:
        return None
    return f"{base}/r/{quote(str(call_id), safe='')}/card"


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:                      # Pillow < 10.1
        return ImageFont.load_default()


def render_fallback(points: int | None, rank: int | None) -> Image.Image:
    """Local frame: points and rank only (no handle, no name)."""
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    lines = [("TIME!", 96, ACCENT), (f"{int(points or 0)} pts", 140, FG),
             (f"Rank #{int(rank)}" if rank else "Rank updating...", 72, FG), ("Check your texts", 44, ACCENT)]
    for (text, size, color), y in zip(lines, (150, 300, 500, 700)):
        f = _font(size)
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=color)
    return img


def _decode_card(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        return im.convert("RGB").resize((W, H), Image.LANCZOS)


async def fetch_card(call_id: str, timeout: float = FETCH_TIMEOUT_S, base: str | None = None) -> Image.Image | None:
    """The card as a 720x900 image, or None (unset base, 404/not ready, non-image, slow, any error). Total <= timeout."""
    url = card_url(call_id, base)
    if url is None:
        return None

    async def _get() -> Image.Image | None:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
            r = await c.get(url)
        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if r.status_code != 200 or ctype != "image/png" or not r.content:
            log.info("reveal card not available (%s %s)", r.status_code, ctype or "no content-type")
            return None
        return _decode_card(r.content)

    try:
        return await asyncio.wait_for(_get(), timeout=timeout)
    except (Exception, asyncio.TimeoutError) as e:
        log.info("reveal card fetch failed: %s", type(e).__name__)
        return None


async def publish_reveal(room: Any, call_id: str, points: int | None, rank: int | None, seconds: float, *,
                         fps: float = FPS, rtc: Any = None, fetch=None, clock=time.monotonic,
                         sleep=asyncio.sleep) -> bool:
    """Publish the reveal frame for what is left of `seconds`, then unpublish. True when frames were published.
    Never raises (cancellation excepted); on any error WARN and False so the call stays audio_only."""
    t_start = clock()
    track = pub = None
    published = False
    try:
        if rtc is None:
            from livekit import rtc as _rtc
            rtc = _rtc
        img = await (fetch or fetch_card)(call_id)
        kind = "card"
        if img is None:
            img, kind = render_fallback(points, rank), "fallback"
        frame = rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.convert("RGBA").tobytes()).convert(
            rtc.VideoBufferType.I420)
        source = rtc.VideoSource(W, H)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        pub = await room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False,
            video_encoding=rtc.VideoEncoding(max_framerate=max(1, int(fps)), max_bitrate=800_000)))
        published = True
        end_t = t_start + float(seconds) - UNPUBLISH_TIMEOUT_S      # leave room to unpublish inside the reveal
        log.info("call %s: reveal video published (%s frame, %dx%d, %g fps)", call_id, kind, W, H, fps)
        period = 1.0 / fps
        while True:
            source.capture_frame(frame)
            now = clock()
            if now + period > end_t:
                if end_t > now:
                    await sleep(end_t - now)
                break
            await sleep(period)
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("call %s: reveal video failed (%s: %s); audio_only reveal", call_id, type(e).__name__, e)
        return published
    finally:
        if published:
            sid = getattr(pub, "sid", None) or getattr(track, "sid", None)
            try:
                await asyncio.wait_for(room.local_participant.unpublish_track(sid), timeout=UNPUBLISH_TIMEOUT_S)
            except (Exception, asyncio.CancelledError) as e:
                log.warning("call %s: reveal video unpublish failed (%s)", call_id, type(e).__name__)
