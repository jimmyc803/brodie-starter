"""Offline checks for release safety, retention, and backup isolation."""
import io
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch

from backup_env import write_backup_env
from deploy_hold import hold, idle
from prune_releases import prune


class ReleaseTests(unittest.TestCase):
    def test_idle_requires_healthy_known_line_states(self):
        for lines in ([{'state': 'idle'}, {'state': 'offline'}],
                      {'line-1': 'idle'}, {'idle': 1, 'in_call': 0, 'claimed': 0}):
            self.assertTrue(idle({'ok': True, 'db': True, 'line_states': lines}))
        for lines in ([{'state': 'in_call'}], [{'state': 'claimed'}],
                      {'claimed': 1}, {'in_call': -1}, {'idle': '1'},
                      [{'state': 'unknown'}], [{}], None):
            self.assertFalse(idle({'ok': True, 'db': True, 'line_states': lines}))
        self.assertFalse(idle({'ok': False, 'db': True, 'line_states': []}))
        self.assertFalse(idle({'ok': True, 'db': False, 'line_states': []}))

    @patch.dict(os.environ, {'DEPLOY_HOLD_MAX_S': '0'})
    def test_hold_fails_closed_and_force_overrides(self):
        for payload in (b'{"ok":true,"db":true,"line_states":[{"state":"claimed"}]}',
                        b'not json', b'{}'):
            with patch('deploy_hold.urllib.request.urlopen', return_value=io.BytesIO(payload)):
                with self.assertRaises(SystemExit):
                    hold()
        with patch('deploy_hold.urllib.request.urlopen', side_effect=OSError('unavailable')):
            with self.assertRaises(SystemExit):
                hold()
            hold(force=True)

    @patch.dict(os.environ, {'DEPLOY_HOLD_MAX_S': '10'})
    def test_hold_waits_until_calls_finish(self):
        responses = [io.BytesIO(b'{"ok":true,"db":true,"line_states":{"in_call":1}}'),
                     io.BytesIO(b'{"ok":true,"db":true,"line_states":{"idle":1}}')]
        with patch('deploy_hold.urllib.request.urlopen', side_effect=responses) as request, \
                patch('deploy_hold.time.sleep') as sleep:
            hold()
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    @patch.dict(os.environ, {'DEPLOY_HOLD_MAX_S': '-1'})
    def test_invalid_hold_limit_is_not_forceable(self):
        with self.assertRaises(SystemExit):
            hold(force=True)

    def test_prune_keeps_five_and_protects_current_and_previous(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            releases = base / 'releases'
            releases.mkdir()
            paths = []
            for index in range(8):
                path = releases / f'{index:040x}'
                path.mkdir()
                ready = path / '.release-ready'
                ready.touch()
                os.utime(ready, (index + 1, index + 1))
                paths.append(path)
            (base / 'current').symlink_to(paths[0])
            prune(base, paths[1].name)
            self.assertEqual(set(releases.iterdir()), {paths[i] for i in (0, 1, 5, 6, 7)})

    def test_activation_and_rollback_reuse_existing_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            state = base / 'state'
            state.mkdir()
            commands = base / 'bin'
            commands.mkdir()
            trace = base / 'trace'
            old, new = 'a' * 40, 'b' * 40
            for sha in (old, new):
                release = base / 'releases' / sha
                (release / 'infra/systemd').mkdir(parents=True)
                (release / 'infra/systemd/test.service').touch()
                (release / 'infra/health.sh').write_text('exit 0\n')
                (release / '.venv/bin').mkdir(parents=True)
                (release / '.venv/bin/python').symlink_to(sys.executable)
                (release / '.release-ready').touch()
            (base / 'current').symlink_to(base / 'releases' / old)
            helper = base / 'releases.sh'
            source = Path(__file__).with_name('releases.sh').read_text()
            helper.write_text(source.replace('/var/lib/brodie', str(state)))
            for name in ('systemctl', 'install'):
                command = commands / name
                command.write_text('#!/bin/bash\nprintf "%s %s %s\\n" "$(basename "$0")" "$1" '
                                   '"$(readlink "$BASE/current")" >> "$TRACE"\n')
                command.chmod(0o755)
            # GNU mv -T has the same rename semantics; emulate it on macOS too.
            command = commands / 'mv'
            command.write_text(f'#!{sys.executable}\nimport os, sys\nos.replace(sys.argv[-2], sys.argv[-1])\n')
            command.chmod(0o755)
            command = ['bash', '-euc', 'source "$1"; release_base=$BASE; '
                       'validate_release "$2"; activate_release "$2" "$3"',
                       'test', str(helper)]
            env = dict(os.environ, BASE=str(base), TRACE=str(trace),
                       PATH=str(commands) + os.pathsep + os.environ['PATH'])
            for target, previous in ((new, old), (old, new)):
                result = subprocess.run(command + [target, previous], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((base / 'current').resolve(), base / 'releases' / target)
                self.assertEqual((state / 'previous-sha').read_text().strip(), previous)
                self.assertEqual((state / 'deployed-sha').read_text().strip(), target)
            events = trace.read_text().splitlines()
            self.assertEqual(events[0], f'systemctl stop {base}/releases/{old}')
            self.assertEqual(events[1], f'install -m {base}/releases/{new}')
            self.assertEqual(events[3], f'systemctl enable {base}/releases/{new}')

    def test_backup_environment_excludes_application_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'env'
            target = Path(directory) / 'backup-env'
            source.write_text('SUPABASE_DB_URL="postgres://test/db"\nBACKUP_BUCKET="backups"\n'
                              'DISPATCHER_TOKEN="never-copy"\nGEMINI_API_KEY="never-copy"\n')
            write_backup_env(source, target)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(target.read_text(),
                             'BACKUP_BUCKET="backups"\nSUPABASE_DB_URL="postgres://test/db"\n')
            source.write_text('BACKUP_BUCKET="backups"\n')
            with self.assertRaises(ValueError):
                write_backup_env(source, target)
            self.assertIn('SUPABASE_DB_URL', target.read_text())


if __name__ == '__main__':
    unittest.main()
