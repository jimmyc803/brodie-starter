#!/usr/bin/env python3
"""Run a command with the root-readable systemd environment, without a shell."""
import os
from pathlib import Path
import shlex
import sys

for line in Path('/etc/brodie/env').read_text().splitlines():
    if not line.strip() or line.lstrip().startswith('#'):
        continue
    values = shlex.split(line, comments=False)
    if len(values) != 1 or '=' not in values[0]:
        raise SystemExit('Invalid /etc/brodie/env assignment')
    key, value = values[0].split('=', 1)
    os.environ[key] = value
os.execvpe(sys.argv[1], sys.argv[1:], os.environ)
