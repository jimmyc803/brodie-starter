#!/usr/bin/env python3
"""Wait for the dispatcher to report no calls or outstanding claims."""
import json
import os
import sys
import time
import urllib.request


STATES = {'idle', 'in_call', 'offline', 'claimed', 'closed'}


def idle(health):
    if health.get('ok') is not True or health.get('db') in (False, None, 'error', 'down'):
        return False
    lines = health.get('line_states')
    if isinstance(lines, dict):
        if lines and set(lines) <= STATES:
            if not all(type(count) is int and count >= 0 for count in lines.values()):
                return False
            return not (lines.get('in_call', 0) or lines.get('claimed', 0))
        lines = list(lines.values())
    if not isinstance(lines, list):
        return False
    states = [line.get('state') if isinstance(line, dict) else line for line in lines]
    return all(isinstance(state, str) and state in STATES - {'in_call', 'claimed'}
               for state in states)


def hold(force=False):
    value = os.environ.get('DEPLOY_HOLD_MAX_S', '300')
    if not value.isascii() or not value.isdecimal():
        raise SystemExit('DEPLOY_HOLD_MAX_S must be a nonnegative integer')
    deadline = time.monotonic() + int(value)
    while True:
        try:
            timeout = max(0.1, min(5, deadline - time.monotonic()))
            with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=timeout) as response:
                if idle(json.load(response)):
                    return
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if force:
                print('Forced restart: calls may be active or call state unavailable', file=sys.stderr)
                return
            raise SystemExit('Active-call hold expired or call state unavailable; services unchanged. Use --force to override.')
        print('Waiting for idle lines before stopping services', file=sys.stderr)
        time.sleep(min(5, remaining))


if __name__ == '__main__':
    hold('--force' in sys.argv[1:])
