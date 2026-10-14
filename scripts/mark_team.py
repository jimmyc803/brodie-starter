#!/usr/bin/env python3
"""Mark (or unmark) team members by phone number: no daily cap (D-38) and the front of the line (D-43).

Same audited RPC as the admin console's "Mark team" button (ch_admin_set_team), so every change lands in
audit_log with the actor and reason. Numbers are matched on their last 10 digits, because handles are stored as
the caller typed them (ch_norm_handle only trims).

    set -a && source .env.local && set +a
    python scripts/mark_team.py --actor you@example.com 4845876944            # show what would change
    python scripts/mark_team.py --actor you@example.com --apply 4845876944
    python scripts/mark_team.py --actor you@example.com --apply --off 4845876944

Exit 1 if any number matched no registered user (the rest are still applied).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from challenge.store import StoreError, store_from_env  # noqa: E402


def digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def find(url: str, key: str, number: str) -> list[dict]:
    """Registered users whose phone handle ends in this number's last 10 digits."""
    tail = digits(number)[-10:]
    if len(tail) < 10:
        raise SystemExit(f"{number!r}: need at least 10 digits")
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    r = httpx.get(f"{url.rstrip('/')}/rest/v1/client_handles",
                  params={"select": "handle,kind,client_id,clients(id,display_name,is_team,joined_at)",
                          "handle": f"like.*{tail}", "limit": "20"}, headers=h, timeout=10.0)
    if r.status_code >= 300:
        raise StoreError(f"client_handles: {r.status_code} {r.text[:300]}")
    return [row for row in r.json() if (row.get("clients") or {}).get("joined_at")]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("numbers", nargs="+", help="phone numbers (any format; last 10 digits are matched)")
    ap.add_argument("--actor", required=True, help="your admin email, written to audit_log")
    ap.add_argument("--reason", default="team member: line testing", help="audit reason")
    ap.add_argument("--off", action="store_true", help="unmark instead (cap and fair order come back)")
    ap.add_argument("--apply", action="store_true", help="without this, only print what would change")
    a = ap.parse_args()

    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("set SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (set -a && source .env.local && set +a)")
    st = store_from_env()
    want = not a.off
    now = datetime.now(timezone.utc)
    missing = False

    for number in a.numbers:
        rows = find(url, key, number)
        if not rows:
            print(f"{number}: no registered user with that handle")
            missing = True
            continue
        for row in rows:
            c = row["clients"]
            label = f"{number} -> {c['display_name']} ({row['handle']}, {c['id']})"
            if bool(c["is_team"]) == want:
                print(f"{label}: already {'team' if want else 'not team'}")
                continue
            if not a.apply:
                print(f"{label}: would {'mark' if want else 'unmark'} team")
                continue
            r = st.rpc("ch_admin_set_team", {"p_user_id": c["id"], "p_team": want, "p_reason": a.reason,
                                             "p_actor": a.actor, "p_now": now})
            print(f"{label}: {'marked' if want else 'unmarked'} team -> {r}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
