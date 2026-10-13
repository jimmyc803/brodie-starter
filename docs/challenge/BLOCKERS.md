# Blockers (current as of 2026-10-13)

Only what still blocks or limits the launch. Each item has an owner and the step that clears it. Detailed steps are in `HUMAN_TASKS.md` (section numbers in brackets).

| # | Blocker | Owner | What is stuck | Unblock step |
|---|---|---|---|---|
| B1 | Inbound FaceTime to the line stopped (OPEN INCIDENT) | You + Chert (James) / the Mac owner | No inbound call detected on the Mac behind the line since 04:23 on 2026-10-13; Chert shows no call records. Nobody can call in. Upstream, not our code. Also holds `HANGUP_MODE=chert_api` (cannot test a call) | Ask Chert and check the Mac (signed in to FaceTime, awake, line enabled); then place one test call and confirm it reaches the worker [HUMAN_TASKS 14] |
| B2 | Web sign-in cannot scale (Supabase Auth email) | You | The built-in Supabase email sends about 2 per hour. Custom SMTP via SES is pending verification and still in the SES sandbox | Finish SES verification (leave the sandbox), then set custom SMTP in Supabase [HUMAN_TASKS 3d]. Until then people join by iMessage text (`JOIN <name>`) |
| B3 | Tester data still in the database | You | Test calls and accounts would show on the public board | Void or remove tester rows through the audited admin RPCs before the public push [LAUNCH_CHECKLIST T-24h] |
| B4 | Real-clip gate under j3 | You (owner) | The gate (`judge_eval/check_real_clips.py`) fails without clips; it has been re-baselined for j3 (`91c9c93`) but needs the footage on this machine | Run it with the clips [HUMAN_TASKS 10], or record in `DECISIONS.md` that you accept launching without it |
| B5 | Top-3 verification call and prize logistics | You | 1st place plus a top-3 group call with a UFC fighter (no raffle, D-22); not yet arranged | [HUMAN_TASKS 9]; do the verification call before payout |
| B6 | `HANGUP_MODE=chert_api` decision | You | Built and tested, not enabled; flipping it needs one live test call | After B1 clears: one test call, then set the flag if it ends cleanly [HUMAN_TASKS 2] |

## Resolved (kept for the record)
| Was | Resolution |
|---|---|
| AWS account and credentials | EC2 `i-0d098dcf3948886ce` provisioned in us-east-2, profile `beatmuse` |
| Chert login and answers; iMessage not delivered | `MESSAGING_PROVIDER=chert`, iMessage verified end to end; caller ID stays `claim_window` because Chert exposes only `from_handle_hash` |
| Judge ship gate INCOMPLETE (D-19) | Replaced by the lenient j3 judge with liveness off (D-34); j3 clean accept 93.3% on the real-clip set |
| Supabase migrations not applied | Applied manually with `supabase --linked`; config via `supabase db query --linked` |
| Vercel deploy, domain | Live at https://brodie-pushups.vercel.app; dispatcher on https://3.13.177.157.sslip.io |
| Admin emails, alert handles | `team_alert_handles` set (one entry, the owner's number) |
| Unmerged work (12, 22-25, 30, 32, 33, 44, 46) | Merged; live release `4c08082`. Task 39 (video reveal rework) is still in progress but does not block (`REVEAL_MODE=audio_only`) |
| Cue audio for new phrases | Bank v2 rendered; rsync to EC2 step in [HUMAN_TASKS 11] if the cue text changes again |
