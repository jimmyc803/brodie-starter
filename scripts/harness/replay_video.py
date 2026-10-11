"""Optional real-video smoke: samples input at 10 fps through real MediaPipe."""
from pathlib import Path

import cv2

from facetime.pipeline import FramePipeline
from facetime.perception import Config, Perception


def run_video_smoke(video, output, max_seconds=30):
    video = Path(video)
    root = Path(__file__).resolve().parents[2]
    model = root / 'models/pose_landmarker_full.task'
    missing = [str(path) for path in (video, model) if not path.is_file()]
    if missing:
        return {'mode': 'actual-video', 'status': 'skipped', 'passed': None,
                'reason': 'Optional licensed local assets are absent', 'missing': missing,
                'curl_device_validated': False}
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f'cannot decode video: {video}')
    source_fps = capture.get(cv2.CAP_PROP_FPS)
    if source_fps < 10:
        capture.release()
        raise ValueError(f'video needs at least 10 fps; got {source_fps}')
    events = []
    pipe = FramePipeline(None, trigger='none')
    perception = Perception(Config(exercise='squats', announce=False), pipe=pipe,
                            clip_s=lambda _text: None, t0=0)
    perception.on_event(events.append)
    source_index = sampled = 0
    try:
        while sampled < max_seconds * 10:
            ok, bgr = capture.read()
            if not ok:
                break
            if source_index >= round(sampled * source_fps / 10):
                perception.process_frame(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB),
                                         t_recv=sampled / 10, t_ms=sampled * 100)
                sampled += 1
            source_index += 1
        reps = [event for event in events if event['type'] == 'rep']
        checks = {'frames_processed': sampled > 0, 'pose_detected': pipe.n_ok > 0,
                  'reps_detected': len(reps) > 0,
                  'sequential_reps': [r['n'] for r in reps] == list(range(1, len(reps) + 1))}
        report = {'mode': 'actual-video', 'status': 'passed' if all(checks.values()) else 'failed',
                  'passed': all(checks.values()), 'exercise': 'squat', 'video': str(video),
                  'source_fps': source_fps, 'sample_fps': 10, 'frames': sampled,
                  'pose_frames': pipe.n_ok, 'rep_count': len(reps), 'checks': checks,
                  'curl_device_validated': False, 'events': events}
    finally:
        capture.release()
        perception.close()
    import json
    (Path(output) / 'video-smoke.json').write_text(json.dumps(report, indent=2) + '\n')
    return {key: value for key, value in report.items() if key != 'events'}
