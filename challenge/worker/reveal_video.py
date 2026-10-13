"""REVEAL_MODE=video (task 33/39, SPEC §3 row 9, CONTRACTS C7.v): during the reveal the worker's existing "coach-video"
track shows the result card (or a local on-brand frame) instead of the push-up mirror. This module publishes no track:

    frames = RevealFrames(size=(720, 1280), landscape_size=(1280, 720))   # the coach-video loop's two layouts
    await frames.run(call_id, seconds, wait_committed)     # the controller's reveal hook (a task, cancellable)
    frames.current_frame(landscape)                  # loop tick: cached PIL RGB image, or None when no reveal is active

current_frame() never blocks (a cached image). The controller commits reps at count end (drain -> reps_committed), so
the frame shows authoritative numbers: neutral "Tallying" until the dispatcher acknowledged the commit, then the card
(GET <WEB_BASE_URL>/r/<call_id>/card, 1080x1350 PNG, call id only, streamed with a byte cap, PNG header checked, decoded
off the event loop, download+decode <= 2 s), else the committed points (and rank when present), else "Score pending"
(no number). Never a locally computed score. All in memory, no disk, no zoom/pan: the card is letterboxed whole. Any
error is logged at WARN and the loop keeps the mirror (the audio_only reveal still plays).
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

from PIL import Image

log = logging.getLogger("challenge.reveal_video")

W, H = 720, 900
FETCH_TIMEOUT_S = 2.0
MAX_BYTES = 4 * 1024 * 1024
MAX_W, MAX_H = 2160, 2700


def card_url(call_id: str, base: str | None = None) -> str | None:
    """<base>/r/<call_id>/card, base from WEB_BASE_URL (else WEB_URL); None when unset or not http(s)."""
    if base is None:
        base = os.environ.get("WEB_BASE_URL") or os.environ.get("WEB_URL") or ""
    base = base.strip().rstrip("/")
    if not re.match(r"^https?://", base) or not call_id:
        return None
    return f"{base}/r/{quote(str(call_id), safe='')}/card"


def _frame(size, lines, card: Image.Image | None = None) -> Image.Image:
    """Paper canvas with brand text/pills (cached sprites). lines: (text, px, colour) centred in the middle band, or the
    whole `card` letterboxed there. A pink 'TIME!' pill on top, a ticket-stub reminder below. RGB."""
    import numpy as np
    from facetime import brand
    w, h = size
    canvas = np.empty((h, w, 3), np.uint8)
    canvas[:] = brand.CANVAS
    top, a_top = brand.pill((("TIME!", 64, brand.INK),), fill=brand.PINK, align="center", min_w=260)
    stub, a_stub = brand.pill((("CHECK YOUR TEXTS", 30, brand.INK, "mono"),), fill=brand.YELLOW, align="center")
    if card is not None and w > h:                                            # landscape: card left, pills right
        col = int(w * 0.55)
        cx = col + (w - col) // 2
        brand.blit(canvas, top, a_top, cx - top.shape[1] // 2, int(h * 0.32))
        brand.blit(canvas, stub, a_stub, cx - stub.shape[1] // 2, int(h * 0.58))
        c = card.convert("RGB")
        c.thumbnail((int(col * 0.92), int(h * 0.90)), Image.LANCZOS)         # fit whole: never crop
        canvas_im = Image.fromarray(canvas)
        canvas_im.paste(c, ((col - c.width) // 2, (h - c.height) // 2))
        return canvas_im
    brand.blit(canvas, top, a_top, (w - top.shape[1]) // 2, int(h * 0.06))
    brand.blit(canvas, stub, a_stub, (w - stub.shape[1]) // 2, int(h * 0.90))
    if card is not None:
        c = card.convert("RGB")
        c.thumbnail((w, int(h * 0.76)), Image.LANCZOS)                        # fit whole: never crop
        canvas_im = Image.fromarray(canvas)
        canvas_im.paste(c, ((w - c.width) // 2, (h - c.height) // 2))
        return canvas_im
    sizes = [brand.text_size(t, px)[1] for t, px, _ in lines]
    y = (h - sum(sizes) - 24 * (len(lines) - 1)) / 2
    for (t, px, col), th in zip(lines, sizes):
        rgb, a = brand.text(t, px, col)
        brand.blit(canvas, rgb, a, int((w - rgb.shape[1]) / 2), int(y))
        y += th + 24
    return Image.fromarray(canvas)


def render_tallying(size=(W, H)) -> Image.Image:
    """Neutral frame while the score is not committed: no numbers."""
    from facetime import brand
    return _frame(size, [("TALLYING", 120, brand.INK), ("YOUR REPS...", 96, brand.BLUE)])


def render_fallback(points: int | None, rank: int | None, size=(W, H)) -> Image.Image:
    """Committed (authoritative) points and rank, no handle or name. Missing -> "Score pending" / no rank line."""
    from facetime import brand
    if points is None:
        return _frame(size, [("SCORE", 140, brand.INK), ("PENDING", 140, brand.BLUE)])
    lines = [(f"{int(points)} PTS", 200, brand.INK)]
    lines.append((f"RANK #{int(rank)}", 90, brand.BLUE) if rank else ("RANK PENDING", 64, brand.INK3))
    return _frame(size, lines)


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


class RevealFrames:
    """Frame provider for the coach-video loop (see module doc). One instance per worker; run() is the controller's
    reveal task. current_frame() is non-blocking and returns the cached frame while a reveal is active."""

    def __init__(self, size=(W, H), clock=time.monotonic, landscape_size=None):
        self.size, self._clock = tuple(size), clock
        self.landscape_size = tuple(landscape_size) if landscape_size else None
        self._img: Image.Image | None = None
        self._img_l: Image.Image | None = None                                 # same frame laid out for landscape_size
        self._until = 0.0

    def current_frame(self, landscape: bool = False) -> Image.Image | None:
        """The cached frame (the landscape layout when asked for and configured), or None when no reveal is active."""
        img = self._img_l if landscape and self._img_l is not None else self._img
        if img is None or self._clock() >= self._until:
            return None
        return img

    def _both(self, render):
        """render(size) -> image, for the portrait size and (when configured) the landscape size; off the loop."""
        img = render(self.size)
        return img, (render(self.landscape_size) if self.landscape_size else None)

    async def run(self, call_id: str, seconds: float, wait_committed=None, *, fetch=None) -> bool:
        """Show the reveal for `seconds` (from now): neutral frame, upgraded once `wait_committed` (async, resolves to
        the reps_committed result dict with optional points/rank) has resolved. Returns True when frames were shown.
        Never raises (cancellation excepted); the frame is dropped on every exit."""
        end_t = self._clock() + float(seconds)
        try:
            self._img, self._img_l = await asyncio.to_thread(self._both, render_tallying)
            self._until = end_t
            log.info("call %s: reveal frame ready (%dx%d)", call_id, *self.size)
            if wait_committed is not None:
                res = await asyncio.wait_for(wait_committed(), max(0.0, end_t - self._clock()))
                card = await (fetch or fetch_card)(call_id, min(FETCH_TIMEOUT_S, end_t - self._clock()))
                res = res if isinstance(res, dict) else {}
                if card is not None:
                    self._img, self._img_l = await asyncio.to_thread(self._both, lambda sz: _frame(sz, (), card))
                    kind = "card"
                else:
                    pts, rank = res.get("points"), res.get("rank")
                    self._img, self._img_l = await asyncio.to_thread(self._both, lambda sz: render_fallback(pts, rank, sz))
                    kind = "committed"
                log.info("call %s: reveal frame upgraded (%s)", call_id, kind)
            await asyncio.sleep(max(0.0, end_t - self._clock()))
            return True
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            return self._img is not None
        except Exception as e:
            log.warning("call %s: reveal frame failed (%s: %s); audio_only reveal", call_id, type(e).__name__, e)
            return self._img is not None
        finally:
            self._img = self._img_l = None
