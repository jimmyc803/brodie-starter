"""Set (or reset) an admin's password for /admin sign-in, with no email involved.

    export SUPABASE_URL='https://<ref>.supabase.co' SUPABASE_SERVICE_ROLE_KEY='...'
    .venv/bin/python scripts/set_admin_password.py alice@example.com            # generates and prints a password
    .venv/bin/python scripts/set_admin_password.py alice@example.com --password 'chosen one'

The email must already be on admin_allowlist (add it with scripts/seed_admins.py). Creates the Supabase auth user,
pre-confirmed, if it does not exist yet. Prints only the password it set.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request


def _request(method: str, url: str, key: str, body: dict | None = None) -> object:
    req = urllib.request.Request(
        url,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            raw = res.read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{method} {urllib.parse.urlsplit(url).path} failed: {e.code} {e.read().decode()[:300]}")
    return json.loads(raw) if raw else None


def find_user_id(base: str, key: str, email: str) -> str | None:
    page = 1
    while True:
        res = _request("GET", f"{base}/auth/v1/admin/users?page={page}&per_page=200", key)
        users = res.get("users", []) if isinstance(res, dict) else []
        for u in users:
            if (u.get("email") or "").lower() == email:
                return u["id"]
        if len(users) < 200:
            return None
        page += 1


def set_admin_password(base: str, key: str, email: str, password: str) -> str:
    """Returns "created" or "updated". Refuses emails that are not on admin_allowlist."""
    email = email.strip().lower()
    q = urllib.parse.quote(email)
    if not _request("GET", f"{base}/rest/v1/admin_allowlist?select=email&email=ilike.{q}", key):
        raise SystemExit(f"{email} is not on admin_allowlist; add it with scripts/seed_admins.py first")
    uid = find_user_id(base, key, email)
    if uid is None:
        _request("POST", f"{base}/auth/v1/admin/users", key, {"email": email, "password": password, "email_confirm": True})
        return "created"
    _request("PUT", f"{base}/auth/v1/admin/users/{uid}", key, {"password": password, "email_confirm": True})
    return "updated"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("email")
    ap.add_argument("--password", help="password to set (default: generate one)")
    args = ap.parse_args(argv)
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set", file=sys.stderr)
        return 2
    password = args.password or secrets.token_urlsafe(12)
    if len(password) < 8:
        print("password must be at least 8 characters", file=sys.stderr)
        return 2
    action = set_admin_password(base, key, args.email, password)
    print(f"{action} {args.email.strip().lower()}  password: {password}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
