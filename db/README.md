# Data contract (v1)

| File | What it is |
|---|---|
| `db/schema.sql` | Supabase tables. Paste into the SQL editor once. |
| `db/fixtures/sample_session.json` | One finished session, nested (`sets[].reps[]`). Build the recap page against this. |
| `shared/muscles.json` | Exercise to muscles, muscle labels and front/back view, the color rule and hex colors. |
| `shared/scoring.py` | The color rule in Python. The worker uses it, so stored scores always match. |

**Pages and tokens.** `/r/<sessions.client_token>` is the client recap. `/c/s/<sessions.coach_token>` is the coach's view of one
session. `/c/<coaches.dashboard_token>` is the coach dashboard. RLS is on with no policies, so read with the service role key
in server code only, never the anon key in the browser.

**Drawing the heat map.** One `muscle_scores` row per trained muscle with `color` already set. A muscle with no row is grey
(`colors.untrained`). `detail.sets` says which sets worked it, `detail.top_fault` is the most common fault label.

**Fault labels** are Brodie's raw strings, like `squats - knees over toes`. The friendly text is `cue` in
`src/rtcoach/cues.json` (that one says "Hips back"). Lunges are named `lunges` but their labels start with
`alternating forward lunges - `.

**Checks.** `python scripts/check_contract.py` checks the fixture against the schema and the rule.
`python scripts/make_sample_session.py` regenerates the fixture.
