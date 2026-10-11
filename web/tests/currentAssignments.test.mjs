import assert from 'node:assert/strict';
import test from 'node:test';
import { currentAssignments } from '../lib/currentAssignments.ts';

const clients = [{ id: 'ryan', name: 'Ryan' }, { id: 'new', name: 'New client' }];
const days = [{ id: 'one', label: 'Strength · Day 1' }, { id: 'two', label: 'Strength · Day 2' }];
const assignment = (program_day_id, assigned_at, active = true) => ({ client_id: 'ryan', program_day_id, assigned_at, active });

test('shows newest active assignment independent of response order and unassigned clients', () => {
  const result = currentAssignments(clients, days, [assignment('one', '2026-10-10T12:00:00Z'), assignment('two', '2026-10-11T12:00:00Z'), assignment('one', '2026-10-12T12:00:00Z', false)]);
  assert.deepEqual(result, [{ id: 'ryan', name: 'Ryan', assignment: 'Strength · Day 2' }, { id: 'new', name: 'New client', assignment: 'No active assignment' }]);
});
test('never exposes foreign client or day details, including malformed assignments', () => {
  const result = currentAssignments(clients, days, [null, {}, assignment('one', 'invalid'), { ...assignment('two', '2026-10-12T12:00:00Z'), client_id: 'foreign' }, assignment('private-day', '2026-10-11T12:00:00Z')]);
  assert.equal(result[0].assignment, 'Assigned day unavailable');
  assert.equal(result.length, 2);
  assert.ok(!JSON.stringify(result).includes('private-day'));
  assert.ok(!JSON.stringify(result).includes('foreign'));
});
