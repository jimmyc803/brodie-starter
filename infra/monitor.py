#!/usr/bin/env python3
"""Host monitoring; only send success pings after the underlying checks pass."""
import datetime
import json
import os
import subprocess
import urllib.request


def alert(message):
    subprocess.run(['bash', '/opt/brodie/infra/alert.sh', message], check=True)


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=25, check=True).stdout


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

    try:
        command('systemctl', 'is-active', '--quiet', 'brodie-worker', 'chert-agent')
        # Read-only doctor checks the actual Chert registration, without dispatching a job.
        command('runuser', '-u', 'brodie', '--', 'chert', 'doctor')
        ping('HC_WORKER_URL', 'worker active; line registered with Chert')
    except Exception:
        alert('Worker/Chert down or line registration unavailable; missed worker heartbeat')

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
      'stale', (SELECT count(*) FROM heartbeats WHERE at < now() - interval '180 seconds'));
    """
    env = dict(os.environ, PGDATABASE=os.environ['SUPABASE_DB_URL'], PGCONNECT_TIMEOUT='10')
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
