# Autonomous curl replay

Run from the repository root (no credentials or camera needed):

```sh
.venv/bin/python scripts/harness/replay.py --output data/tmp/harness/replay
PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_harness_replay.py -q
```

The CLI exits nonzero if any check fails. Standard output is a JSON report; sink
logging goes to standard error. `report.json` summarizes all cases. Each scenario
file includes the full event stream, captured persistence rows and session view;
`sessions/` contains the production sink's recap JSON.

This is explicitly **synthetic-landmarks** mode at 10 fps. Only the external
camera/MediaPipe pose acquisition and Supabase I/O are replaced. The real
`FramePipeline`, `CurlCounter`, `Perception`, workout `Session`, `SessionSink`, and
shared muscle scoring execute together. No model files, database, Gemini token,
LiveKit session, or live phone are required. It does not validate MediaPipe's
accuracy on a human, Gemini parsing quality, remote persistence, or a phone call.
Curls currently have no trained form-fault classifier, so the expected fault list
is empty; a clean score is not a claim of clinically correct form.

The independent expected outcomes are five completed plus two partial curls =
five reps; an occluded unfinished curl = zero; changing which arm is more visible
cannot complete a locked-arm curl; threshold noise = zero; the visible right arm
counts two reps; missing pose discards an unfinished curl. Every case checks the
rep sequence and event key, turning timestamps, persisted counts/faults, session
closure, all 15 muscle scores, biceps coverage, and gray untrained quads.

Real video validation remains separate: follow `docs/BICEP_CURL.md` for 10-fps
conversion and replay of a filmed side-view curl clip. A squat clip cannot certify
curl device accuracy. This harness reports `device_validated: false` explicitly.

Optional real-video smoke (requires the existing licensed local pose model and
bundled recording; never downloads assets):

```sh
.venv/bin/python scripts/harness/replay.py --video-smoke
# Or provide another recorded squat clip:
.venv/bin/python scripts/harness/replay.py --video-smoke /absolute/path/squats.mp4
```

This streams at most 30 seconds of video, samples to 10 fps, and runs real
MediaPipe, the squat counter, session and event pipeline. It checks pose detection,
nonzero reps and sequential rep events; `video-smoke.json` retains the full stream.
It is a smoke test, not an exact-count accuracy benchmark. Missing local video or
model assets report `status: skipped` with paths; runtime or check failures fail
the command. The main `passed` field permits this optional asset skip, so inspect
`video_smoke.status` when requiring a real-video pass. Curl validation stays false.
