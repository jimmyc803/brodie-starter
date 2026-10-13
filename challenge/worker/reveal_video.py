"""REVEAL_MODE=video (task 33, SPEC §3 row 9, CONTRACTS C7.v): during the reveal publish the result card (or a local
fallback frame) as a 720x900 LiveKit video track at 2 fps, then unpublish.

    await publish_reveal(room, call_id, points=3, rank=None, seconds=15)

The card is the web route GET <WEB_BASE_URL>/r/<call_id>/card (1080x1350 PNG, same call id the dispatcher uses; never a
handle or phone). Fetching is bounded at FETCH_TIMEOUT_S in total; on any miss a Pillow frame with points and rank text
(no handle) is drawn instead. Everything stays in memory: nothing is written to disk. Any error is logged at WARN and
publish_reveal returns False (the caller keeps the audio_only reveal); it never raises and finishes within `seconds`
of its start. Numbers are shown only when authoritative: the neutral "Tallying your reps..." frame is up until the
dispatcher acknowledged reps_committed; then the card is fetched (streamed with a byte cap, PNG header checked, decoded
off the event loop), else the committed points/rank from the dispatcher, else "Score pending" (no number).
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
MAX_BYTES = 4 * 1024 * 1024
MAX_W, MAX_H = 2160, 2700
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


def _text_frame(lines) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for (text, size, color), y in zip(lines, (150, 300, 500, 700)):
        f = _font(size)
        w = d.textlength(text, font=f)
        d.text(((W - w) / 2, y), text, font=f, fill=color)
    return img


def render_tallying() -> Image.Image:
    """Neutral frame while the score is not committed: no numbers."""
    return _text_frame([("TIME!", 96, ACCENT), ("Tallying", 100, FG), ("your reps...", 100, FG),
                        ("Check your texts", 44, ACCENT)])


def render_fallback(points: int | None, rank: int | None) -> Image.Image:
    """Committed (authoritative) points and rank, no handle or name. Missing -> "Score pending" / "Rank pending"."""
    if points is None:
        return _text_frame([("TIME!", 96, ACCENT), ("Score", 110, FG), ("pending", 110, FG),
                            ("Check your texts", 44, ACCENT)])
    return _text_frame([("TIME!", 96, ACCENT), (f"{int(points)} pts", 140, FG),
                        (f"Rank #{int(rank)}" if rank else "Rank pending", 72, FG), ("Check your texts", 44, ACCENT)])


def png_size(head: bytes) -> tuple[int, int] | None:
    """(width, height) from the PNG signature + IHDR in the first 24 bytes; None when it is not a PNG."""
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _decode_card(data: bytes) -> Image.Image:
    """Blocking: runs in a worker thread. Rejects non-PNG and anything over MAX_W x MAX_H before decoding."""
    size = png_size(data[:24])
    if size is None or not (0 < size[0] <= MAX_W and 0 < size[1] <= MAX_H):
        raise ValueError(f"card image rejected (size {size})")
    with Image.open(io.BytesIO(data)) as im:
        if im.format != "PNG" or im.size != size or im.size[0] * im.size[1] > MAX_W * MAX_H:
            raise ValueError("card image rejected (header mismatch)")
        im.load()
        return im.convert("RGB").resize((W, H), Image.LANCZOS)


async def fetch_card(call_id: str, timeout: float = FETCH_TIMEOUT_S, base: str | None = None) -> Image.Image | None:
    """The card as a 720x900 image, or None (unset base, 404/not ready, non-image, too big, slow, any error).
    Download (streamed, MAX_BYTES cap) and decode (thread) together stay within `timeout`."""
    url = card_url(call_id, base)
    if url is None or timeout <= 0:
        return None

    async def _get() -> Image.Image | None:
        import httpx
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as c:
            async with c.stream("GET", url) as r:
                ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                if r.status_code != 200 or ctype != "image/png":
                    log.info("reveal card not available (%s %s)", r.status_code, ctype or "no content-type")
                    return None
                try:
                    if int(r.headers.get("content-length", "0")) > MAX_BYTES:
                        return None
                except ValueError:
                    return None
                buf = bytearray()
                async for chunk in r.aiter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        log.info("reveal card over %d bytes; ignored", MAX_BYTES)
                        return None
                    if len(buf) >= 24 and png_size(bytes(buf[:24])) is None:
                        return None
        return await asyncio.to_thread(_decode_card, bytes(buf))

    try:
        return await asyncio.wait_for(_get(), timeout=timeout)
    except (Exception, asyncio.TimeoutError) as e:
        log.info("reveal card fetch failed: %s", type(e).__name__)
        return None


async def publish_reveal(room: Any, call_id: str, seconds: float, wait_committed=None, *,
                         fps: float = FPS, rtc: Any = None, fetch=None, clock=time.monotonic,
                         sleep=asyncio.sleep) -> bool:
    """Publish the reveal frame for what is left of `seconds`, then unpublish. True when frames were published.
    `wait_committed` is an async callable resolving to the dispatcher's reps_committed result (dict with optional
    points/rank) once acknowledged; until then the neutral frame shows. Never raises (cancellation excepted); on any
    error WARN and False so the call stays audio_only."""
    t_start = clock()
    end_t = t_start + float(seconds) - UNPUBLISH_TIMEOUT_S      # leave room to unpublish inside the reveal
    track = pub = source = upgrade = None
    attempted = False
    try:
        if rtc is None:
            from livekit import rtc as _rtc
            rtc = _rtc

        def to_frame(img):
            return rtc.VideoFrame(W, H, rtc.VideoBufferType.RGBA, img.convert("RGBA").tobytes()).convert(
                rtc.VideoBufferType.I420)

        async def upgraded():
            res = await wait_committed()
            card = await (fetch or fetch_card)(call_id, min(FETCH_TIMEOUT_S, end_t - clock()))
            if card is not None:
                return to_frame(card), "card"
            res = res if isinstance(res, dict) else {}
            return to_frame(render_fallback(res.get("points"), res.get("rank"))), "committed"

        frame = to_frame(render_tallying())
        source = rtc.VideoSource(W, H)
        track = rtc.LocalVideoTrack.create_video_track(TRACK_NAME, source)
        left = end_t - clock()
        if left <= 0:
            return False
        attempted = True
        pub = await asyncio.wait_for(room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False,
            video_encoding=rtc.VideoEncoding(max_framerate=max(1, int(fps)), max_bitrate=800_000))), left)
        log.info("call %s: reveal video published (%dx%d, %g fps)", call_id, W, H, fps)
        if wait_committed is not None:
            upgrade = asyncio.ensure_future(upgraded())
        period = 1.0 / fps
        while True:
            if upgrade is not None and upgrade.done():
                try:
                    frame, kind = upgrade.result()
                    log.info("call %s: reveal frame upgraded (%s)", call_id, kind)
                except Exception as e:
                    log.warning("call %s: reveal upgrade failed (%s); neutral frame stays", call_id, type(e).__name__)
                upgrade = None
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
    except (Exception, asyncio.TimeoutError) as e:
        log.warning("call %s: reveal video failed (%s: %s); audio_only reveal", call_id, type(e).__name__, e)
        return pub is not None
    finally:
        if upgrade is not None:
            upgrade.cancel()
        if attempted:
            sid = getattr(pub, "sid", None) or getattr(track, "sid", None)
            if sid:
                try:
                    await asyncio.wait_for(asyncio.shield(room.local_participant.unpublish_track(sid)),
                                           timeout=UNPUBLISH_TIMEOUT_S)
                except (Exception, asyncio.CancelledError) as e:
                    log.warning("call %s: reveal video unpublish failed (%s)", call_id, type(e).__name__)
        if source is not None and hasattr(source, "aclose"):
            try:
                await asyncio.wait_for(asyncio.shield(source.aclose()), timeout=UNPUBLISH_TIMEOUT_S)
            except (Exception, asyncio.CancelledError) as e:
                log.warning("call %s: reveal video source close failed (%s)", call_id, type(e).__name__)
