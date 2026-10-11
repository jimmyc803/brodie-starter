# Deployment-wide program safety budgets

Before deploying private-workspace onboarding, apply these SQL files in order through the Supabase SQL editor or your database migration pipeline:

1. `db/schema.sql` (for a new database).
2. `db/migrations/20261011_program_upload.sql`.
3. `db/migrations/20261011_program_budgets.sql`.

The new migration creates `public.program_request_budget` and the service-role-only `consume_program_budget(text)` RPC. No browser role can read or write the budget table or call the function. The function atomically checks and consumes a slot under a transaction-scoped advisory lock, shared by all application processes and serverless instances using this database.

Ceilings apply globally over a rolling hour: **30 new workspaces** and **60 parser starts**. Validating names happens before consuming a workspace slot. Upload authorization and PDF checks happen before consuming a parser slot; a denied parser slot removes the pending private PDF through the existing cleanup path. Failed requests still consume a slot once work starts; slots are not refunded, avoiding races and repeated paid retries. Old slots are removed when the next request for that action is checked.

Missing RPCs, database errors, or unexpected results fail closed and return a safe setup message. The application will not issue a new workspace or call Gemini until the budget check succeeds. Existing coach viewing and assignment are unaffected. An exhausted budget asks users to retry in an hour. These ceilings bound public onboarding and parser costs; they do not identify users or guarantee fairness during abuse.

The same forward migration updates the assignment RPC to accept `pullup`, matching the parser and worker's existing supported exercise key. It preserves ownership validation and client-lock assignment serialization. The migration is safe to reapply: it does not clear budget history or alter existing programs or assignments.
