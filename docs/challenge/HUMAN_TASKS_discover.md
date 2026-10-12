# Chert discovery runbook (SPEC §3 #1, #3, #4)

Goal: learn (1) whether `chert_call` carries the caller handle, (3) whether FaceTime hangs up when the agent leaves, (4) how long the line stays offline afterwards. Needs one tester with a phone/FaceTime and one operator at the repo.

## Setup (operator, from the repo root)
```
cd /Users/stanley/brodie-rt-coach
set -a; source .env.local; set +a
export PYTHONPATH=src:.
.venv/bin/python scripts/discover_chert.py dev --leave-after-s 20
```
In a second terminal (same repo root, same env export) start Chert pointed at this agent:
```
cd /Users/stanley/brodie-rt-coach
set -a; source .env.local; set +a
chert dev --agent "$AGENT_NAME"
```
The script prints a warning: logs in `data/tmp/discover/` hold caller handles unredacted (gitignored). No media is stored.

## Test A: does the line hang up when the agent leaves? (#3)
1. Tester FaceTimes the Chert line. Note the wall-clock time the call connects.
2. Stay on the call. After 20 s the agent leaves.
3. Record: did FaceTime end by itself? how many seconds after the agent left? (If it never ends, wait 60 s, then hang up manually.)

## Test B: offline gap (#4)
1. The moment the call ends (by hang-up or by agent), start a timer.
2. Tester calls back every 30 s. Record the time of each attempt and its result (busy/offline/rings/connects).
3. Record when it first rings through and the agent joins (a new file appears in `data/tmp/discover/`).

## Test C: payload (#1)
Open the newest log: `ls -t data/tmp/discover | head -1`, then
`jq -c 'select(.ev=="job" or .ev=="connected")' data/tmp/discover/<file>.jsonl`.
Record whether `chert_call` exists and which fields it has (handle/phone/email/call id?), and the participant identity/attributes.

## Results table (copy and fill)
| Test | Observation | Seconds | Notes |
|---|---|---|---|
| A: hung up after agent left? | yes/no | | |
| B: first successful call-back | | | attempts: |
| C: chert_call has caller handle? | yes/no | | fields: |
| C: participant identity format | | | |
| dispatch lag (`job` -> `connected` dt) | | | |

## Where to paste results
Paste the table plus `jq -c .` output of the `job`, `connected`, `participant_disconnected` and `room_disconnected` lines (redact handles to last 2 digits) into the Phase 2 section of `docs/challenge/HUMAN_TASKS.md`, then set `HANGUP_MODE`, `LINE_OFFLINE_GAP_S` and `CALLER_ID_SOURCE` accordingly.
