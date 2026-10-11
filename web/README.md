# web: Brodie for Coaches

Next.js (App Router) + Tailwind + shadcn/ui. Deployed on Vercel with the project root directory set to `web`.

```
cd web
npm install
cp .env.example .env.local   # fill in the Supabase values
npm run dev                  # http://localhost:3000
```

| Route | Page | Owner |
|---|---|---|
| `/r/[token]` | Client recap (`sessions.client_token`) | Jimmy |
| `/c/[token]` | Coach dashboard (`coaches.dashboard_token`) | Jimmy |
| `/c/s/[token]` | Coach view of one session (`sessions.coach_token`) | Jimmy |
| `app/coach/` | Program upload and assign | Ryan |

Database access: `@/lib/supabase/server` only, in server code. The data contract is `db/schema.sql` and `shared/muscles.json`.
