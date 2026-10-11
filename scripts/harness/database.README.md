# Local SQL harness

`node --test scripts/harness/database.test.mjs` runs a disposable native PostgreSQL
cluster with `pgcrypto`. Install the harness's npm dependencies first. No Docker,
Supabase project, environment file, or cloud credentials are needed. Run as your
normal OS user; PostgreSQL does not support running as root.

The harness applies `db/schema.sql` and
`db/migrations/20261011_program_upload.sql` unchanged. It creates only the
Supabase infrastructure that those files depend on: three roles and the
`storage.buckets` metadata table. It grants the normal table privileges so RLS
is actually exercised; an anonymous SELECT must return no rows.

The regression runs `db/tests/program_upload.sql` and tests both RPC permissions
and two genuinely overlapping assignment transactions. It observes the second
connection waiting for a PostgreSQL lock before releasing the first transaction,
then checks there is exactly one active assignment, pointing at the second day.

`createDatabaseHarness({repoRoot})` returns `query(sql, parameters)`,
`connect({role})`, `port`, and `stop()`. Query results are native node-postgres
results. `query` uses the setup superuser. `connect` optionally assumes `anon`,
`authenticated`, or `service_role`, and its caller should call `end()` on the
returned client. Always call `stop()` in a `finally` block. The server binds
127.0.0.1, uses a random local password, and deletes its temporary cluster.

This verifies PostgreSQL transactions, constraints, RLS and production RPCs. It
does not verify the hosted Supabase gateway, Storage file service, project
configuration, network, or production credentials. HTTP service emulation belongs
to the separate browser harness, not this SQL layer.

Shutdown also handles a server terminated by another process: it checks the child
exit state, allows 3 seconds for graceful shutdown, then 3 seconds for forced
shutdown. Client shutdown is bounded at 3 seconds, and server startup at 15
seconds. The harness clears the pinned embedded-postgres child's exit-hook
reference itself because that dependency otherwise waits forever for an exit
event that already occurred. Tests exercise external termination and failed
schema setup as well as normal cleanup.
