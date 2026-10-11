#!/usr/bin/env python3
"""Offline input-boundary replay; runs the real counter, perception and session sink."""
import argparse
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
MUSCLE_COUNT = len(json.loads((ROOT / 'shared' / 'muscles.json').read_text())['muscles'])

import numpy as np

from facetime import pipeline, session_sink
from facetime.perception import Config, Perception
from facetime.session_sink import SessionSink

FPS = 10
CYCLE = [170] * 4 + [140, 120, 95, 75, 60, 50, 50, 60, 85, 110, 130, 155, 170, 170]
PARTIAL = [170] * 4 + [145, 130, 100, 80, 100, 140, 170, 170]


def landmark_frame(angle=170, right=170, left_visibility=.99, right_visibility=.8):
    """Construct MediaPipe-shaped input, never substitute counter/events/scoring."""
    img = np.full((33, 5), .5)
    world = np.zeros((33, 3))
    for ids, degrees, visibility in [((11, 13, 15), angle, left_visibility),
                                      ((12, 14, 16), right, right_visibility)]:
        img[list(ids), 3:5] = visibility
        shoulder, elbow, wrist = ids
        world[shoulder] = [0, -1, 0]
        world[elbow] = [0, 0, 0]
        world[wrist] = [np.sin(np.radians(degrees)), -np.cos(np.radians(degrees)), 0]
    return img, world


def frames(angles, **kwargs):
    return [landmark_frame(angle, **kwargs) for angle in angles]


def scenarios():
    warmup = frames([170] * 10)
    return {
        'five_complete_two_partial': (warmup + frames(CYCLE * 5 + PARTIAL * 2), 5, 7),
        'occlusion_discards_partial': (warmup + frames(CYCLE[:11]) +
            frames([50], left_visibility=.1) + frames([50, 90, 130, 170, 170]), 0, 1),
        'opposite_arm_cannot_complete_locked_rep': (warmup + frames(CYCLE[:11]) +
            frames([50] * 10, right=170, left_visibility=.7, right_visibility=.99) +
            frames(CYCLE[11:]), 1, 2),
        'threshold_noise': (warmup + frames([64, 66] * 20 + [170] * 10), 0, 1),
        'visible_right_arm': (frames([170] * 10, left_visibility=.2) +
            [landmark_frame(170, right=a, left_visibility=.2) for a in CYCLE * 2], 2, 3),
        'missing_pose_discards_partial': (warmup + frames(CYCLE[:11]) + [(None, None)] +
            frames([50, 90, 130, 170, 170]), 0, 1),
    }


class RecordedPose:
    """Camera/MediaPipe boundary double; the production pipeline consumes each frame."""
    def __init__(self, trace):
        self.trace = iter(trace)

    def __call__(self, *_args):
        return next(self.trace)

    def close(self):
        pass


class MemoryDatabase:
    """Persistence boundary double: capture rows and satisfy real sink name lookups."""
    def __init__(self):
        self.rows = {}
        self.updates = []

    def insert(self, table, rows):
        single = isinstance(rows, dict)
        result = []
        for row in ([rows] if single else rows):
            copied = json.loads(json.dumps(row))
            copied.setdefault('id', f'{table}-{len(self.rows.get(table, [])) + 1}')
            self.rows.setdefault(table, []).append(copied)
            result.append(copied)
        return result[0] if single else result

    def update(self, table, patch, **filters):
        self.updates.append({'table': table, 'patch': patch, 'filters': filters})
        return []

    def select(self, table, **_filters):
        if table == 'clients':
            return [{'id': 'harness-client', 'name': 'Ryan', 'coaches': {'name': 'Tristan'}}]
        if table == 'program_days':
            return [{'id': 'harness-day', 'title': 'Curl replay', 'day_number': 1}]
        raise ValueError(f'unexpected lookup: {table}')


def run_scenario(name, trace, expected, planned, output):
    database = MemoryDatabase()
    sink = SessionSink('harness-client', 'harness-day', [
        {'exercise_key': 'bicep_curl', 'name': 'Bicep curls', 'sets': 1,
         'reps': planned, 'supported': True}], f'bicep curls:{planned}', db=database)
    events = []
    # Only replace external pose acquisition and database I/O. All business logic is real.
    with patch.object(pipeline, 'Pose', return_value=RecordedPose(trace)), \
         patch.object(session_sink, 'OUT_DIR', output / 'sessions'):
        pipe = pipeline.FramePipeline(None, trigger='none')
        perception = Perception(Config(plan=f'bicep curls:{planned}', announce=False),
                                pipe=pipe, clip_s=lambda _text: None, t0=0)
        perception.on_event(events.append)
        perception.on_event(sink.on_event)
        sink.start()
        try:
            for index in range(len(trace)):
                perception.process_frame(np.zeros((288, 288, 3), dtype=np.uint8),
                                         t_recv=index / FPS, t_ms=index * 100)
            view = sink.finish('harness-trace-end')
        finally:
            perception.close()
    reps = [event for event in events if event['type'] == 'rep']
    faults = [event for event in events if event['type'] == 'fault']
    completed = view['exercises'][0]['sets'][0]['completed_reps']
    persisted_reps = database.rows.get('reps', [])
    muscles = {row['muscle']: row for row in view['muscles']}
    expected_quality = round(.7 + .3 * min(expected / planned, 1), 3) if expected else 0
    checks = {
        'rep_count': len(reps) == expected,
        'rep_sequence': [r['n'] for r in reps] == list(range(1, expected + 1)),
        'exercise_key': all(r.get('exercise_key') == 'bicep_curl' for r in reps),
        'turning_precedes_rep': all(r['turning_t'] < r['t'] for r in reps),
        'no_untrained_curl_fault_classifier': not faults,
        'sink_completed': completed == expected,
        'persisted_reps': len(persisted_reps) == expected,
        'persisted_faults': all(r['faults'] == [] for r in persisted_reps),
        'all_muscles': len(view['muscles']) == MUSCLE_COUNT,
        'biceps_quality': muscles['biceps']['score'] == expected_quality,
        'biceps_coverage': muscles['biceps']['coverage'] == ('primary' if expected else 'none'),
        'untrained_quads': muscles['quads']['color'] == 'gray',
        'session_closed': len(database.updates) == 1 and bool(view['session']['ended_at']),
        'persisted_muscles': len(database.rows.get('muscle_scores', [])) == MUSCLE_COUNT,
        'session_view_written': sink.view_path is not None and sink.view_path.is_file(),
    }
    result = {'scenario': name, 'mode': 'synthetic-landmarks', 'frames': len(trace),
              'expected_reps': expected, 'actual_reps': len(reps), 'faults': faults,
              'checks': checks, 'passed': all(checks.values()), 'session_view': view,
              'events': events, 'persisted_rows': database.rows}
    (output / f'{name}.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def run(output, video_smoke=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with redirect_stdout(sys.stderr):
        results = [run_scenario(name, *args, output) for name, args in scenarios().items()]
    report = {'mode': 'synthetic-landmarks', 'device_validated': False, 'fps': FPS,
              'boundaries_replaced': ['camera/MediaPipe pose acquisition', 'Supabase database I/O'],
              'real_components': ['FramePipeline', 'CurlCounter', 'Perception', 'Session',
                                  'SessionSink', 'muscle_scores'],
              'passed': all(result['passed'] for result in results),
              'scenarios': [{key: value for key, value in result.items()
                             if key not in ('events', 'session_view', 'persisted_rows')}
                            for result in results]}
    if video_smoke is not None:
        from scripts.harness.replay_video import run_video_smoke
        with redirect_stdout(sys.stderr):
            report['video_smoke'] = run_video_smoke(video_smoke, output)
        report['passed'] = report['passed'] and report['video_smoke']['status'] != 'failed'
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/tmp/harness/replay')
    parser.add_argument('--video-smoke', type=Path, nargs='?',
                        const=ROOT / 'data/tmp/mac_handoff/segments/run3_squats.mp4',
                        help='also run real squat video through MediaPipe (first 30 seconds)')
    args = parser.parse_args()
    report = run(args.output, args.video_smoke)
    print(json.dumps(report, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
