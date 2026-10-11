# Data contract

| File | What it is |
|---|---|
| `db/schema.sql` | Supabase tables (the team CONTRACT block). Already applied to project `beat-muse`. |
| `db/seed.sql` | Demo rows: coach Tristan, client Ryan, Day 1, one active assignment. Applied. |
| `db/fixtures/sample_session.json` | One finished session in the **session view** shape (what `GET /api/session/[token]` returns). Build the recap page and image against it. |
| `shared/muscles.json` | Exercise key to muscles, 15 muscle labels with front/back view, Brodie plan names, the scoring rule and hex colors. |
| `shared/scoring.py` | The rule in Python. The worker uses it, so stored `muscle_scores` always match. |

**Scoring, in words.** Per exercise: clean = reps with no faults divided by reps completed; completion = reps completed over
planned, capped at 1; dropoff = how much the clean rate fell from the first set to the last. Quality = 0.5 clean + 0.3 completion
+ 0.2 (1 - dropoff). Per muscle: weighted average of quality over exercises that hit it (primary 1, secondary 0.5). Green at
0.75 and up, yellow at 0.5 and up, red below. A muscle no exercise hit is gray, "not trained this session". `muscle_scores`
has one row per muscle per session (15 rows), gray ones included.

**Links.** `/r/<sessions.share_token>` client recap, `/c/<coaches.share_token>` coach dashboard. RLS is on with no policies:
read with the service role key in server code only.

**Ended early.** A caller who hangs up mid-plan still gets a session (`ended_at` set). Sets never reached have
`completed_reps = 0` and no reps; an exercise with 0 completed reps hits no muscle (gray). Sets filled in by hand later
(a web form, if built) should not change `muscle_scores`: nobody watched the form.

**Fault labels** are Brodie's raw strings. The friendly text is `cue` in `src/rtcoach/cues.json` (`squats - knees over toes`
says "Hips back"). Lunge labels start with `alternating forward lunges - ` (see `fault_prefix` in muscles.json).

**Checks.** `python scripts/check_contract.py`; `python scripts/make_sample_session.py` regenerates the fixture;
`python scripts/seed_sample_sql.py` prints SQL that loads it.

**Before the demo.** Run `set -a && source .env.local && set +a && python scripts/preflight.py` (venv active) right before
recording: env, files, the Supabase plan, the recap card, a real session save (deleted again; `--keep` keeps it), a LiveKit
loopback of the card (`--skip-livekit` skips it) and the worker import. Record only if no row says FAIL (WARN is fine).
