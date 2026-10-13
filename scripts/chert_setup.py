#!/usr/bin/env python3
"""One-shot Chert iMessage setup, run from a laptop with the `beatmuse` AWS profile.

Reads CHERT_MSG_TOKEN (and optional CHERT_TENANT) from SSM, lists the project's lines, and (with --subscribe)
registers the dispatcher webhook for `message.received`. If Chert returns a subscription secret it is written
straight to SSM as CHERT_WEBHOOK_SECRET. Secrets are never printed.

  python3 scripts/chert_setup.py                      # list lines + existing subscriptions
  python3 scripts/chert_setup.py --subscribe          # create the webhook subscription
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://console.trychert.com/api/v1"
VERSION = "2026-05-04"
DEFAULT_URL = "https://3.13.177.157.sslip.io/webhooks/chert"
SECRET_KEYS = ("secret", "signing_secret", "webhook_secret")


def aws(*args: str) -> str:
    cmd = ["aws", "--profile", "beatmuse", "--region", "us-east-2", *args]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def ssm_get(prefix: str, name: str) -> str | None:
    try:
        return aws("ssm", "get-parameter", "--with-decryption", "--name", prefix + name,
                   "--query", "Parameter.Value", "--output", "text").strip()
    except subprocess.CalledProcessError:
        return None


def ssm_put(prefix: str, name: str, value: str) -> None:
    # value goes via stdin-free argv to the local aws process only; never echoed
    aws("ssm", "put-parameter", "--overwrite", "--type", "SecureString", "--name", prefix + name, "--value", value)


def call(method: str, path: str, token: str, tenant: str | None, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if tenant:
        headers["x-chert-tenant"] = tenant
    req = urllib.request.Request(API + path, method=method, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read()[:500].decode(errors="replace")
        sys.exit(f"{method} {path} -> HTTP {e.code}: {detail}")


def find_secret(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in SECRET_KEYS and isinstance(v, str) and v:
                return v
            found = find_secret(v)
            if found:
                return found
    return None


def redact(obj):
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k in SECRET_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subscribe", action="store_true")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--prefix", default="/brodie/challenge/")
    a = ap.parse_args()
    token = ssm_get(a.prefix, "CHERT_MSG_TOKEN")
    if not token:
        sys.exit(f"Missing SSM {a.prefix}CHERT_MSG_TOKEN (the project's signing secret from the Chert console)")
    tenant = ssm_get(a.prefix, "CHERT_TENANT")
    print("lines:", json.dumps(redact(call("GET", "/phone-numbers", token, tenant)), indent=1))
    if not a.subscribe:
        return
    res = call("POST", "/webhook-subscriptions", token, tenant,
               {"url": a.url, "events": ["message.received"], "version": VERSION})
    print("subscription:", json.dumps(redact(res), indent=1))
    secret = find_secret(res)
    if secret:
        ssm_put(a.prefix, "CHERT_WEBHOOK_SECRET", secret)
        print(f"stored {a.prefix}CHERT_WEBHOOK_SECRET")
    else:
        print("No secret in the response: copy the subscription secret from the Chert console into SSM CHERT_WEBHOOK_SECRET.")


if __name__ == "__main__":
    main()
