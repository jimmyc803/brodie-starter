import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, writeFile, rm, access } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(read) {
  for (let i = 0; i < 200; i++) { const result = await read(); if (result) return result; await delay(25); }
  throw new Error('Timed out awaiting subprocess');
}
const alive = pid => { try { process.kill(pid, 0); return true; } catch (error) { if (error.code === 'ESRCH') return false; throw error; } };
for (const signal of ['SIGINT', 'SIGTERM']) {
  test(`${signal} replaces stale report and reaps a detached child plus descendant`, { timeout: 15000 }, async () => {
    const directory = await mkdtemp(path.join(tmpdir(), 'brodie-signal-test-'));
    const reportPath = path.join(directory, 'report.json');
    await writeFile(reportPath, JSON.stringify({ status: 'passed', stale: true }));
    const source = `
      import { createDatabaseHarness } from ${JSON.stringify(path.join(here, 'database.mjs'))};
      import { createLifecycle, stopChild } from ${JSON.stringify(path.join(here, 'lifecycle.mjs'))};
      import { spawn } from 'node:child_process';
      import { mkdtemp, writeFile, rm } from 'node:fs/promises';
      const lifecycle = await createLifecycle(${JSON.stringify(reportPath)}, {status:'running',tests:[]});
      const temp = await lifecycle.acquire(()=>mkdtemp(${JSON.stringify(path.join(directory, 'owned-'))}),value=>rm(value,{recursive:true,force:true}));
      const child = spawn(process.execPath, ['--input-type=module','-e',
        "import {spawn} from 'node:child_process'; const grandchild=spawn(process.execPath,['-e','process.on(\\\"SIGTERM\\\",()=>{});setInterval(()=>{},1000)'],{stdio:'ignore'});process.on('SIGTERM',()=>{});console.log(grandchild.pid);setInterval(()=>{},1000)"
      ], {detached:true,stdio:['ignore','pipe','inherit']});
      lifecycle.track(()=>stopChild(child,{graceMs:100}));
      child.stdout.once('data',async data=>{await writeFile(${JSON.stringify(path.join(directory, 'ready.json'))},JSON.stringify({child:child.pid,grandchild:Number(data),temp}));});
      setInterval(()=>{},1000);
    `;
    const runner = spawn(process.execPath, ['--input-type=module', '-e', source], { stdio: ['ignore', 'ignore', 'pipe'] });
    let stderr = ''; runner.stderr.on('data', data => stderr += data);
    const exited = new Promise(resolve => runner.once('exit', (code, sig) => resolve({ code, sig })));
    let owned;
    try {
      owned = await until(async () => { try { return JSON.parse(await readFile(path.join(directory, 'ready.json'), 'utf8')); } catch { return false; } });
      assert.equal(JSON.parse(await readFile(reportPath)).status, 'running', 'prior pass invalidated before checks');
      runner.kill(signal);
      const result = await exited;
      assert.equal(result.code, signal === 'SIGINT' ? 130 : 143, stderr);
      const report = JSON.parse(await readFile(reportPath));
      assert.equal(report.status, 'interrupted'); assert.equal(report.signal, signal);
      assert.equal(report.stale, undefined); assert.ok(report.finished_at);
      assert.equal(alive(owned.child), false, 'child must be reaped');
      assert.equal(alive(owned.grandchild), false, 'descendant must be killed even if it ignores SIGTERM');
      await assert.rejects(access(owned.temp), { code: 'ENOENT' });
    } finally {
      runner.kill('SIGKILL');
      if (owned) { try { process.kill(-owned.child, 'SIGKILL'); } catch {} }
      await rm(directory, { recursive: true, force: true });
    }
  });
}

test('SIGTERM during final report I/O cannot leave a passing report', { timeout: 15000 }, async () => {
  const directory = await mkdtemp(path.join(tmpdir(), 'brodie-late-signal-test-'));
  const reportPath = path.join(directory, 'report.json');
  const source = `
    import { createDatabaseHarness } from ${JSON.stringify(path.join(here, 'database.mjs'))};
    import { createLifecycle } from ${JSON.stringify(path.join(here, 'lifecycle.mjs'))};
    const report={status:'running',tests:[]};
    const lifecycle=await createLifecycle(${JSON.stringify(reportPath)},report);
    report.status='passed';
    // Widen real filesystem I/O so the signal arrives during finalization.
    report.padding='x'.repeat(30_000_000);
    const done=lifecycle.exit();
    setTimeout(()=>process.kill(process.pid,'SIGTERM'),1);
    await done;
  `;
  const runner = spawn(process.execPath, ['--input-type=module', '-e', source], { stdio: 'ignore' });
  try {
    const code = await new Promise(resolve => runner.once('exit', resolve));
    assert.equal(code, 143);
    const report = JSON.parse(await readFile(reportPath, 'utf8'));
    assert.equal(report.status, 'interrupted');
    assert.equal(report.signal, 'SIGTERM');
    assert.ok(report.finished_at);
  } finally {
    runner.kill('SIGKILL');
    await rm(directory, { recursive: true, force: true });
  }
});
