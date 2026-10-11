# Program PDF parser

`parseProgram(pdf: Buffer | Uint8Array)` in `lib/parseProgram.ts` returns
`{ title, days: [{ day_number, title, exercises: [{ exercise_key, name, sets, reps, notes, supported }] }] }`.
It is server-only and reads **only `GEMINI_PARSER_API_KEY`** for authentication.
Set that variable in the repository's ignored `.env.local` for the CLI, and in
Vercel's server environment for deployed routes. Never use a `NEXT_PUBLIC_` variable.
Optional `GEMINI_PARSER_MODEL` defaults to `gemini-2.5-flash`.

Use Node 22.18+ or Node 24:

```sh
cd web
npm ci
npm run test:parser
npm run parse:program -- ../db/fixtures/sample_program.pdf
```

The CLI loads repository and web `.env.local` files without printing credentials.
It prints parsed program JSON on success and exits nonzero with a safe error on failure.
The sample PDF's expected prescription is `db/fixtures/sample_program.expected.json`.
Compare actual output with that prescription; model wording can vary. An API key and
network access are required for the live CLI. Offline tests replace only the HTTP
transport and exercise the real parsing, validation, and request construction.

The parser accepts PDFs up to 10 MiB, uses a 60-second request timeout, requires a
complete structured JSON response, and rejects empty programs, duplicate day
numbers, invalid numbers, and malformed fields. A route may impose a smaller upload
limit. Provider error bodies are never forwarded to callers. Exercise support is
computed using a conservative local name allowlist; unsupported variants, bench
presses, and unknown names remain in the program with a null key and supported=false.
Rep ranges use their lower bound with the range preserved in notes. Timed/AMRAP work
uses reps=0 and is unsupported by the rep-counting worker. Missing set counts default
to 1, explicitly recorded in notes by the extractor.

API references: [Gemini document input](https://ai.google.dev/gemini-api/docs/generate-content/document-processing)
and [structured output](https://ai.google.dev/gemini-api/docs/generate-content/structured-output).
