"""Real curl -> perception -> session -> persistence/scoring path, without network."""
import json
from pathlib import Path
import subprocess
import sys

from scripts.harness.replay import run


def test_replay_integrates_real_counter_events_sink_and_scores(tmp_path):
    report = run(tmp_path)
    assert report['passed'], report
    assert report['mode'] == 'synthetic-landmarks'
    assert report['device_validated'] is False
    assert {case['scenario']: case['actual_reps'] for case in report['scenarios']} == {
        'five_complete_two_partial': 5,
        'occlusion_discards_partial': 0,
        'opposite_arm_cannot_complete_locked_rep': 1,
        'threshold_noise': 0,
        'visible_right_arm': 2,
        'missing_pose_discards_partial': 0,
    }
    result = json.loads((tmp_path / 'five_complete_two_partial.json').read_text())
    view = result['session_view']
    assert view['client']['name'] == 'Ryan' and view['coach']['name'] == 'Tristan'
    assert view['exercises'][0]['sets'][0]['completed_reps'] == 5
    biceps = next(m for m in view['muscles'] if m['muscle'] == 'biceps')
    assert biceps == {'muscle': 'biceps', 'score': .914, 'color': 'green', 'coverage': 'primary'}
    rows = result['persisted_rows']
    assert len(rows['sessions']) == len(rows['sets']) == 1
    assert all(rep['set_id'] == rows['sets'][0]['id'] for rep in rows['reps'])
    assert all(muscle['session_id'] == view['session']['id'] for muscle in rows['muscle_scores'])


def test_cli_emits_machine_readable_report_outside_repo_cwd(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/harness/replay.py'
    result = subprocess.run([sys.executable, str(script), '--output', str(tmp_path / 'output')],
                            cwd=tmp_path, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)['passed'] is True


def test_optional_video_missing_assets_are_explicit(tmp_path):
    from scripts.harness.replay_video import run_video_smoke
    report = run_video_smoke(tmp_path / 'missing.mp4', tmp_path)
    assert report['mode'] == 'actual-video'
    assert report['status'] == 'skipped' and report['passed'] is None
    assert str(tmp_path / 'missing.mp4') in report['missing']
    assert report['curl_device_validated'] is False
