# Progress (phases P0-P7)

State as of 2026-10-13. The challenge is LIVE. Live release `4c08082` (HEAD of the branch this file was written on).

- Site: https://brodie-pushups.vercel.app (Vercel)
- Dispatcher: https://3.13.177.157.sslip.io on EC2 `i-0d098dcf3948886ce` (m7i-flex.large, us-east-2, AWS profile `beatmuse`, free plan with $100 credits)
- Database: Supabase project `beat-muse` (`tqfilmqvbhrywjstmyhu`)
- Services running on EC2: `brodie-worker`, `chert-agent`, `brodie-dispatcher`; `brodie-reconciler.timer` is enabled (every 60 s, `--once`, hard deadline `RECONCILE_MAX_RUN_S=50`, `TimeoutStartSec=90`)
- Messaging: `MESSAGING_PROVIDER=chert`; iMessage verified end to end (JOIN, QUEUE, "you're up"). Line (628) 246-3964, Chert project `2c765f80-02fb-4b0c-91ac-723ffece9006`
- Flags live: `CALLER_ID_SOURCE=claim_window`, `HANGUP_MODE=unverified`, `REVEAL_MODE=audio_only`
- OPEN INCIDENT: inbound FaceTime to the line stopped (nothing seen on the Mac behind the line since 04:23 on 2026-10-13; Chert shows no call records). It is upstream (Chert or the Mac owner), not our code. See `BLOCKERS.md` B1.
- Tests: full challenge suite about 1040 passed; the other suite about 106 passed, 6 skipped. Known flaky test: `tests/challenge/test_scheduler_properties.py::test_scheduler_state_machine[1-line]` (its `pops >= 200` guard once got 145 under load; passed on rerun).

| Phase | Scope | Status | Evidence (commits) |
|---|---|---|---|
| P0 | Recon, spec, contracts, plan, decisions | Done | `a7cf4ce` spec/contracts/plan, `803ca40` contracts v1.1, notes `fb2832c` `856526c` `201c289` `9d96040` `b88f8eb` |
| P1 | Data layer: schema, RLS, views, config seed, RPCs | Done and live. Migrations are applied by hand with `supabase --linked` as owner; the deploy role `brodie_ops` cannot write `competition_config`, so config is applied with `supabase db query --linked` | `9c9ee66`/`efa64d4` schema, `6f710c0`/`e5271f5` calls, `50ac8d4`/`c6c0a68` misc, `8377f74`; latest `20261022_challenge_judge_j3.sql` (`a064896`, `5f043d8`), `9da2781` pgcrypto fix |
| P2 | Identity + call lifecycle: Chert, dispatcher call API, worker controller, reconciler | Done and live; inbound FaceTime currently down upstream | `1ed1d1d` discover_chert, `71b3888`/`c45cb20` dispatcher API, `aae1318`/`9eebc68` worker controller + checkpoints (30), `8dcefd4`/`4c08082` reconciler (32), `cb723e6` warm-room test (37), `3f0cfa5` harness mirrors Supabase schema (36) |
| P3 | Judge: gates, runtime hook, cues, harness, rejudge, liveness | Done. Live judge is j3 lenient with liveness OFF (D-34, owner decision). Real-clip gate re-baselined for j3 | `91c9c93` j3, `d381f13`/`aad8e8b` calibration (j2, now reference), `2b65416` real-clip gate, `3ab5500`..`fb1899c` liveness (12, code kept, off), `0833e25` rejudge |
| P4 | Dispatcher: messaging, commands, outbox, jobs, simulation, admin endpoints | Done and live | `89fe43a` Chert iMessage provider, `ccc0805`/`4717b38` outbox (22), `bc2d5bb`/`2c533ca` jobs (23), `35a2d7f`..`3dce926` simulation (24), `428803f`/`2277aa0` admin endpoints (25) |
| P5 | Website: public pages, join, admin, design pass, config copy | Done and live (web redesign by the deploy session) | `2a2f23e`/`98f7ebf` admin (43), `b90bb6e`/`5d44513` design pass (45), `e0c4d2b`/`83f1931`/`341a422` web join (44), `8a32578`/`8603f7b`/`709afad` config copy (46), `515f6d4`/`cded247` raffle removed (47, D-22), `f29474a` riso redesign |
| P6 | Infra: systemd, Caddy, backups, deploy/rollback, monitoring | Done and live on EC2 | `20b5425`/`0b541b2`; `e4f6439`, `4f5209a`, `11239f4` deploy fixes; `0de091a` runbook live section |
| P7 | Docs and human setup tooling | Refreshed 2026-10-13 (task 53) | this change |
| Extra | Caller video and voice | Live: push-up mirror (whole picture, no zoom or pan, form skeleton, camera status, mascot; 15 fps / 2.8 Mbps), auto-rotation for portrait-locked phones, cue bank v2 | `ac1b6d3`, `df6c86b`, `51b14d3`, `167c340`, `0166efb` |
| Extra | `HANGUP_MODE=chert_api` | Built, not enabled; waiting for inbound FaceTime to work so one test call can be made | `5efc9fe`, `b438c3f`, `3590f2f` (35, 38) |
| Extra | `REVEAL_MODE=video` | Built (33); being reworked to render inside the coach-video track after the commit (task 39, in progress) | `180c520`, `8347adf` |
| Parked | Strict liveness (2-stage, branch `orch-task/34`) | Not landed, kept for reference (D-33, D-34) | branch `orch-task/34` @ `8b3ea45` |

To refresh the numbers: `git log --oneline | head -40` and
`PYTHONPATH=src:. .venv/bin/python -m pytest -q -p no:cacheprovider tests/challenge infra scripts/harness`.
The website's vitest suite needs `cd pushup-web && npm ci && npm test`.
