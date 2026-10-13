# FaceTime lines (Chert)

Clients FaceTime Brodie. A FaceTime call doesn't tell us who is calling, so the client **reserves a line first**:

1. The coach texts the client their personal link (`/go/<token>`, the "Text it" button on the dashboard).
2. The client taps **Start workout**. That reserves a free line for 3 minutes (`claim_line`) and shows **FaceTime Brodie**,
   a `facetime:` link to that line.
3. The worker on that line takes the reservation when the call arrives (`take_line_claim`), loads the client's assigned day
   and saves the session to them. A caller with no reservation (a walk-in) gets the demo workout, saved to nobody.
4. When the call ends the worker releases the line (`release_line`); it is held for `cooldown_s` (default 180 s) because
   Chert takes a line offline for a few minutes after each call. While every line is busy the page says so and retries.

Tables and functions: `db/migrations/20261012_call_lines.sql`. Web: `web/lib/lines.ts`, `web/app/api/line/[token]`,
`web/components/call/facetime-launcher.tsx`. Worker: `facetime/lines.py` and `BRODIE_LINE` in `facetime/worker.py`.

While `call_lines` has no enabled rows, client pages keep the in-browser call (`/api/call`), as before.

## Add a line

```sql
insert into call_lines (id, facetime_handle) values ('line1', '+1 555 010 0199');   -- or an Apple ID email
-- take it out of rotation: update call_lines set enabled = false where id = 'line1';
```

## Run one worker per line

Each line is one `chert dev` plus one worker with that line's id and Chert dispatch name (`.env.local` exported as usual):

```
BRODIE_LINE=line1 AGENT_NAME=<line1 dispatch name> python -m facetime.worker --voice gemini dev
chert dev --agent <line1 dispatch name>
```

Repeat for `line2` and `line3`. `CALLER_PROBE=1` on a worker logs what Chert tells us about each caller to
`data/tmp/caller_probe.jsonl`. If that includes the caller's number, clients could later skip the reservation.
