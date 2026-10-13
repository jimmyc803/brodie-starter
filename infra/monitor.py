#!/usr/bin/env python3
"""Host monitoring; only send success pings after the underlying checks pass."""
import datetime
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pgenv import pg_env  # noqa: E402


def alert(message):
    subprocess.run(['bash', '/opt/brodie/current/infra/alert.sh', message], check=True)


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=25, check=True).stdout


# Chert agent health from its unit + journal. `chert doctor` is not usable here: it exits 3 while the agent is
# connected (line_free fails because the session IS connected; livekit vars are not in the doctor's env).
CHERT_UNIT = 'chert-agent'
CHERT_HEALTHY = ('connected to chert', 'joined a waiting room', 'call accepted', 'call ended', 'reconnected')
CHERT_LOST = 'connection to chert lost'
CHERT_EXPIRED = 'session expired'


def chert_event(message):
    """'expired' | 'lost' | 'healthy' | None for one chert-agent journal line."""
    text = message.lower()
    if CHERT_EXPIRED in text:
        return 'expired'
    if CHERT_LOST in text:
        return 'lost'
    if any(marker in text for marker in CHERT_HEALTHY):
        return 'healthy'
    return None


def chert_status(active, entries, now, window_min, lost_grace_min):
    """('ok' | 'pending' | 'fail', detail). entries: [(datetime, message)] from the last window_min minutes.
    ok: unit active and the latest Chert state line is connected / waiting room / call. pending: the connection was
    lost less than lost_grace_min ago (Chert reconnects on its own). fail: unit inactive, session expired, lost for
    longer than the grace, or no connected/waiting-room line at all in the window."""
    if not active:
        return 'fail', CHERT_UNIT + ' unit is not active'
    last, lost_since = None, None
    for at, message in sorted(entries, key=lambda e: e[0]):
        kind = chert_event(message)
        if kind is None:
            continue
        if kind == 'lost':
            lost_since = lost_since or at
        else:
            lost_since = None
        last = kind
    if last is None:
        return 'fail', f'no connected or waiting-room state in the last {window_min} min of the {CHERT_UNIT} journal'
    if last == 'expired':
        return 'fail', 'Chert session expired; device login needed'
    if last == 'lost':
        minutes = (now - lost_since).total_seconds() / 60
        if minutes > lost_grace_min:
            return 'fail', f'Connection to Chert lost {int(minutes)} min ago without recovery'
        return 'pending', f'Connection to Chert lost {int(minutes)} min ago; reconnecting'
    return 'ok', 'connected'


def journal_entries(unit, window_min):
    """[(datetime, message)] for unit's journal over the last window_min minutes (journalctl -o json)."""
    out = command('journalctl', '-u', unit, '--since', f'-{int(window_min)}min', '-o', 'json', '--no-pager')
    entries = []
    for line in out.splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        message = record.get('MESSAGE')
        if isinstance(message, list):  # journald encodes non-UTF-8 messages as a byte array
            message = bytes(message).decode('utf-8', 'replace')
        if not isinstance(message, str) or '__REALTIME_TIMESTAMP' not in record:
            continue
        at = datetime.datetime.fromtimestamp(int(record['__REALTIME_TIMESTAMP']) / 1e6, datetime.timezone.utc)
        entries.append((at, message))
    return entries


def unit_active(unit):
    return subprocess.run(['systemctl', 'is-active', '--quiet', unit], timeout=25).returncode == 0


def check_chert(now=None):
    window_min = int(os.environ.get('CHERT_JOURNAL_WINDOW_MIN', '30'))
    lookback_min = int(os.environ.get('CHERT_JOURNAL_LOOKBACK_MIN', '1440'))
    lost_grace_min = int(os.environ.get('CHERT_LOST_ALERT_MIN', '10'))
    now = now or datetime.datetime.now(datetime.timezone.utc)
    active = unit_active(CHERT_UNIT)
    entries = journal_entries(CHERT_UNIT, window_min) if active else []
    status = chert_status(active, entries, now, window_min, lost_grace_min)
    if active and status[0] == 'fail' and status[1].startswith('no connected'):
        # A healthy idle agent logs nothing (live 2026-10-13: a quiet evening emptied the 30-min window and texted
        # a false 'unhealthy'): judge from its latest state line further back before calling silence a failure.
        entries = journal_entries(CHERT_UNIT, lookback_min)
        status = chert_status(active, entries, now, lookback_min, lost_grace_min)
    return status


def ping(name, body):
    url = os.environ.get(name)
    if url:
        request = urllib.request.Request(url, data=body.encode(), method='POST')
        with urllib.request.urlopen(request, timeout=10) as response:
            response.read()


def main():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=10) as response:
            health = json.load(response)
        if health.get('ok') is not True or health.get('db') in (False, None, 'error', 'down'):
            raise ValueError('Dispatcher health unhealthy')
        ping('HC_DISPATCHER_URL', 'dispatcher and database healthy')
    except Exception:
        alert('Dispatcher erroring or missed dispatcher heartbeat')

    worker_ok = unit_active('brodie-worker')
    if not worker_ok:
        alert('Worker down: brodie-worker unit is not active')
    try:
        chert, detail = check_chert()
    except Exception as exc:  # journal unreadable: report it, never pass silently
        chert, detail = 'fail', f'chert check failed: {exc}'
    if chert == 'fail':
        alert('Chert agent unhealthy: ' + detail)
    elif chert == 'pending':
        print('chert: ' + detail, flush=True)
    if worker_ok and chert == 'ok':
        ping('HC_WORKER_URL', 'worker active; Chert agent connected')

    for unit in ('brodie-worker', 'chert-agent', 'brodie-dispatcher'):
        count = int(command('systemctl', 'show', unit, '--property=NRestarts', '--value').strip())
        path = '/var/lib/brodie/' + unit + '.restarts'
        try:
            with open(path) as stream:
                previous = int(stream.read())
        except FileNotFoundError:
            previous = 0
        if count - previous >= 3:
            alert(unit + ' crash loop: at least three restarts in one minute')
        with open(path, 'w') as stream:
            stream.write(str(count))

    query = """
    SELECT json_build_object(
      'stuck', (SELECT count(*) FROM line_state WHERE
        (state = 'claimed' AND claimed_until < now() - interval '120 seconds') OR
        (state = 'offline' AND offline_until < now() - interval '120 seconds') OR
        (state = 'in_call' AND in_call_since < now() - make_interval(secs =>
          COALESCE((SELECT (value::text)::int FROM competition_config WHERE key='call_count_s'),180) +
          COALESCE((SELECT (value::text)::int FROM competition_config WHERE key='call_reveal_s'),15) +
          COALESCE((SELECT (value::text)::int FROM competition_config WHERE key='in_call_timeout_extra_s'),60) + 120))),
      'failed', (SELECT count(*) FROM messages WHERE direction='out' AND status='failed'
        AND created_at > now() - interval '5 minutes'),
      'stale', (SELECT count(*) FROM heartbeats h WHERE h.at < now() - interval '180 seconds'
        AND h.component NOT LIKE 'warn:%'
        AND (h.component NOT LIKE 'worker:%:job' OR EXISTS (
          SELECT 1 FROM line_state ls WHERE ls.line_id = split_part(h.component, ':', 2)
            AND ls.state = 'in_call'))));
    """
    # stale: the contractual rows only. A 'worker:<line>:job' row is per-call bookkeeping that lingers after the
    # call (live 2026-10-13: a cut-off call plus the caller's daily limit left one aging all evening, texting
    # 'Stale application heartbeat records' every minute); a wedged job DURING a call still counts, and also
    # surfaces through the aggregate 'worker' row (only healthy beats refresh it) and the line_state stuck check.
    # 'warn:*' rows are one-shot markers, never refreshed.
    env = pg_env(os.environ['SUPABASE_DB_URL'])
    result = subprocess.run(['psql', '-X', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query],
                            env=env, capture_output=True, text=True, timeout=25, check=True)
    status = json.loads(result.stdout)
    if status['stuck']:
        alert('line_state stuck past recovery deadline')
    if status['failed'] >= int(os.environ.get('OUTBOUND_FAILURE_ALERT_COUNT', '5')):
        alert('Outbound failure spike over the last five minutes')
    if status['stale']:
        alert('Stale application heartbeat records')
    expiry = os.environ.get('CHERT_TOKEN_EXPIRES_AT')
    if expiry:
        expires = datetime.datetime.fromisoformat(expiry.replace('Z', '+00:00'))
        if expires.tzinfo is None:
            raise ValueError('CHERT_TOKEN_EXPIRES_AT must include a timezone')
        if expires - datetime.datetime.now(datetime.timezone.utc) < datetime.timedelta(hours=24):
            alert('Chert token expires within 24 hours; renew device login')
    else:
        alert('Chert token expiry unknown; configure CHERT_TOKEN_EXPIRES_AT after device login')


if __name__ == '__main__':
    main()
