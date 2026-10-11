# Program upload and assignment

Open `/c/<coaches.share_token>/program`. This is a bearer-link capability: keep the coach link private. The server checks the token for every read/action; the database RPC independently validates ownership before mutations.

## Setup

1. Apply `db/schema.sql`, then **`db/migrations/20261011_program_upload.sql`** in Supabase's SQL editor. The migration creates a private `programs` bucket and service-role-only transaction functions; it does not alter the fixed table contract.
2. Configure `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the dedicated `GEMINI_PARSER_API_KEY` in `web/.env.local` for local development, or Vercel environment settings. Do not use the worker's Gemini token. Never commit these values.
3. Start `cd web && npm run dev`; use the seeded coach share link and append `/program`.
4. Upload `db/fixtures/sample_program.pdf`, review the day cards, then pick a client and day. Unsupported exercises remain visible as manual tracking. Assignment success means the worker can load that day on the next call.

If using a preconfigured local `psql` connection, the exact migration command from the repo root is:

```sh
psql -v ON_ERROR_STOP=1 -f db/migrations/20261011_program_upload.sql
psql -v ON_ERROR_STOP=1 -f db/tests/program_upload.sql
```

The SQL test inserts isolated rows and rolls back. Run it only against a development database. Its checks cover ownership, unchanged prior assignments on refusal, one active assignment after replacement, program rollback, and RPC grants.

## Reliability

Uploads are capped at 3 MB, below Vercel's request limit; Next Server Actions allow 4 MB including multipart overhead. The MIME content starts with `%PDF-`; filenames are never used in storage paths. PDFs are stored under a server-derived coach ID and random UUID. Program + days persist in one database transaction. Parse failures attempt private-object cleanup and explicitly report a failed cleanup.

Assignment locks the client row, verifies the program belongs to that coach, then deactivates old assignments and inserts the new one in one transaction. Failure rolls back; concurrent calls using the RPC serialize. Other writers must use this RPC to preserve that concurrency guarantee.

After any database save attempt fails, the PDF is retained privately because a transport failure after a successful commit is inherently ambiguous; check the refreshed library before retrying. An administrator can remove orphaned private PDFs after verifying no program references their path. Storage cleanup cannot be atomic with Postgres. Never expose the service-role key or create public bucket policies.

## Local checks

```sh
node --experimental-strip-types --test web/tests/programWorkflow.test.mjs
cd web && npx tsc --noEmit && npm run lint
```

Live parsing/storage and SQL integration require configured credentials and the migration. Unit tests exercise the actual workflow using explicit storage/database adapters and never send PDFs to Gemini.
