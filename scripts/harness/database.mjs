/** Isolated native PostgreSQL. Applies production SQL verbatim; no cloud credentials. */
import EmbeddedPostgres from 'embedded-postgres';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

async function freePort() {
  const server = createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  return port;
}

export async function createDatabaseHarness({ repoRoot = fileURLToPath(new URL('../../', import.meta.url)) } = {}) {
  const port = await freePort();
  const directory = await mkdtemp(join(tmpdir(), 'brodie-postgres-'));
  const logs = [];
  const postgres = new EmbeddedPostgres({
    databaseDir: join(directory, 'cluster'), user: 'postgres', password: randomBytes(24).toString('hex'),
    port, persistent: false, initdbFlags: ['--locale=C', '--encoding=UTF8'],
    postgresFlags: ['-h', '127.0.0.1', '-k', directory],
    onLog: message => logs.push(String(message)), onError: message => logs.push(String(message)),
  });
  const clients = new Set();
  let stopped = false;
  async function connect({ role } = {}) {
    if (role && !['service_role', 'anon', 'authenticated'].includes(role)) throw new Error('Unknown harness database role');
    const client = postgres.getPgClient();
    await client.connect();
    clients.add(client);
    client.once('end', () => clients.delete(client));
    client.on('error', error => logs.push(`Database connection closed: ${error.message}`));
    await client.query("set statement_timeout = '15s'");
    if (role) await client.query(`set role ${role}`);
    return client;
  }
  async function bounded(promise, milliseconds, label) {
    let timer;
    try {
      return await Promise.race([promise, new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} timed out after ${milliseconds}ms`)), milliseconds);
      })]);
    } finally { clearTimeout(timer); }
  }
  async function stop() {
    if (stopped) return;
    stopped = true;
    // embedded-postgres.stop waits for a future exit even when the process has
    // already exited. Own the child shutdown and clear its exit-hook reference.
    const child = postgres.process;
    try {
      if (child && child.exitCode === null && child.signalCode === null) {
        const exited = new Promise(resolve => child.once('exit', resolve));
        child.kill('SIGINT');
        try { await bounded(exited, 3000, 'PostgreSQL graceful shutdown'); }
        catch {
          child.kill('SIGKILL');
          await bounded(exited, 3000, 'PostgreSQL forced shutdown');
        }
      }
      const results = await bounded(Promise.allSettled([...clients].map(client => client.end())), 3000, 'Database client shutdown');
      const failed = results.find(result => result.status === 'rejected');
      if (failed) throw failed.reason;
    } finally {
      postgres.process = undefined;
      await rm(directory, { recursive: true, force: true });
    }
  }
  try {
    await postgres.initialise();
    await bounded(postgres.start(), 15000, 'PostgreSQL startup');
    const client = await connect();
    // Supabase-owned infrastructure only: product tables/functions are never replaced.
    await client.query(`
      create role anon nologin;
      create role authenticated nologin;
      create role service_role nologin bypassrls;
      create schema storage;
      create table storage.buckets (
        id text primary key, name text not null, public boolean not null default false,
        file_size_limit bigint, allowed_mime_types text[]
      );
    `);
    await client.query(await readFile(join(repoRoot, 'db/schema.sql'), 'utf8'));
    await client.query(`
      grant usage on schema public to anon, authenticated, service_role;
      grant select, insert, update, delete on all tables in schema public to anon, authenticated, service_role;
    `);
    await client.query(await readFile(join(repoRoot, 'db/migrations/20261011_program_upload.sql'), 'utf8'));
    return { port, query: (text, values) => client.query(text, values), connect, stop };
  } catch (error) {
    try { await stop(); }
    catch (cleanupError) { logs.push(`Cleanup failed: ${cleanupError.message}`); }
    throw new Error(`Local PostgreSQL setup failed: ${error?.message ?? String(error)}\n${logs.slice(-15).join('\n')}`, { cause: error });
  }
}
