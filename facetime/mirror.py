"""The mirror: the caller's own frame as Brodie's video, with the pose, the count and the last cue drawn on it in the v3 look.

compose(rgb, lm, count, target, exercise, state, cue, avatar) -> HxWx3 uint8 RGB, portrait (W, H) = (720, 1280):
  - the landscape frame from the bridge is cropped to 9:16 around the person (the landmarks' centre; frame centre without a
    pose), then scaled to 720x1280;
  - skeleton lines and joints in volt (#D9FF3D) over black outlines, drawn only for landmarks seen with visibility > 0.3;
  - a top bar: the exercise and "count / target" (or the session state when no set is active);
  - a bottom bar with the last cue Brodie said (fades after a few seconds);
  - Brodie's face (facetime/avatar.py) as an inset bottom-right, mouth moving while he talks.
The palette is the v3 marketing look (memory: black + volt #D9FF3D; the typeface is Hershey here, no Archivo in the container).
No muscle paint: that renderer is a GPU batch job, not realtime.

Offline check:  .venv/bin/python -m facetime.mirror --video data/sc288/00262828.mp4 [--out data/tmp/mirror_sheet.png]
"""
import os, time
import numpy as np
import cv2
from facetime import ROOT

W, H = 720, 1280
VOLT = (217, 255, 61)          # RGB
BLACK = (0, 0, 0)
WHITE = (245, 245, 245)
CONNECTIONS = [(11, 12), (11, 13), (13, 15), (12, 14), (14, 16), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27), (24, 26), (26, 28),
               (27, 29), (29, 31), (28, 30), (30, 32), (0, 11), (0, 12)]
VIS = 0.3
CUE_SHOW_S = 4.0


LETTERBOX = False                 # True: a landscape frame is shown whole (blurred fill above and below) instead of cropped;
                                  # for floor exercises filmed from the side (push-ups), where a 9:16 crop cuts off head and feet


def letterbox_portrait(rgb):
    """The whole landscape frame scaled to width W, centred between the top bar and the cue bar, on a blurred fill."""
    h, w = rgb.shape[:2]; hh = int(round(W * h / w))
    fw = int(round(H * w / h)); fill = cv2.resize(rgb, (fw, H), interpolation=cv2.INTER_AREA)[:, (fw - W) // 2:(fw - W) // 2 + W]
    img = (cv2.GaussianBlur(cv2.resize(fill, (W // 8, H // 8)), (0, 0), 3)).astype(np.float32)
    img = cv2.resize((img * 0.45).astype(np.uint8), (W, H), interpolation=cv2.INTER_LINEAR)
    top, bottom = SAFE_TOP + 106, SAFE_BOTTOM - 110
    y_off = max(0, min(H - hh, (top + bottom - hh) // 2))
    img[y_off:y_off + hh] = cv2.resize(rgb, (W, hh), interpolation=cv2.INTER_AREA)
    ch = h * H / hh
    return img, (0, -y_off * ch / H, w, ch)        # the box _map uses: x scaled by W / w, y shifted down by y_off


def crop_portrait(rgb, lm):
    """9:16 crop of a landscape frame centred on the person (mean of the visible landmarks), scaled to WxH."""
    h, w = rgb.shape[:2]
    if LETTERBOX and w > h: return letterbox_portrait(rgb)
    cw = int(round(h * 9 / 16))
    if cw >= w:                                        # already portrait or square: letterbox-free scale
        return cv2.resize(rgb, (W, H), interpolation=cv2.INTER_AREA), (0, 0, w, h)
    cx = w / 2
    if lm is not None:
        pts = [x for x, y, *_ in lm[lm[:, 3] > VIS]] if lm.shape[1] > 3 else [x for x, y, *_ in lm]
        if pts: cx = float(np.clip(np.mean(pts) * w, cw / 2, w - cw / 2))
    x0 = int(round(cx - cw / 2)); x0 = max(0, min(w - cw, x0))
    crop = rgb[:, x0:x0 + cw]
    return cv2.resize(crop, (W, H), interpolation=cv2.INTER_AREA), (x0, 0, cw, h)


def _map(lm, box, full_w, full_h):
    x0, y0, cw, ch = box
    out = []
    for row in lm:
        x, y, v = row[0], row[1], row[3] if len(row) > 3 else 1.0
        px = (x * full_w - x0) * W / cw; py = (y * full_h - y0) * H / ch
        out.append((int(px), int(py), float(v)))
    return out


def skeleton(img, pts):
    for a, b in CONNECTIONS:
        if pts[a][2] > VIS and pts[b][2] > VIS:
            cv2.line(img, pts[a][:2], pts[b][:2], BLACK, 9, cv2.LINE_AA); cv2.line(img, pts[a][:2], pts[b][:2], VOLT, 4, cv2.LINE_AA)
    for x, y, v in pts[11:]:
        if v > VIS: cv2.circle(img, (x, y), 8, BLACK, -1, cv2.LINE_AA); cv2.circle(img, (x, y), 5, VOLT, -1, cv2.LINE_AA)


def text(img, s, org, scale, color, thick=2, outline=True):
    if outline: cv2.putText(img, s, org, cv2.FONT_HERSHEY_DUPLEX, scale, BLACK, thick + 4, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_DUPLEX, scale, color, thick, cv2.LINE_AA)


SAFE_X = int(W * 0.12)          # FaceTime "Fill" on an iPhone 17 Pro crops about 9 % each side of a 9:16 track; the island covers the top, the self-view the bottom left
SAFE_TOP = int(H * 0.14)
SAFE_BOTTOM = int(H * 0.80)


def bars(img, exercise, count, target, state, cue, cue_t, now):
    # top bar: below the island, inside the side margins
    cv2.rectangle(img, (0, 0), (W, SAFE_TOP + 100), BLACK, -1)
    cv2.rectangle(img, (0, SAFE_TOP + 100), (W, SAFE_TOP + 106), VOLT, -1)
    label = (exercise or state or 'brodie').upper()
    text(img, label, (SAFE_X, SAFE_TOP + 38), 1.0, WHITE, 2, outline=False)
    if target: text(img, f'{count} / {target}', (SAFE_X, SAFE_TOP + 88), 1.5, VOLT, 3, outline=False)
    elif state: text(img, state.upper(), (SAFE_X, SAFE_TOP + 88), 1.2, VOLT, 2, outline=False)
    (tw, th), _ = cv2.getTextSize('BRODIE', cv2.FONT_HERSHEY_DUPLEX, 1.0, 2)
    text(img, 'BRODIE', (W - SAFE_X - tw, SAFE_TOP + 38), 1.0, VOLT, 2, outline=False)
    # cue bar: above the bottom 20 % (the caller's self-view sits there), left of the inset
    if cue and now - cue_t <= CUE_SHOW_S:
        y0 = SAFE_BOTTOM - 110
        cv2.rectangle(img, (0, y0), (W, SAFE_BOTTOM), BLACK, -1); cv2.rectangle(img, (0, y0 - 6), (W, y0), VOLT, -1)
        s = str(cue); scale = 1.1 if len(s) <= 16 else (0.9 if len(s) <= 24 else 0.7)
        text(img, s, (SAFE_X, SAFE_BOTTOM - 42), scale, WHITE, 2, outline=False)


def inset(img, face_rgb, dy=0):
    """Brodie's face: right side, inside the side margin, above the cue bar."""
    if face_rgb is None: return
    face_rgb = np.asarray(face_rgb)
    fh, fw = 240, 135; f = cv2.resize(face_rgb, (fw, fh), interpolation=cv2.INTER_AREA)
    y1 = SAFE_BOTTOM - 130; x1 = W - SAFE_X - fw
    cv2.rectangle(img, (x1 - 4, y1 - fh - 4), (x1 + fw + 4, y1 + 4), VOLT, -1)
    img[y1 - fh:y1, x1:x1 + fw] = f


def compose(rgb, lm, count=0, target=None, exercise=None, state=None, cue=None, cue_t=0.0, face=None, now=None):
    now = time.time() if now is None else now
    full_h, full_w = rgb.shape[:2]
    img, box = crop_portrait(rgb, lm)
    img = np.ascontiguousarray(img)
    if lm is not None: skeleton(img, _map(lm, box, full_w, full_h))
    bars(img, exercise, count, target, state, cue, cue_t, now)
    inset(img, face)
    return img


if __name__ == '__main__':
    import argparse
    from facetime.pipeline import FramePipeline
    from facetime.session import Session
    from facetime.coach_agent import COUNTERS
    from facetime.avatar import Avatar
    ap = argparse.ArgumentParser(); ap.add_argument('--video', required=True); ap.add_argument('--out', default=os.path.join(ROOT, 'data', 'tmp', 'mirror_sheet.png'))
    ap.add_argument('--model', default=os.path.join(ROOT, 'data', 'models', 'clf_pose.pt')); ap.add_argument('--every', type=int, default=6)
    a = ap.parse_args()
    pipe = FramePipeline(a.model, None, 'full', {}, None, rep_params=COUNTERS['v2'], trigger='auto')
    cues = []
    sess = Session(pipe, lambda t, i, m, **k: cues.append((t, i, time.time())), plan='squats:5', announce=True, rest_s=5.0, set_timeout_s=45.0)
    av = Avatar(); cap = cv2.VideoCapture(a.video); tiles = []; i = 0; last = (None, 0.0)
    while True:
        ok, bgr = cap.read()
        if not ok: break
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB); r = pipe.process(rgb); sess.on_frame(r)
        if cues: last = (cues[-1][0], cues[-1][2])
        if i % a.every == 0 and len(tiles) < 8:
            tiles.append(compose(rgb, pipe.last_landmarks, sess.last_count, sess.target, pipe.exercise, sess.state, last[0], last[1], av.frame(speaking=bool(cues and time.time() - cues[-1][2] < 1.0))))
        i += 1
    sheet = np.concatenate([cv2.resize(t, (W // 2, H // 2)) for t in tiles], axis=1) if tiles else None
    os.makedirs(os.path.dirname(a.out), exist_ok=True); cv2.imwrite(a.out, cv2.cvtColor(sheet, cv2.COLOR_RGB2BGR)); print('wrote', a.out, 'tiles', len(tiles), 'frames', i, 'cues', len(cues))
    t = time.perf_counter(); [compose(rgb, pipe.last_landmarks, 3, 10, 'squats', 'active', 'Sink lower', time.time(), av.frame()) for _ in range(30)]; print(f'{(time.perf_counter() - t) / 30 * 1000:.1f} ms per frame')
