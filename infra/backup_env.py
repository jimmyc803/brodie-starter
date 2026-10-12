#!/usr/bin/env python3
"""Create the root-readable environment file consumed by the backup unit."""
import os
from pathlib import Path
import shlex


ALLOWED = {'SUPABASE_DB_URL', 'BACKUP_BUCKET', 'AWS_DEFAULT_REGION'}


def write_backup_env(source=Path('/etc/brodie/env'), target=Path('/etc/brodie/backup-env')):
    entries = {}
    for line in source.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        values = shlex.split(line, comments=False)
        if len(values) != 1 or '=' not in values[0]:
            raise ValueError('Invalid systemd environment assignment')
        key, value = values[0].split('=', 1)
        if key in ALLOWED:
            entries[key] = value
    if not all(entries.get(key) for key in ('SUPABASE_DB_URL', 'BACKUP_BUCKET')):
        raise ValueError('Backup database and bucket settings required')
    temporary = target.with_name(target.name + '.new')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        for key, value in sorted(entries.items()):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            stream.write(f'{key}="{escaped}"\n')
    os.replace(temporary, target)


if __name__ == '__main__':
    write_backup_env()
