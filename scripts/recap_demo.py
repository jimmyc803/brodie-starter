"""Render the end-of-workout recap PNG from a session view and write it to disk.

    python scripts/recap_demo.py [--view db/fixtures/sample_session.json] [--out data/tmp/recap_demo.png]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from facetime.recap_video import render_recap_png  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--view', default=str(ROOT / 'db' / 'fixtures' / 'sample_session.json'))
    ap.add_argument('--out', default=str(ROOT / 'data' / 'tmp' / 'recap_demo.png'))
    a = ap.parse_args()
    view = json.loads(Path(a.view).read_text())
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(render_recap_png(view))
    print(out)


if __name__ == '__main__':
    main()
