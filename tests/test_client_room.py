"""Client calls (web /go/<link>) name their room client-<clients.id>-<random>; the worker loads and saves for that client."""
from types import SimpleNamespace

from facetime.worker import call_client_id, client_for_room


def test_client_room_names_carry_the_client_id():
    assert client_for_room('client-1f8c570f-f37f-4c83-bb24-8af8a2c0f259-ab12cd34') == '1f8c570f-f37f-4c83-bb24-8af8a2c0f259'
    assert client_for_room('client-1F8C570F-F37F-4C83-BB24-8AF8A2C0F259-x') == '1f8c570f-f37f-4c83-bb24-8af8a2c0f259'


def test_other_rooms_are_not_client_calls():
    for name in ('jimmy-151012', 'skeleton-1500', 'client-not-a-uuid-x', '', None):
        assert client_for_room(name) is None


def test_room_client_wins_over_demo_client(monkeypatch):
    monkeypatch.setenv('DEMO_CLIENT_ID', 'demo')
    assert call_client_id(SimpleNamespace(client_id='room-client')) == 'room-client'
    assert call_client_id(SimpleNamespace(client_id=None)) == 'demo'
    monkeypatch.delenv('DEMO_CLIENT_ID')
    assert call_client_id(SimpleNamespace(client_id=None)) is None
