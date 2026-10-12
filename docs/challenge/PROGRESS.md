# Progress (phases P0-P7)

Evidence is from the repo at the time of writing: offline suite `PYTHONPATH=src:. .venv/bin/python -m pytest -q -p no:cacheprovider tests/challenge infra scripts/harness`
gave 652 passed (after adding `tests/challenge/test_seed_admins.py`, 11 tests). The website's vitest suite was not run in this
environment (`pushup-web/node_modules` not installed): run `cd pushup-web && npm ci && npm test`. Nothing here is live: no AWS, no live
Supabase apply, no Vercel deploy (see `BLOCKERS.md`).

| Phase | Scope | Status | Evidence (commits) |
|---|---|---|---|
| P0 | Recon, spec, contracts, plan, decisions | Done | `a7cf4ce` spec/contracts/plan, `803ca40` contracts v1.1, further contract notes `fb2832c` `856526c` `201c289` `9d96040` `b88f8eb` |
| P1 | Data layer: schema, RLS, views, config seed, RPCs | Done offline; live apply pending (B4) | `9c9ee66`/`efa64d4` (01 schema), `6f710c0`/`e5271f5` (03 calls), `50ac8d4`/`c6c0a68` (04 misc), `8377f74` power-hour lookup; tests `tests/challenge/test_db_*.py` |
| P2 | Identity + call lifecycle: Chert discovery, dispatcher call API, worker integration, reconciler | Partial: discovery script and dispatcher call endpoints done; worker controller (30), reconciler (32) not merged | `1ed1d1d` discover_chert, `d656fab`/`365a2c3` py-core, `71b3888`/`c45cb20` dispatcher API; live discovery needs a human (HUMAN_TASKS 13) |
| P3 | Strict judge: gates, runtime hook, liveness, cues, harness, rejudge | Mostly done; liveness redesign (12, D-20) not merged; SHIP GATE INCOMPLETE (D-19) | `4a6161e`/`94bd330` judge core, `9010136`/`de533e2` runtime, `1bfe731`/`1f00d75` cues, `0833e25` harness + rejudge |
| P4 | Dispatcher: messaging, commands, outbox, jobs, simulation | Partial: messaging adapters/templates (`65a204b`/`e65cc85`); outbox wiring (22), jobs (23), simulation (24), admin endpoints (25) not merged | `challenge/messaging/`, `tests/challenge/test_messaging.py` |
| P5 | Website: public pages, avatar, profile + card, admin, design pass | Done offline; Vercel deploy pending (B5); web-only join (44) and config copy (46) not merged | `64d37ff`/`441b7c8` public, `2a2f23e`/`98f7ebf` admin, `7ed2951`/`e7a4494`/`6b1425b` profile + card, `b90bb6e`/`5d44513` design pass |
| P6 | Infra: systemd, Caddy, backups, deploy/rollback, monitoring | Scripts written and tested offline; AWS provisioning blocked (B1) | `20b5425`/`0b541b2`; `infra/test_infra.py`, `infra/test_releases.py` |
| P7 | Docs and human setup tooling | In progress (this change) | `HUMAN_TASKS.md`, `BLOCKERS.md`, `LAUNCH_CHECKLIST.md`, `DECISIONS.md`, `PROGRESS.md`, `RUNBOOK.md` additions, `scripts/seed_admins.py` |

To refresh the numbers: `git log --oneline | head -40` and the pytest command above.
