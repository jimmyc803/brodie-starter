# PLAN — Brodie Push-Up Challenge (orch run 20261012-1810)
SPEC: docs/challenge/SPEC.md · CONTRACTS: docs/challenge/CONTRACTS.md (frozen; committed first)

## Approach
1. All transactional logic (line state machine, queue, caps, scoring, outbox dedupe) lives in plpgsql RPCs with row locks; every RPC takes p_now so tests and the 60-user simulation drive time. Python calls them via one Store interface (PgStore for local Postgres tests, SupaStore via PostgREST in prod).
2. Dispatcher = FastAPI + an asyncio jobs loop (tick every 2s, scheduled jobs by ET clock). Messaging behind MessagingProvider (mock default; chert stub; web_only).
3. Judge = pure per-rep metrics + deterministic gates (challenge/judge) hooked into the existing FramePipeline so live and judge_eval replay share one path; RepCounter2 still detects reps; side-view adaptation + num_poses=2 for person count; liveness challenge.
4. Worker gets a CompetitionCall controller (gatekeeper via dispatcher, 3:00 count + 15s reveal, commit via dispatcher with local JSON backup + reconciler). Legacy DEMO_CLIENT_ID path behind CHALLENGE_MODE=demo.
5. Public site = new Next.js app pushup-web/ (separate Vercel project) reading anon views + realtime site_pulse; admin via Supabase email login + allowlist, server actions call service RPCs. Result card via next/og at /r/[callId]/opengraph-image.
6. Infra scripts for EC2 (systemd, Caddy, backups, deploy/rollback) written + linted; actual AWS provisioning blocked on credentials.

## Task DAG
Wave 1 (parallel): 01 db-schema · 02 py-core · 10 judge-core · 13 cues · 21 messaging · 31 discover-chert · 40 web-public · 41 avatar · 50 infra
Wave 2: 03 db-calls(01) · 04 db-misc(01) · 11 judge-runtime(10) · 20 dispatcher-api(02,03) · 42 web-profile-card(40,41)
Wave 3: 12 liveness(11) · 14 harness+rejudge(11) · 22 outbox+commands-wiring(04,20,21) · 30 worker-controller(11,20) · 43 admin(04,40)
Wave 4: 23 jobs(22) · 24 simulation+property(23) · 32 reconciler(30) · 44 web-only-join(20,40)
Then: apply migrations to beat-muse, deploy pushup-web to Vercel, docs (HUMAN_TASKS, RUNBOOK, LAUNCH_CHECKLIST), DONE.
