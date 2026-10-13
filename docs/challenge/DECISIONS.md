# Decisions (plain-language summary)

Source of record: `.orch/DECISIONS.md` (internal log). This page explains each decision for people who were not in the room.

## Ground-truth differences from the spec's audit (SPEC section 1)
- The repo already contained untracked files `facetime/annotate_video.py`, `facetime/call_render.py`, `facetime/heatmap_intro.py`; they were left alone (D-01).
- `src/rtcoach/pose.py` tracked only one person; the judge needs two to detect "two people" (D-09).
- The rep counter registers a rep when the person is 15% back up from the bottom, so the finishing lockout is not yet visible at that moment (D-10).
- No fixed depth, knee or hip-line gate existed; the strict judge adds them (see D-15 to D-20). Since 2026-10-13 the live judge is the lenient j3 and the liveness test is off (D-34).
- Chert's command line had no messaging surface, so iMessage behaviour was first behind flags (D-07). Since then the Chert Messaging API was built and iMessage works live.
- The audit said "no per-caller identity". Still true: Chert exposes only a hashed caller id (no phone or email), so attribution uses the claim window (D-06).

## Decisions D-01 to D-34
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
| D-19 | Ghost second-person false rejects remain on front-view stock clips (9% of reps; 0 of 14 on side-view); the ship gate stays INCOMPLETE until real side-view clips exist | No side-view two-person footage to tune on (Superseded by D-34: lenient j3, ship gate is now the j3 real-clip check.) |
| D-20 | Liveness redesigned: distinguishable challenges (lift-hold, double-tap, freeze), a quiet window before the cue, an unprompted-motion flag, "present but unverifiable" = fail, camera-motion invalidation | Review showed a periodic-tap replay passed about 100% (Parked, liveness is off: D-34.) |
| D-22 | The raffle is cancelled; prizes are 1st place plus the top-3 group call with a UFC fighter | User decision 2026-10-12; all raffle config, views, admin and copy removed |
| D-23 | Calling the line puts you in the queue: a busy-line call by a known caller auto-joins the queue and texts the spot; QUEUE texting still works. 2026-10-12: Chert masks inbound callers (calls API masked_identity '***', no handle), so this stays dormant under CALLER_ID_SOURCE=claim_window and all copy says text QUEUE first | User request 2026-10-12 (less friction). Needs caller ID, so active only with CALLER_ID_SOURCE=chert_meta; claim_window keeps the plain reject |
| D-24 | A handle typed on the website can't be verified (no SMS channel). The first person to enter it keeps it, and it is never merged into an existing account. Who is on a call is still decided by the claim window | There is no way to text-verify web sign-ups |
| D-25 | A handle entered on the website is only a pending claim until the person texts `LINK <code>` from that handle. Until then: no texts to it and no handle-based caller ID | Both security reviews found that binding unverified handles let people squat on someone's number or steal their calls |
| D-26 | The website-to-dispatcher login check always requires the token issuer (`SUPABASE_JWT_ISSUER`), in both secret and key-set modes; a missing or mismatched issuer is rejected | A review found the secret-only setup skipped the issuer check |
| D-27 | Website requests get their own per-IP rate ceiling (default 20000 per minute); the real limit is per user (120 per minute) | Every website call comes from Vercel's shared IPs, so the shared 600 per minute limit would block us at about 30 live users |
| D-28 | Accepting a call also returns the live config (count and reveal seconds, judge thresholds). A new heartbeat call lets the worker report it is alive | The worker needs one source for live config, and the liveness alert needs a heartbeat |
| D-29 | (Parked with the liveness test, D-34) The freeze challenge ends with a random-time "go" cue; motion must resume after it, not before | Replays that paused every 6 s beat freeze 30-47% of the time |
| D-30 | (Parked) Liveness go delay 2-8 s, reaction window 2.0 s | Long-pause replays passed 6-15% at 2-4.5 s; honest first-try pass fell at a 1.5 s window |
| D-31 | Minimum lockout angle 150 degrees in the strict judge (j2); in j3 it is 135 | Real clean tops (145-177) overlap the fake 140-degree cheat under noise; rejecting honest people is worse than accepting near-lockouts |
| D-32 | (Parked) Liveness shipped with a 15 s hand cooldown; replays lifting every 20-35 s at rest still passed 7.5-9.5% | Ship the big improvement; admin re-judge covers the rest |
| D-33 | (Parked, branch `orch-task/34`) Liveness needs 2 passed checks per call, the 2nd 10-60 s after the 1st; reps after the last pass count | One pass left 19.7% of replays through; two checks bring it to 1% or less per call while honest callers still pass 100% |
| D-34 | OWNER DECISION 2026-10-13: the liveness "cheater test" is OFF and the judge is the lenient j3. `liveness_enabled` is false in the live `judge_thresholds`; the code and tests stay, and one config change turns it back on. The strict j2 calibration (clean side-view accept 86.7%, 0 cheats) and the 2-stage liveness branch are parked for reference. Live j3 values: min_conf 0.4, frame_conf 0.6, knee 120, hip 30/40, depth 120/0.92, lockout 135, incline 25 / decline 35, min rep time 0.45 s, cadence 100, no classifier veto | The owner wants a lenient, friendly public challenge. Real-clip result for j3: clean reps accepted 93.3%, worst count error 1. Cheats that rely on pretending to be live are no longer caught; use admin re-judge and void for abuse |

## Decisions you may be asked to make
- Run the j3 real-clip check before the public push, or accept launching without it? See `BLOCKERS.md` B4.
- Turn on `HANGUP_MODE=chert_api` after one test call? See `BLOCKERS.md` B6.
- Turn liveness back on (D-34)? Only by a config change plus a fresh look at the parked branch.
