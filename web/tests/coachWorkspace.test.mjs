import test from 'node:test';
import assert from 'node:assert/strict';
import { createCoachWorkspace, createClientForCoach } from '../lib/coachWorkspace.ts';

const token = 'private-coach-valid-token-0001';
const coachId = '11111111-1111-4111-8111-111111111111';
const demoToken = 'demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c';
function fixture(overrides = {}) {
  const events = [];
  const store = {
    coach: async value => { events.push(['coach', value]); return value === token ? { id: coachId, name: 'Tristan' } : null; },
    createCoach: async row => { events.push(['createCoach', row]); },
    createClient: async row => { events.push(['createClient', row]); },
    removeCoach: async id => { events.push(['removeCoach', id]); },
    ...overrides,
  };
  return { store, events };
}
const writes = events => events.filter(([name]) => name !== 'coach');

test('invalid names never create any workspace rows', async () => {
  for (const invalid of [null, undefined, 42, {}, '', '   ', 'a'.repeat(81)]) {
    for (const names of [[invalid, 'Ryan'], ['Tristan', invalid]]) {
      const { store, events } = fixture();
      assert.equal((await createCoachWorkspace(store, ...names)).ok, false);
      assert.deepEqual(events, []);
    }
  }
});

test('workspace creates linked coach and client with independent fresh capability tokens', async () => {
  const { store, events } = fixture();
  const tokens = new Set();
  const ids = new Set();
  for (let i = 0; i < 8; i++) {
    const result = await createCoachWorkspace(store, '  Tristan  ', ' Ryan ');
    assert.equal(result.ok, true);
    const [[coachOperation, coach], [clientOperation, client]] = events.splice(0);
    assert.equal(coachOperation, 'createCoach'); assert.equal(clientOperation, 'createClient');
    assert.equal(coach.name, 'Tristan'); assert.equal(client.name, 'Ryan');
    assert.equal(client.coach_id, coach.id); assert.equal(result.token, coach.share_token);
    for (const row of [coach, client]) {
      assert.match(row.id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      assert.match(row.share_token, /^[0-9a-f]{64}$/);
      assert(!ids.has(row.id)); assert(!tokens.has(row.share_token));
      ids.add(row.id); tokens.add(row.share_token);
    }
  }
});

test('failed client insertion removes only newly-created coach and hides internal details', async () => {
  const { store, events } = fixture({ createClient: async row => { events.push(['createClient', row]); throw Error('private-service-key'); } });
  const result = await createCoachWorkspace(store, 'Tristan', 'Ryan');
  assert.equal(result.ok, false); assert(!result.message.includes('private-service-key'));
  assert.deepEqual(events.map(([operation]) => operation), ['createCoach', 'createClient', 'removeCoach']);
  assert.equal(events[2][1], events[0][1].id);
});

test('cleanup failure is an explicit safe failure, never a successful workspace', async () => {
  const { store } = fixture({ createClient: async () => { throw Error('secret'); }, removeCoach: async () => { throw Error('secret'); } });
  const result = await createCoachWorkspace(store, 'Tristan', 'Ryan');
  assert.equal(result.ok, false); assert.equal(typeof result.message, 'string'); assert(!result.message.includes('secret'));
});

test('unknown, malformed and public demo coach links cannot add clients', async () => {
  for (const value of ['', 'bad', 'unknown-coach-valid-token-0001', demoToken]) {
    const { store, events } = fixture();
    assert.equal((await createClientForCoach(store, value, 'Ryan')).ok, false);
    assert.deepEqual(writes(events), []);
  }
  const { store, events } = fixture({ coach: async () => ({ id: coachId, name: 'Public demo' }) });
  assert.equal((await createClientForCoach(store, demoToken, 'Ryan')).ok, false);
  assert.deepEqual(events, []);
});

test('invalid client name cannot create a row under a valid coach', async () => {
  for (const name of [null, {}, 3, '', '   ', 'x'.repeat(81)]) {
    const { store, events } = fixture();
    assert.equal((await createClientForCoach(store, token, name)).ok, false);
    assert.deepEqual(writes(events), []);
  }
});

test('client creation attaches only to authenticated coach and generates a private token', async () => {
  const { store, events } = fixture();
  assert.equal((await createClientForCoach(store, token, '  Ryan  ')).ok, true);
  const client = events.find(([operation]) => operation === 'createClient')?.[1];
  assert.equal(client.coach_id, coachId); assert.equal(client.name, 'Ryan');
  assert.match(client.share_token, /^[0-9a-f]{64}$/);
  assert.deepEqual(writes(events).map(([operation]) => operation), ['createClient']);
});

test('client store failures return safe failures', async () => {
  for (const overrides of [{ coach: async () => { throw Error('database-secret'); } }, { createClient: async () => { throw Error('database-secret'); } }]) {
    const { store } = fixture(overrides);
    const result = await createClientForCoach(store, token, 'Ryan');
    assert.equal(result.ok, false); assert(!result.message.includes('database-secret'));
  }
});
