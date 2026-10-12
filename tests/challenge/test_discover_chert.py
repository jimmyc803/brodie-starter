import asyncio, importlib.util, json
from pathlib import Path
from types import SimpleNamespace as NS

spec = importlib.util.spec_from_file_location('discover_chert', Path(__file__).resolve().parents[2] / 'scripts' / 'discover_chert.py')
dc = importlib.util.module_from_spec(spec); spec.loader.exec_module(dc)


class FakeRoom:
    def __init__(self): self.h = {}
    def on(self, ev, fn): self.h[ev] = fn


def lines(p): return [json.loads(l) for l in Path(p).read_text().splitlines()]


class FakeStream:
    def __init__(self, gate): self.gate = gate; self.closed = False
    def __aiter__(self): return self
    async def __anext__(self):
        await self.gate.wait(); return object()
    async def aclose(self): self.closed = True


def test_payload_and_timing(tmp_path):
    ticks = iter([100.0, 100.5, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0])
    log = dc.DiscoveryLog(tmp_path / 'd' / 'x.jsonl', clock=lambda: next(ticks))
    md = json.dumps({'chert_call': {'handle': '+15551234567', 'id': 'c1'}})
    log.job('J1', 'room1', md)
    p = NS(identity='chert-c1', name='Caller', kind='STANDARD', attributes={'a': '1'}, metadata='{"x": 2}')
    log.connected('room1', [p])

    async def run():
        room = FakeRoom(); gate = asyncio.Event(); streams = []
        def mk(track): streams.append(FakeStream(gate)); return streams[-1]
        h = dc.attach(room, log, make_stream=mk)
        h['sub'](NS(kind='KIND_AUDIO'), None, p); h['sub'](NS(kind='KIND_AUDIO'), None, p)
        await asyncio.sleep(0)
        assert 'first_frame' not in [x['ev'] for x in lines(tmp_path / 'd' / 'x.jsonl')]   # subscription alone is not a frame
        gate.set(); await asyncio.gather(*h['tasks'])
        assert len(streams) == 1 and streams[0].closed
        h['left'](p); h['disc']('CLIENT_INITIATED')
        assert set(room.h) >= {'participant_connected', 'disconnected', 'track_subscribed'}
    asyncio.run(run())
    r = lines(tmp_path / 'd' / 'x.jsonl')
    assert [x['ev'] for x in r] == ['job', 'connected', 'first_frame', 'participant_disconnected', 'room_disconnected']
    assert r[0]['chert_call'] == {'handle': '+15551234567', 'id': 'c1'}
    assert r[1]['participants'][0]['attributes'] == {'a': '1'} and r[1]['participants'][0]['metadata'] == {'x': 2}
    assert [x['dt'] for x in r] == [0.5, 1.0, 2.0, 3.0, 4.0]


def test_nonjson_metadata(tmp_path):
    log = dc.DiscoveryLog(tmp_path / 'y.jsonl')
    rec = log.job('J', 'r', 'not json')
    assert rec['metadata'] == {'raw': 'not json'} and rec['chert_call'] is None
