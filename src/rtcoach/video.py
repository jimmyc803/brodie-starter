import json, subprocess, numpy as np


def probe_size(path):
    """(width, height) of the first video stream. JSON output, so ffprobe builds that also print stream groups (which
    made the old csv output read '1280\\n\\n720') parse the same way."""
    p = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                        '-of', 'json', path], capture_output=True, text=True)
    try:
        streams = json.loads(p.stdout or '{}').get('streams') or []
        s = next(x for x in streams if x.get('width') and x.get('height'))
        return int(s['width']), int(s['height'])
    except (ValueError, StopIteration) as e:
        raise RuntimeError(f'ffprobe found no video stream size in {path}: {p.stderr.strip() or p.stdout.strip()!r}') from e


def read_frames(path, w=None, h=None):
    if w is None or h is None:
        w, h = probe_size(path)
    p = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], capture_output=True)
    if p.returncode != 0:
        raise RuntimeError(f'ffmpeg failed to decode {path}: {p.stderr.decode(errors="replace").strip()}')
    raw = p.stdout
    n = len(raw) // (w * h * 3)
    return np.frombuffer(raw[:n * w * h * 3], np.uint8).reshape(n, h, w, 3)
