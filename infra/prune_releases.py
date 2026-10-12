#!/usr/bin/env python3
"""Retain five completed releases, always protecting current and rollback."""
from pathlib import Path
import re
import shutil


def prune(base, previous):
    base = base.resolve()
    current = (base / 'current').resolve()
    releases = [path for path in (base / 'releases').iterdir()
                if not path.is_symlink() and re.fullmatch('[0-9a-f]{40}', path.name)
                and (path / '.release-ready').is_file()]
    releases.sort(key=lambda path: (path / '.release-ready').stat().st_mtime_ns, reverse=True)
    keep = {path for path in releases if path == current or path.name == previous}
    for path in releases:
        if len(keep) < 5:
            keep.add(path)
    for path in releases:
        if path not in keep:
            shutil.rmtree(path)


if __name__ == '__main__':
    record = Path('/var/lib/brodie/previous-sha')
    prune(Path('/opt/brodie'), record.read_text().strip() if record.exists() else '')
