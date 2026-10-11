import exitHook from 'async-exit-hook';
import { writeFile, rename } from 'node:fs/promises';

const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export async function stopChild(child, { graceMs = 3000 } = {}) {
  if (!child.pid) return;
  const signal = name => {
    try { process.kill(-child.pid, name); return true; }
    catch (error) { if (error.code !== 'ESRCH') throw error; return false; }
  };
  // The leader may have exited while descendants still hold the process group.
  if (!signal('SIGTERM')) return;
  for (let elapsed = 0; elapsed < graceMs; elapsed += 100) {
    if (!signal(0)) return;
    await delay(100);
  }
  signal('SIGKILL');
  for (let i = 0; i < 30; i++) {
    if (!signal(0)) return;
    await delay(100);
  }
  throw new Error(`Child process group ${child.pid} did not exit after SIGKILL`);
}

export async function createLifecycle(reportPath, report) {
  const resources = [];
  const pending = new Set();
  let closing, exiting, interrupted;
  let revision = 0, savedRevision = -1;
  async function save() {
    const currentRevision = revision;
    await writeFile(`${reportPath}.tmp`, JSON.stringify(report, null, 2) + '\n');
    await rename(`${reportPath}.tmp`, reportPath);
    savedRevision = currentRevision;
  }
  // Invalidate a prior passing result before any test or long-running setup.
  await save();
  function check() { if (interrupted) throw new Error(`Harness interrupted by ${interrupted}`); }
  async function acquire(create, cleanup) {
    check();
    const tracked = Promise.resolve().then(create).then(value => {
      resources.push(() => cleanup(value));
      return value;
    });
    pending.add(tracked);
    try { const value = await tracked; check(); return value; }
    finally { pending.delete(tracked); }
  }
  function track(cleanup) {
    check(); resources.push(cleanup);
    return () => { const index = resources.indexOf(cleanup); if (index !== -1) resources.splice(index, 1); };
  }
  function finish() {
    if (closing) return closing;
    closing = (async () => {
      const watchdog = setTimeout(() => {
        report.status = interrupted ? 'interrupted' : 'failed';
        report.cleanup_errors = [...(report.cleanup_errors || []), 'Cleanup exceeded 30s deadline'];
        report.finished_at = new Date().toISOString();
        save().finally(() => process.exit(interrupted === 'SIGINT' ? 130 : interrupted ? 143 : 1));
      }, 30000);
      try {
        await Promise.allSettled([...pending]);
        const errors = [];
        for (const cleanup of [...resources].reverse()) {
          try { await cleanup(); } catch (error) { errors.push(error.message); }
        }
        if (errors.length) { report.cleanup_errors = errors; report.status = 'failed'; }
        if (interrupted) { report.status = 'interrupted'; report.signal = interrupted; }
        report.finished_at = new Date().toISOString();
        await save();
      } finally { clearTimeout(watchdog); }
    })();
    return closing;
  }
  function exit() {
    if (exiting) return exiting;
    exiting = (async () => {
      await finish();
      // A signal can arrive while the final report is being written. Flush its
      // revision before exiting; every caller shares this one exit promise.
      while (savedRevision !== revision) await save();
      console.log(`${report.status.toUpperCase()}: ${report.tests.length} checks; ${reportPath}`);
      process.exit(interrupted === 'SIGINT' ? 130 : interrupted ? 143 : report.status === 'passed' ? 0 : 1);
    })();
    return exiting;
  }
  for (const signal of ['SIGINT', 'SIGTERM']) {
    // embedded-postgres installs async-exit-hook, which otherwise exits before
    // our finally block. Remove only that library's handlers, not other listeners.
    if (exitHook.hookedEvents().includes(signal)) exitHook.unhookEvent(signal);
    process.on(signal, () => {
      if (interrupted) return;
      interrupted = signal;
      revision++;
      report.status = 'interrupted';
      report.signal = signal;
      void exit();
    });
  }
  return { acquire, track, check, exit };
}
