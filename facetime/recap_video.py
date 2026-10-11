"""End-of-workout recap on the FaceTime call: the muscle heat map as a PNG, published as the agent's video track.

    from facetime.recap_video import get_recap_png, publish_recap
    png = get_recap_png(view)                    # view = session view (db/fixtures/sample_session.json shape)
    await publish_recap(room, png, seconds=45)   # shows it on the call, then unpublishes

PNG source: Jimmy's web endpoint WEB_URL/api/recap-image/<share_token> when it answers with an image, else a local Pillow render.
Nothing here raises into the call: errors are logged and the call carries on.
"""
import asyncio
import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
MUSCLES = json.loads((ROOT / 'shared' / 'muscles.json').read_text())
COLORS = MUSCLES['scoring']['colors']
GRAY_LABEL = MUSCLES['scoring'].get('gray_label', 'not trained this session')

BASE_W, BASE_H = 720, 1280
BG = (17, 24, 39)
SILHOUETTE = (55, 65, 81)
OUTLINE = (17, 24, 39)
TEXT = (243, 244, 246)
MUTED = (156, 163, 175)


def _log(msg):
    print(f'[recap] {msg}', flush=True)


# Body coordinates in a 100 x 200 unit box (x right, y down), body centred at x=50. Shapes: ('ellipse', (x0, y0, x1, y1)) or
# ('poly', [(x, y), ...]). Left-side shapes are mirrored to the right with _pair().
def _mirror(shape):
    kind, pts = shape
    if kind == 'ellipse':
        x0, y0, x1, y1 = pts
        return ('ellipse', (100 - x1, y0, 100 - x0, y1))
    return ('poly', [(100 - x, y) for x, y in pts])


def _pair(shape):
    return [shape, _mirror(shape)]


SILHOUETTE_SHAPES = [
    ('ellipse', (40, 2, 60, 24)),                                       # head
    ('poly', [(45, 22), (55, 22), (56, 30), (44, 30)]),                 # neck
    ('poly', [(30, 30), (70, 30), (68, 60), (64, 94), (36, 94), (32, 60)]),  # torso
    *_pair(('poly', [(30, 30), (22, 32), (16, 66), (12, 98), (20, 99), (28, 68), (32, 46)])),  # arm
    *_pair(('poly', [(36, 92), (50, 96), (49, 154), (47, 194), (36, 194), (34, 154)])),        # leg
]

REGIONS = {
    'front': {
        'traps':       _pair(('poly', [(34, 31), (44, 30), (43, 37), (36, 39), (32, 34)])),
        'front_delts': _pair(('ellipse', (21, 29, 33, 43))),
        'chest':       _pair(('poly', [(34, 33), (49, 33), (49, 48), (40, 50), (34, 46)])),
        'biceps':      _pair(('ellipse', (18, 44, 28, 66))),
        'forearms':    _pair(('poly', [(17, 68), (26, 69), (21, 96), (13, 95)])),
        'abs':         [('poly', [(43, 51), (57, 51), (57, 90), (50, 93), (43, 90)])],
        'obliques':    _pair(('poly', [(34, 52), (41, 52), (41, 89), (37, 86), (35, 70)])),
        'abductors':   _pair(('poly', [(31, 97), (35, 98), (35, 116), (31, 118), (28, 106)])),
        'quads':       _pair(('poly', [(35, 98), (44, 100), (44, 148), (40, 152), (35, 146)])),
        'adductors':   _pair(('poly', [(45, 100), (50, 100), (49, 136), (45, 136)])),
    },
    'back': {
        'rear_delts':  _pair(('ellipse', (21, 29, 33, 43))),
        'traps':       [('poly', [(38, 27), (62, 27), (66, 38), (50, 54), (34, 38)])],
        'triceps':     _pair(('ellipse', (18, 44, 28, 66))),
        'forearms':    _pair(('poly', [(17, 68), (26, 69), (21, 96), (13, 95)])),
        'lats':        _pair(('poly', [(34, 42), (47, 56), (46, 82), (38, 78), (34, 60)])),
        'abductors':   _pair(('poly', [(31, 92), (35, 94), (35, 112), (31, 114), (28, 100)])),
        'glutes':      _pair(('ellipse', (35, 90, 50, 114))),
        'hamstrings':  _pair(('poly', [(36, 116), (48, 116), (47, 150), (37, 150)])),
        'calves':      _pair(('ellipse', (36, 156, 47, 188))),
    },
}


def _hex(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _color(name):
    if isinstance(name, str) and name.startswith('#'):
        return _hex(name)
    return _hex(COLORS.get(name) or COLORS['gray'])


def _font(size):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:          # Pillow < 10.1: fixed-size bitmap font
        return ImageFont.load_default()


def _draw_shape(d, shape, ox, oy, s, fill):
    kind, pts = shape
    if kind == 'ellipse':
        x0, y0, x1, y1 = pts
        d.ellipse((ox + x0 * s, oy + y0 * s, ox + x1 * s, oy + y1 * s), fill=fill, outline=OUTLINE, width=2)
    else:
        d.polygon([(ox + x * s, oy + y * s) for x, y in pts], fill=fill, outline=OUTLINE, width=2)


def _draw_body(d, view_name, colors, ox, oy, s):
    for shape in SILHOUETTE_SHAPES:
        _draw_shape(d, shape, ox, oy, s, SILHOUETTE)
    for muscle, shapes in REGIONS[view_name].items():
        fill = _color(colors.get(muscle, 'gray'))
        for shape in shapes:
            _draw_shape(d, shape, ox, oy, s, fill)


def _exercise_line(ex):
    sets = ex.get('sets') or []
    parts = [f"{int(st.get('completed_reps') or 0)}/{int(st.get('planned_reps') or ex.get('planned_reps') or 0)}" for st in sets]
    return ' '.join([str(ex.get('name') or ex.get('exercise_key') or 'Exercise')] + (parts or ['-']))


def render_recap_png(view, size=(720, 1280)) -> bytes:
    """The recap card: title, FRONT and BACK bodies colored per muscle, one line per exercise, legend. Drawn at 720x1280, scaled to size."""
    view = view or {}
    img = Image.new('RGB', (BASE_W, BASE_H), BG)
    d = ImageDraw.Draw(img)
    client = (view.get('client') or {}).get('name') or 'Your'
    title = f"{client}'s workout" if client != 'Your' else 'Your workout'
    day = (view.get('day') or {}).get('title') or ''
    d.text((BASE_W // 2, 50), title, font=_font(44), fill=TEXT, anchor='mm')
    if day:
        d.text((BASE_W // 2, 100), day, font=_font(28), fill=MUTED, anchor='mm')

    colors = {m.get('muscle'): m.get('color', 'gray') for m in (view.get('muscles') or []) if isinstance(m, dict)}
    s, top = 2.9, 185
    for i, name in enumerate(('front', 'back')):
        ox = 40 + i * 350
        d.text((ox + 50 * s, top - 22), name.upper(), font=_font(28), fill=TEXT, anchor='mm')
        _draw_body(d, name, colors, ox, top, s)

    y = top + 200 * s + 30
    f = _font(30)
    for ex in view.get('exercises') or []:
        d.text((50, y), _exercise_line(ex), font=f, fill=TEXT)
        y += 42
    y += 20
    lf = _font(26)
    for key, label in (('green', 'good form'), ('yellow', 'watch it'), ('red', 'fix this'), ('gray', GRAY_LABEL)):
        d.rounded_rectangle((50, y + 2, 80, y + 30), radius=6, fill=_color(key))
        d.text((95, y), label, font=lf, fill=TEXT)
        y += 40

    if tuple(size) != (BASE_W, BASE_H):
        img = img.resize(tuple(int(v) for v in size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def fetch_recap_png(share_token, timeout=4.0):
    """Jimmy's renderer: GET WEB_URL/api/recap-image/<share_token>. None when WEB_URL is unset or on any error / non-200 / non-image."""
    base = (os.environ.get('WEB_URL') or '').rstrip('/')
    if not base or not share_token:
        return None
    try:
        import httpx
        r = httpx.get(f'{base}/api/recap-image/{share_token}', timeout=timeout, follow_redirects=True)
        ctype = r.headers.get('content-type', '').split(';')[0].strip().lower()
        if r.status_code != 200 or not ctype.startswith('image/') or not r.content:
            _log(f'web recap image unavailable ({r.status_code} {ctype or "no content-type"})')
            return None
        return r.content
    except Exception as e:
        _log(f'web recap image fetch failed: {type(e).__name__}')
        return None


def _as_png(data):
    """Decode any image bytes and re-encode as PNG; None if undecodable."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if im.format == 'PNG':
                return data
            buf = io.BytesIO()
            im.convert('RGBA').save(buf, format='PNG')
            return buf.getvalue()
    except Exception as e:
        _log(f'web recap image undecodable: {type(e).__name__}')
        return None


def get_recap_png(view) -> bytes:
    """Web image if available, else local render. Stored in the private 'recaps' bucket at <session id>.png when Supabase is configured."""
    session = (view or {}).get('session') or {}
    png = None
    fetched = fetch_recap_png(session.get('share_token'))
    if fetched:
        png = _as_png(fetched)
    if png is None:
        png = render_recap_png(view)
    sid = session.get('id')
    if sid:
        try:
            from facetime.supa import Supa
            if Supa.available():
                db = Supa()
                path = db.upload('recaps', f'{sid}.png', png, 'image/png')
                try:
                    db.update('sessions', {'recap_image_path': path}, id=f'eq.{sid}')
                except Exception as e:
                    _log(f'sessions.recap_image_path update failed: {e}')
                _log(f'uploaded recaps/{path}')
        except Exception as e:
            _log(f'recap upload failed: {e}')
    return png


async def publish_recap(room, png_bytes, seconds=45, fps=2, track_name='coach-video') -> None:
    """Show png_bytes as a video track on room.local_participant for `seconds` (or until cancelled), then unpublish. Never raises."""
    track = pub = None; published = False
    try:
        from livekit import rtc
        img = Image.open(io.BytesIO(png_bytes)).convert('RGBA')
        w, h = img.size
        w, h = w - (w % 2), h - (h % 2)                 # I420 wants even dimensions
        if (w, h) != img.size:
            img = img.crop((0, 0, w, h))
        if w < 2 or h < 2:
            raise ValueError(f'recap image too small: {img.size}')
        fps = max(0.5, float(fps or 2))
        frame = rtc.VideoFrame(w, h, rtc.VideoBufferType.RGBA, img.tobytes()).convert(rtc.VideoBufferType.I420)
        source = rtc.VideoSource(w, h)
        track = rtc.LocalVideoTrack.create_video_track(track_name, source)
        pub = await room.local_participant.publish_track(track, rtc.TrackPublishOptions(
            source=rtc.TrackSource.SOURCE_CAMERA, simulcast=False,
            video_encoding=rtc.VideoEncoding(max_framerate=max(1, int(fps)), max_bitrate=800_000)))
        published = True
        _log(f'published video track {track_name} {w}x{h} at {fps:g} fps for {seconds}s (recap)')
        loop = asyncio.get_running_loop()
        period = 1.0 / fps; t0 = next_t = loop.time()
        while True:
            source.capture_frame(frame)
            next_t += period
            if next_t - t0 >= float(seconds):
                break
            await asyncio.sleep(max(0.0, next_t - loop.time()))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        _log(f'recap video stopped: {e!r}')
    finally:
        if published:
            sid = getattr(pub, 'sid', None) or getattr(track, 'sid', None)
            try:
                await asyncio.wait_for(room.local_participant.unpublish_track(sid), timeout=5.0)
                _log(f'unpublished {track_name} (recap)')
            except (Exception, asyncio.CancelledError) as e:   # a second cancellation included: never propagate
                _log(f'recap unpublish failed: {e!r}')
