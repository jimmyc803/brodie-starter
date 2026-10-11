# Autonomous local acceptance harness

From the repository root, install once:

```sh
npm ci --prefix web
npm ci --prefix scripts/harness
node scripts/harness/node_modules/playwright/cli.js install chromium
```

Use the project's Python virtualenv (`uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`), then run:

```sh
npm test --prefix scripts/harness
```

Set `HARNESS_PYTHON` to an existing Python environment if needed. Node 22+ and a platform supported by embedded-postgres and Playwright are required. Installation needs network access; execution needs permission to start localhost servers, PostgreSQL and Chromium. No `.env`, cloud credentials, login, running developer server, or camera are required. npm versions that block dependency install scripts may require approving the embedded-postgres platform package's `hydrate-symlinks.js` postinstall.

The command fails nonzero on any failed assertion and writes `.local/harness/report.json`, browser screenshots, browser trace, and process logs. It starts temporary native PostgreSQL with the exact repository schema and migration, checks real RPC ownership/RLS/transaction behavior, runs deterministic curl replay, then starts an isolated copy of the actual Next application and drives its forms with Chromium. The server environment is a small allowlist with fake local keys, and the copy excludes every `.env*` file. Child servers and temporary database/app directories are cleaned up.

Browser acceptance covers the real PDF upload, parser normalization, storage transport, SQL persistence and assignment replacement; invalid/oversized PDFs; provider outage, malformed JSON and invalid-schema storage cleanup without partial database writes; forged provider support claims normalized to manual-only days; DOM-forged cross-coach and manual-day assignments rejected by real server actions and SQL without changing prior assignments; current assignment feedback after reload; real Python HTTP assignment loading after browser assignment/replacement, including curl prescriptions and manual-exercise exclusion; and unknown coach links. Database tests also cover manual-only days, cross-coach writes, roles and concurrent assignments.

Boundaries are explicit: a test-process Node preload substitutes only the external Gemini response, checking that the real PDF bytes and dedicated test parser key reach that boundary. A small localhost Supabase HTTP adapter translates the application's unmodified SDK requests into PostgreSQL using `service_role` and stores uploaded PDF bytes on disk. It is **not** a replacement implementation of the parser, workflow or SQL functions. It does **not** validate real Gemini extraction, hosted Supabase transport/configuration, cloud permissions, video pose estimation, FaceTime or physical-device accuracy. Synthetic landmark replay covers counter behavior; a real clip/device test remains distinct.

The browser uses Next's webpack development server to avoid requiring a production deployment. Production build, lint, parser unit tests and Python unit tests remain separate existing checks. External fetches from the Next runtime are blocked except the deterministic Gemini boundary and loopback HTTP.
