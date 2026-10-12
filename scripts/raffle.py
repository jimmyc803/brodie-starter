"""Reproducible raffle draw (SPEC §2): everyone with >= raffle_min_valid_reps valid reps, not banned.

    python scripts/raffle.py --seed <value published before the draw> [--dry-run] [--actor email --reason text]

Same code path as POST /admin/raffle (challenge.dispatcher.admin.run_raffle): eligible user_ids sorted ascending,
winner index = int(sha256(seed + ':' + ','.join(ids)), 16) % n. Without --dry-run the draw is logged to audit_log
(action 'raffle': seed, eligible ids + their sha256, winner); --actor and --reason are then required.
Prints the result as JSON. Exit: 0 ok, 2 usage / store error.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from challenge.dispatcher.admin import run_raffle
from challenge.store import Store, StoreError


def main(argv: list[str] | None = None, store: Store | None = None, now: datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seed", required=True, help="public seed, published before the draw")
    ap.add_argument("--dry-run", action="store_true", help="compute only; write no audit row")
    ap.add_argument("--actor", default=None)
    ap.add_argument("--reason", default=None)
    a = ap.parse_args(argv)
    if not a.dry_run and not (a.actor and a.actor.strip() and a.reason and a.reason.strip()):
        print("raffle: a logged draw needs --actor and --reason (or use --dry-run)", file=sys.stderr)
        return 2
    try:
        if store is None:
            from challenge.store import store_from_env
            store = store_from_env()
        out = run_raffle(store, a.seed, dry_run=a.dry_run, actor=a.actor and a.actor.strip().lower(),
                         reason=a.reason and a.reason.strip(), now=now or datetime.now(UTC))
    except ValueError as e:
        print(f"raffle: {e}", file=sys.stderr)
        return 2
    except StoreError as e:
        print(f"raffle: {e}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
