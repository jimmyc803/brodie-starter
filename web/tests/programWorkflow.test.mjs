import test from 'node:test';
import assert from 'node:assert/strict';
import { uploadProgram, assignProgramDay, MAX_UPLOAD_BYTES, READ_ONLY_MESSAGE } from '../lib/programWorkflow.ts';
const token = 'coach-valid-token-123456789';
const id = '11111111-1111-4111-8111-111111111111';
const day = '22222222-2222-4222-8222-222222222222';
function fixture(overrides = {}) {
  const events = [];
  return { events, store: {
    coach: async t => { events.push('coach'); return t === token ? { id, name: 'Tristan' } : null; },
    upload: async (p, bytes) => { assert.ok(p.startsWith(id + '/')); assert.ok(bytes.length); events.push('upload'); },
    remove: async () => { events.push('remove'); },
    save: async (t, p, program) => { assert.equal(t, token); assert.ok(p.endsWith('.pdf')); assert.equal(program.title, 'Training'); events.push('save'); },
    assign: async (t, client, trainingDay) => { assert.equal(t, token); assert.equal(client, id); assert.equal(trainingDay, day); events.push('assign'); },
    ...overrides,
  } };
}
const pdf = () => new File(['%PDF-1.4\nprogram'], 'workout.pdf', { type: 'application/pdf' });
const parse = async () => ({ title: 'Training', days: [] });
test('upload authenticates before storing, parsing, and transactional save', async () => {
  const { store, events } = fixture();
  const result = await uploadProgram(store, async b => { events.push('parse'); assert.ok(b instanceof Uint8Array); return parse(); }, token, pdf());
  assert.equal(result.ok, true); assert.deepEqual(events, ['coach', 'upload', 'parse', 'save']);
});
test('forged coach token cannot invoke parser or upload', async () => {
  const { store, events } = fixture();
  const result = await uploadProgram(store, () => assert.fail('parser called'), 'wrong-token-123456789', pdf());
  assert.equal(result.ok, false); assert.deepEqual(events, ['coach']);
});
test('missing and disguised or oversized PDFs cause no writes', async () => {
  for (const file of [null, 'not a file', new File(['not a pdf file'], 'fake.pdf'), new File([new Uint8Array(MAX_UPLOAD_BYTES + 1)], 'huge.pdf')]) {
    const { store, events } = fixture();
    assert.equal((await uploadProgram(store, parse, token, file)).ok, false);
    assert.deepEqual(events, ['coach']);
  }
});
test('parse failure removes uploaded PDF and never saves a partial program', async () => {
  const { store, events } = fixture();
  const result = await uploadProgram(store, async () => { throw new Error('secret-key-and-document'); }, token, pdf());
  assert.equal(result.ok, false); assert.ok(!result.message.includes('secret'));
  assert.deepEqual(events, ['coach', 'upload', 'remove']);
});
test('database save failure retains PDF because commit outcome may be unknown', async () => {
  const { store, events } = fixture({ save: async () => { throw new Error('SQL internal'); } });
  assert.equal((await uploadProgram(store, parse, token, pdf())).ok, false);
  assert.deepEqual(events, ['coach', 'upload']);
});
test('failed storage upload never parses or removes another object', async () => {
  const { store, events } = fixture({ upload: async () => { throw new Error('Storage'); } });
  assert.equal((await uploadProgram(store, () => assert.fail('parser called'), token, pdf())).ok, false);
  assert.deepEqual(events, ['coach']);
});
test('cleanup failure is disclosed safely', async () => {
  const { store } = fixture({ remove: async () => { throw new Error('secret'); } });
  const result = await uploadProgram(store, async () => { throw new Error('parser'); }, token, pdf());
  assert.equal(result.ok, false); assert.match(result.message, /could not be removed/); assert.ok(!result.message.includes('secret'));
});
test('assignment rejects absent, malformed IDs and unrecognized coach before RPC', async () => {
  for (const [t, c, d] of [[token, null, day], [token, 'invalid', day], ['wrong-token-123456789', id, day]]) {
    const { store, events } = fixture();
    assert.equal((await assignProgramDay(store, t, c, d)).ok, false);
    assert.deepEqual(events, ['coach']);
  }
});
test('assignment forwards authenticated token and IDs to atomic ownership-checking RPC', async () => {
  const { store, events } = fixture();
  assert.equal((await assignProgramDay(store, token, id, day)).ok, true);
  assert.deepEqual(events, ['coach', 'assign']);
});
test('ownership or transaction refusal returns failure without leaking database errors', async () => {
  const { store } = fixture({ assign: async () => { throw new Error('service-secret'); } });
  const result = await assignProgramDay(store, token, id, day);
  assert.equal(result.ok, false); assert.ok(!result.message.includes('service-secret'));
});
test('uncertain database commit retains PDF and prompts library refresh', async () => {
  const { store, events } = fixture({ save: async () => { throw new Error('secret details'); } });
  const result = await uploadProgram(store, parse, token, pdf());
  assert.equal(result.ok, false); assert.match(result.message, /Refresh/);
  assert.deepEqual(events, ['coach', 'upload']);
  assert.ok(!result.message.includes('secret'));
});
test('the public demo coach link is view-only: no upload, parse or assign', async () => {
  const demo = 'demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c';
  const { store, events } = fixture({ coach: async () => { events.push('coach'); return { id, name: 'Tristan' }; } });
  const up = await uploadProgram(store, async () => { events.push('parse'); return parse(); }, demo, pdf());
  assert.equal(up.ok, false); assert.equal(up.message, READ_ONLY_MESSAGE);
  const as = await assignProgramDay(store, demo, id, day);
  assert.equal(as.ok, false); assert.equal(as.message, READ_ONLY_MESSAGE);
  assert.deepEqual(events, []);
});
