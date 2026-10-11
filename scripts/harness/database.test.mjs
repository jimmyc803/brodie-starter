import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import { createDatabaseHarness } from './database.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
test('real PostgreSQL enforces upload transactions, ownership, RLS and assignment serialization', async () => {
  const db = await createDatabaseHarness({ repoRoot: root });
  try {
    await db.query(await readFile(new URL('../../db/tests/program_upload.sql', import.meta.url), 'utf8'));
    assert.equal((await db.query('select count(*)::int as n from coaches')).rows[0].n, 0, 'SQL regression must rollback fixtures');
    const coach = (await db.query("insert into coaches(name,share_token) values ('Harness', 'database-harness-coach-token') returning id")).rows[0].id;
    const client = (await db.query("insert into clients(name,coach_id) values ('Harness client',$1) returning id", [coach])).rows[0].id;
    const program = { title: 'Concurrent assignments', days: [1, 2].map(day_number => ({ day_number, title: `Day ${day_number}`, exercises: [{ exercise_key: 'bicep_curl', name: 'Curl', supported: true, sets: 3, reps: 12, notes: '' }] })) };
    const service = await db.connect({ role: 'service_role' });
    const programId = (await service.query('select save_coach_program($1,$2,$3) as id', ['database-harness-coach-token', `${coach}/fixture.pdf`, program])).rows[0].id;
    const days = (await db.query('select id from program_days where program_id=$1 order by day_number', [programId])).rows;
    const anonymous = await db.connect({ role: 'anon' });
    assert.equal((await anonymous.query('select * from coaches')).rowCount, 0, 'RLS hides coach bearer tokens');
    await assert.rejects(anonymous.query('select save_coach_program($1,$2,$3)', ['database-harness-coach-token', `${coach}/fixture.pdf`, program]), /permission denied/);
    await anonymous.end();

    const first = await db.connect({ role: 'service_role' });
    const second = await db.connect({ role: 'service_role' });
    const secondPid = (await second.query('select pg_backend_pid() as pid')).rows[0].pid;
    let pending;
    try {
      await first.query('begin');
      await first.query('select assign_coach_program_day($1,$2,$3)', ['database-harness-coach-token', client, days[0].id]);
      pending = second.query('select assign_coach_program_day($1,$2,$3)', ['database-harness-coach-token', client, days[1].id]);
      // Observe an actual database lock, rather than hoping parallel requests overlap.
      let blocked = false;
      for (let attempt = 0; attempt < 100; attempt++) {
        const state = await db.query('select wait_event_type from pg_stat_activity where pid=$1', [secondPid]);
        if (state.rows[0]?.wait_event_type === 'Lock') { blocked = true; break; }
        await new Promise(resolve => setTimeout(resolve, 20));
      }
      assert.ok(blocked, 'second assignment must wait for the first transaction');
      await first.query('commit');
      await pending;
      const active = (await db.query('select program_day_id from assignments where client_id=$1 and active', [client])).rows;
      assert.deepEqual(active, [{ program_day_id: days[1].id }]);
      assert.equal((await db.query('select count(*)::int as n from assignments where client_id=$1', [client])).rows[0].n, 2);
    } finally {
      await first.query('rollback');
      if (pending) await pending;
      await first.end();
      await second.end();
      await service.end();
    }
    assert.equal((await db.query("select public from storage.buckets where id='programs'")).rows[0].public, false);
  } finally { await db.stop(); }
});

test('cleanup finishes after PostgreSQL was externally terminated', { timeout: 10000 }, async () => {
  const db = await createDatabaseHarness({ repoRoot: root });
  try {
    const pid = Number((await db.query("select split_part(pg_read_file('postmaster.pid'), E'\\n', 1) as pid")).rows[0].pid);
    process.kill(pid, 'SIGINT');
    await new Promise(resolve => setTimeout(resolve, 100));
  } finally { await db.stop(); }
});

test('failed schema setup preserves the original error and cleans up', { timeout: 10000 }, async () => {
  await assert.rejects(createDatabaseHarness({ repoRoot: '/nonexistent-brodie-harness-fixture' }), /ENOENT/);
});
