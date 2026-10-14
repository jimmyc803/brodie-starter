"""The host monitor's Chert-agent health call (infra/monitor.py): a healthy idle agent logs nothing, so silence in
the short window falls back to the latest state line further back instead of texting a false 'unhealthy'
(live 2026-10-13: a quiet evening - caller at the daily limit - emptied the 30-min window)."""
import datetime
import importlib.util
import pathlib

MON = pathlib.Path(__file__).resolve().parents[1] / 'infra' / 'monitor.py'
spec = importlib.util.spec_from_file_location('brodie_monitor', MON)
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

NOW = datetime.datetime(2026, 10, 13, 23, 30, tzinfo=datetime.timezone.utc)


def ago(minutes):
    return NOW - datetime.timedelta(minutes=minutes)


CONNECTED = 'Connected to Chert. Call readiness is reported separately.'
WAITING = '"brodie-challenge" joined a waiting room. Media readiness is not verified.'
LOST = 'Connection to Chert lost: reconnecting…'


def test_chert_status_reads_the_latest_state_line():
    ok = monitor.chert_status(True, [(ago(5), CONNECTED), (ago(4), WAITING)], NOW, 30, 10)
    assert ok == ('ok', 'connected')
    assert monitor.chert_status(False, [], NOW, 30, 10)[0] == 'fail'
    assert monitor.chert_status(True, [], NOW, 30, 10) == (
        'fail', 'no connected or waiting-room state in the last 30 min of the chert-agent journal')
    pending = monitor.chert_status(True, [(ago(20), CONNECTED), (ago(5), LOST)], NOW, 30, 10)
    assert pending[0] == 'pending' and 'reconnecting' in pending[1]
    down = monitor.chert_status(True, [(ago(20), CONNECTED), (ago(15), LOST)], NOW, 30, 10)
    assert down[0] == 'fail' and 'without recovery' in down[1]
    back = monitor.chert_status(True, [(ago(15), LOST), (ago(2), CONNECTED)], NOW, 30, 10)
    assert back == ('ok', 'connected')


def test_idle_agent_is_judged_by_its_latest_state_not_by_silence(monkeypatch):
    calls = []
    def entries(unit, window_min):
        calls.append(window_min)
        return [] if window_min == 30 else [(ago(120), CONNECTED), (ago(119), WAITING)]
    monkeypatch.setattr(monitor, 'unit_active', lambda unit: True)
    monkeypatch.setattr(monitor, 'journal_entries', entries)
    assert monitor.check_chert(NOW) == ('ok', 'connected')
    assert calls == [30, 1440]                                            # the short window first, then the lookback


def test_silence_through_the_whole_lookback_still_fails(monkeypatch):
    monkeypatch.setattr(monitor, 'unit_active', lambda unit: True)
    monkeypatch.setattr(monitor, 'journal_entries', lambda unit, window_min: [])
    status = monitor.check_chert(NOW)
    assert status[0] == 'fail' and '1440 min' in status[1]


def test_an_old_unrecovered_loss_found_in_the_lookback_fails(monkeypatch):
    monkeypatch.setattr(monitor, 'unit_active', lambda unit: True)
    monkeypatch.setattr(monitor, 'journal_entries',
                        lambda unit, window_min: [] if window_min == 30 else [(ago(90), CONNECTED), (ago(80), LOST)])
    status = monitor.check_chert(NOW)
    assert status[0] == 'fail' and 'without recovery' in status[1]


def test_stale_heartbeat_query_spares_job_rows_of_lines_not_in_call():
    import re
    sql = pathlib.Path(MON).read_text()
    m = re.search(r"'stale',\s*\(SELECT.*?\)\)\)\);", sql, re.S)
    assert m is not None
    stale = m.group(0)
    assert "NOT LIKE 'warn:%'" in stale                                   # one-shot markers never count
    assert "worker:%:job" in stale and "state = 'in_call'" in stale       # job rows count only during a call


def test_alert_carries_a_kind_so_two_host_problems_are_two_texts(monkeypatch):
    """Every check used to text under the one kind 'infra', and the dispatcher's dedupe key held only the kind."""
    runs = []
    monkeypatch.setattr(monitor.subprocess, 'run', lambda argv, **kw: runs.append(argv))
    monitor.alert('Chert agent unhealthy: unit is not active', 'chert')
    monitor.alert('Stale application heartbeat records', 'heartbeat')
    assert [argv[-1] for argv in runs] == ['chert', 'heartbeat']
    monitor.alert('no kind given')
    assert runs[-1][-1] == 'infra'


def test_throttled_lets_the_first_through_then_holds_for_the_window(tmp_path):
    kwargs = {'state_dir': str(tmp_path)}
    assert monitor.throttled('chert_token_unset', 24 * 3600, NOW, **kwargs) is False
    assert monitor.throttled('chert_token_unset', 24 * 3600, NOW + datetime.timedelta(hours=10), **kwargs) is True
    assert monitor.throttled('chert_token_unset', 24 * 3600, NOW + datetime.timedelta(hours=25), **kwargs) is False
    assert monitor.throttled('other', 24 * 3600, NOW, **kwargs) is False      # per name, not global
    (tmp_path / 'alert.chert_token_unset').write_text('not a timestamp')      # unreadable stamp: alert, do not hide
    assert monitor.throttled('chert_token_unset', 24 * 3600, NOW, **kwargs) is False


def test_throttled_alerts_every_run_when_the_state_dir_is_unwritable():
    assert monitor.throttled('x', 3600, NOW, state_dir='/nonexistent/brodie') is False
