# Brodie for Coaches

**IvyHacks 2026 · Team Beat Muse**

A coach writes the program. Brodie runs the workout over FaceTime. The coach sees how it went.

Personal trainers hand clients a PDF and hope they follow it. Brodie for Coaches turns that PDF into a coached session: the client video-calls Brodie, an AI coach that watches through the camera, counts every rep, corrects form out loud and talks between sets. When the call ends, the client and the coach each get a recap showing which muscles were trained and how cleanly. Nobody installs an app or makes an account: everything is a private link.

<p align="center"><img src="https://brodie-for-coaches.vercel.app/api/recap-image/demo" width="300" alt="Recap card Brodie sends after a call: front and back muscle heat map, rank, reps, sets and clean-rep percentage"></p>

## Try it

| What | Link |
| --- | --- |
| Client recap (what the client gets after a call) | https://brodie-for-coaches.vercel.app/r/demo |
| Coach dashboard (every client's sessions) | https://brodie-for-coaches.vercel.app/c/demo |
| Recap card (the image Brodie shows on the call and texts to the client) | https://brodie-for-coaches.vercel.app/api/recap-image/demo |
| Program upload (view-only on the public demo link) | https://brodie-for-coaches.vercel.app/c/demo-tristan-R7mQ2vK9xL4pN8sW1tY3aB5c/program |

## How it works

1. **The coach uploads a program PDF.** Gemini reads it into days, exercises, sets and reps. The coach checks the parsed days and assigns one to a client.
2. **The client calls Brodie.** The LiveKit worker loads that client's assigned day, counts squats, push-ups, lunges, jumping jacks and curls with MediaPipe pose estimation, flags form faults (like knees past toes on a squat) and coaches by voice.
3. **Every rep is saved.** When the call ends, the worker writes the session, sets, reps, faults and per-muscle scores to Supabase.
4. **Everyone sees the recap.** The client gets a recap link and a recap card on the call. The coach's dashboard shows every client's sessions, which muscles were worked, and what to look at next.

### The muscle heat map

Each exercise maps to main and helper muscles (`shared/muscles.json`, 16 muscles). Each exercise gets a quality score: half for clean reps, 30% for finishing the planned reps, 20% for holding form through the last set. A muscle's score averages the exercises that hit it, so colour means how well it was trained, not how hard: green is solid (0.75 or better), yellow is room to improve (0.5 or better), red needs work, grey wasn't trained. Main muscles glow brighter than helpers. Daily ranks run from Novice through Beginner, Intermediate, Advanced, Expert, Elite, Master and Legendary. Each trained muscle uses exactly its rank's color in the coach view, client recap and shared recap image; coverage changes the halo, never the rank color.

## Built with

- **Coach:** Python, LiveKit Agents, MediaPipe pose, Gemini voice (the Brodie starter)
- **Web:** Next.js 16 (App Router), Tailwind, shadcn/ui, `next/og` for the recap card, on Vercel
- **Data:** Supabase Postgres and private Storage. Row-level security is on with no public policies; only the server uses the service key.
- **Program parsing:** Gemini 2.5 Flash with structured JSON output

### Where things live

| Path | What |
| --- | --- |
| `facetime/` | The call worker: plan loading, rep events, saving sessions |
| `web/` | Recap pages, coach dashboard, program upload, recap card |
| `db/schema.sql`, `db/migrations/` | Database tables and the upload functions |
| `shared/muscles.json` | The team contract: exercises → muscles, labels, scoring |

### Privacy

Links are long random tokens, pages are `noindex`, and unknown tokens return a real 404. The public demo coach link can view but not upload or assign. Muscle scores are estimated coverage, not a measurement of muscle activation.

## Team

| Who | Built |
| --- | --- |
| Jimmy | Web app: heat map, client recap, recap card, coach dashboard |
| Kevin | Web app front end |
| Stanley | Database, the call worker saving sessions, the team contract |
| Ryan | Program PDF upload, parsing and assignment |
| Tristan | Demo coach |

---

# Run the coach yourself (Brodie starter)

A real-time video coach in one Python process. Your phone joins a LiveKit room, the coach watches through the camera, counts reps, corrects form out loud, and talks between sets.

You write the coaching. Perception is done for you.

### What you need

- macOS or Linux, Python 3.12, [uv](https://docs.astral.sh/uv/) (`brew install uv`)
- A free LiveKit Cloud project ([cloud.livekit.io](https://cloud.livekit.io))
- A phone, or Safari on a Mac
- Your team card (Gemini team token)

### 1. Install (about 30 minutes, mostly waiting)

```
git clone https://github.com/seraphimlabs-dev/brodie-starter.git brodie-rt-coach && cd brodie-rt-coach
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
mkdir -p models && for m in lite full heavy; do curl -sSfL -o models/pose_landmarker_$m.task https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_$m/float16/latest/pose_landmarker_$m.task; done
```

On Linux, run `uv pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu` first to skip 3 GB of CUDA wheels.

### 2. Get the data bundle

The models, voice clips and sample recordings are not in git. Download them from this repo's release and unpack them at the repo root:

```
for p in part1_models_recordings part3_bank_puck; do curl -sSfLO https://github.com/seraphimlabs-dev/brodie-starter/releases/download/data-2026-10-09/rtcoach_starter_${p}_2026-10-09.tgz; done
tar xzf rtcoach_starter_part1_models_recordings_2026-10-09.tgz && tar xzf rtcoach_starter_part3_bank_puck_2026-10-09.tgz
```

Check it worked:

```
ls data/models/clf_pose.pt data/models/trigger_lr.json data/cues_audio_gemini/manifest.json models/pose_landmarker_full.task
```

### 3. Prove the install (2 minutes, no phone)

```
python -m facetime.replay_local --video data/tmp/mac_handoff/crops/run3.mp4 --plan "squats:10,pushups:8,jumping jacks:20,lunges:10" --fast --events data/tmp/run3.events.jsonl
python scripts/test_voice.py
```

### 4. Configure

Copy `.env.example` to `.env.local` and fill it in. The LiveKit values come from your project's Settings, then Keys. The Gemini token is on your team card.

### 5. First call

Terminal A, the coach:

```
source .venv/bin/activate && set -a && source .env.local && set +a
python -m facetime.worker --voice gemini dev
```

Terminal B, the link (use a new room name for every attempt):

```
source .venv/bin/activate && set -a && source .env.local && set +a
python -m facetime.mint_token --room team1-try1 --url
```

Open the third printed line on your phone, tap to enable audio, prop the phone up and step back. You should hear "Let's do squats" and then the counts.

Always start Terminal A before the phone joins.

### What you change

Only these three files:

| File | What it is |
| --- | --- |
| `starter/persona.md` | Who Brodie is and how it talks between sets |
| `starter/plan.txt` | The workout, e.g. `squats:10,pushups:8,jumping jacks:20,lunges:10` |
| `starter/handlers.py` | `on_event(event, say_now, ask_voice)`, called for every rep, fault, cue and set change |

- `say_now(text)` plays a pre-recorded line about 0.2 s later. Only strings in `data/cues_audio_gemini/manifest.json` work.
- `ask_voice(prompt)` asks the conversational voice, which answers 1 to 2 s later. Only call it when `session.state` is `rest` or `done`, never during a set.

### Docs

- [docs/STARTER_README.md](docs/STARTER_README.md): full setup, troubleshooting, FaceTime lines, licence
- [docs/STARTER_EVENTS.md](docs/STARTER_EVENTS.md): every event and its fields
- [docs/BUILD_ON_BRODIE.md](docs/BUILD_ON_BRODIE.md): what you can build and how

The same pages are at [seraphimlabs.dev/hackathon](https://seraphimlabs.dev/hackathon).

### Licence

The models and the thresholds (`clf_pose.pt`, `trigger_lr.json`, `src/rtcoach/thresholds_e3c.json`, `src/rtcoach/cue_prior.json`) come from a research evaluation licence. Use them for this hackathon only and do not redistribute them.
