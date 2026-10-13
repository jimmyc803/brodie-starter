# Decisions (plain-language summary)

Source of record: `.orch/DECISIONS.md` (internal log). This page explains each decision for people who were not in the room.

## Ground-truth differences from the spec's audit (SPEC section 1)
- The repo already contained untracked files `facetime/annotate_video.py`, `facetime/call_render.py`, `facetime/heatmap_intro.py`; they were left alone (D-01).
- `src/rtcoach/pose.py` tracked only one person; the judge needs two to detect "two people" (D-09).
- The rep counter registers a rep when the person is 15% back up from the bottom, so the finishing lockout is not yet visible at that moment (D-10).
- No fixed depth, knee or hip-line gate existed; the strict judge adds them (see D-15 to D-20).
- Chert's command line has no messaging surface, so iMessage behaviour could not be verified and is behind flags (D-07).
- The audit said "no per-caller identity". That is still true until Chert confirms the call carries the caller handle; attribution falls back to the claim window (D-06).

## Decisions D-01 to D-22
| ID | In plain words | Why |
|---|---|---|
| D-01 | Work happens on a new branch `orch/20261012-1810`; the three untracked facetime files stay untouched | You asked to leave them |
| D-02 | Queue, caps, scoring and message outbox live in the database as functions that take "now" as an input | Atomic under concurrency without direct DB credentials; tests and the simulation can fake time |
| D-03 | The public site is a new app `pushup-web/` on its own Vercel project; the old `web/` coach app is untouched | Route clashes and not breaking the coach demo |
| D-04 | Competitors are stored as clients under a seeded "Brodie Challenge" coach | Existing sessions/sets/reps tables keep working |
| D-05 | The worker saves reps through the dispatcher, not straight to the database | One writer, safe to retry (keyed by call id) |
| D-06 | With `CALLER_ID_SOURCE=claim_window`, walk-in callers are rejected | Without a handle we cannot tell who a walk-in is |
| D-07 | Safe defaults: `MESSAGING_PROVIDER=mock`, `HANGUP_MODE=unverified`, `REVEAL_MODE=audio_only`, `CARD_DELIVERY=link` until Chert answers | Flags can be flipped live when answers arrive |
| D-08 | Integration tests use a local Postgres 17 with Supabase look-alike roles | No Docker available |
| D-09 | The judge counts people with two pose slots | One slot can never see a second person |
| D-10 | The lockout check is measured at the top that starts each rep | See the 15% note above; a set with no lockout still fails every rep after the first |
| D-11 | Tie-break: whoever reached the tied total first, measured by the time of their last scoring event | Points only go up, so the last scoring time is when the total was reached |
| D-12 | Voided calls still count toward the daily cap | Stops void-and-retry abuse; an admin can adjust |
| D-13 | A walk-in is allowed when the only waiting entry is the caller's own | Their own entry should not block them |
| D-14 | Texting QUEUE after STOP opts the person back in | An explicit action is consent; STOP is still instant |
| D-15 | The judge runs at 10 FPS and uses median-style aggregation for extremes | Raw min/max let noise pass cheats |
| D-16 | A single noisy frame never decides; faults on 2+ frames reject; extremes use the 2nd-best frame | Balances transient glitches against noise passing cheats |
| D-17 | `knee_floor_margin` is 0.02 (not 0.08); noise within about 5 degrees of a limit is accepted; final calibration on real clips | Synthetic evidence: 0.08 caused false rejects |
| D-18 | Geometry-checked ghost de-duplication landed; remaining ghost second-person rejects to be measured on real clips | Side view (the required setup) showed 0 ghosts |
| D-19 | Ghost second-person false rejects remain on front-view stock clips (9% of reps; 0 of 14 on side-view); the ship gate stays INCOMPLETE until real side-view clips exist | No side-view two-person footage to tune on |
| D-20 | Liveness redesigned: distinguishable challenges (lift-hold, double-tap, freeze), a quiet window before the cue, an unprompted-motion flag, "present but unverifiable" = fail, camera-motion invalidation | Review showed a periodic-tap replay passed about 100% |
| D-22 | The raffle is cancelled; prizes are 1st place plus the top-3 group call with a UFC fighter | User decision 2026-10-12; all raffle config, views, admin and copy removed |
| D-23 | Calling the line puts you in the queue: a busy-line call by a known caller auto-joins the queue and texts the spot; QUEUE texting still works | User request 2026-10-12 (less friction). Needs caller ID, so active only with CALLER_ID_SOURCE=chert_meta; claim_window keeps the plain reject |

## Decisions you may be asked to make
- Launch with the ship gate INCOMPLETE (D-19), or wait for clips? See `BLOCKERS.md` B3.
- Use sslip.io instead of a domain? See `HUMAN_TASKS.md` section 5.
