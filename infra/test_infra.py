"""Offline acceptance tests; never contact AWS, Postgres, or systemd."""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InfrastructureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.env = dict(os.environ, PATH=f'{self.path}:/usr/bin:/bin',
                        DISPATCHER_TOKEN='test-token', ALERT_EMAIL='team@example.test',
                        SES_FROM_EMAIL='alerts@example.test', BACKUP_BUCKET='test-backups',
                        SUPABASE_DB_URL='postgresql://test.invalid/db', TRACE=str(self.path / 'trace'))

    def executable(self, name, body):
        path = self.path / name
        path.write_text('#!/bin/bash\nset -eu\n' + body)
        path.chmod(0o755)

    def run_script(self, path, *args):
        return subprocess.run(['bash', str(ROOT / path), *args], env=self.env,
                              capture_output=True, text=True, timeout=10)

    def test_alert_falls_back_only_when_dispatcher_fails(self):
        self.executable('curl', 'exit "${CURL_STATUS:-0}"\n')
        self.executable('aws', 'echo "$1 $2" >> "$TRACE"\n')
        result = self.run_script('infra/alert.sh', 'worker unavailable')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.path / 'trace').exists())
        self.env['CURL_STATUS'] = '22'
        result = self.run_script('infra/alert.sh', 'worker unavailable')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.path / 'trace').read_text().strip(), 'ses send-email')

    def test_backup_never_uploads_failed_dump(self):
        self.executable('pg_dump', 'echo incomplete\nexit 1\n')
        self.executable('aws', 'echo uploaded >> "$TRACE"\n')
        result = self.run_script('infra/backup.sh')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.path / 'trace').exists())

    def test_backup_compresses_and_uses_dated_prefix(self):
        self.executable('pg_dump', 'test -n "$PGDATABASE"\nprintf database\n')
        self.executable('aws', 'gzip -t "$3"\necho "$4" >> "$TRACE"\n')
        result = self.run_script('infra/backup.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex((self.path / 'trace').read_text(),
                         r'^s3://test-backups/\d{4}/\d{2}/\d{2}/\d{8}T\d{6}Z.dump.gz\n$')

    def test_dry_runs_have_no_external_side_effects(self):
        for command in ('aws', 'git', 'sudo', 'systemctl', 'uv', 'psql', 'curl'):
            self.executable(command, 'echo invoked >> "$TRACE"\nexit 99\n')
        for script in ('scripts/deploy.sh', 'infra/provision.sh'):
            result = self.run_script(script, '--dry-run')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('plan', result.stdout.lower())
        self.assertFalse((self.path / 'trace').exists())

    def test_migrations_are_ordered_locked_and_fail_closed(self):
        migrations = self.path / 'db/migrations'
        migrations.mkdir(parents=True)
        (migrations / '002_second.sql').write_text('SELECT 2;')
        (migrations / '001_first.sql').write_text('SELECT 1;')
        self.executable('psql', 'cat > "$TRACE"\nexit "${PSQL_STATUS:-0}"\n')
        import sys
        result = subprocess.run([sys.executable, str(ROOT / 'infra/migrations.py')],
                                cwd=self.path, env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sql = (self.path / 'trace').read_text()
        self.assertLess(sql.index('001_first.sql'), sql.index('002_second.sql'))
        self.assertIn('pg_advisory_lock', sql)
        self.assertIn('sha256 <>', sql)
        self.assertIn('ON_ERROR_STOP=1', (ROOT / 'infra/migrations.py').read_text())
        self.env['PSQL_STATUS'] = '3'
        result = subprocess.run([sys.executable, str(ROOT / 'infra/migrations.py')],
                                cwd=self.path, env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_python_and_cloudwatch_config_parse(self):
        for path in (ROOT / 'infra').glob('*.py'):
            ast.parse(path.read_text(), filename=str(path))
        json.loads((ROOT / 'infra/cloudwatch-agent.json').read_text())


if __name__ == '__main__':
    unittest.main()
