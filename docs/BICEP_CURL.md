# Bicep curl demo

`bicep curls`, `bicep curl`, `bicep_curl`, and `bicep_curls` resolve to the
canonical plan name `bicep curls`. Assignment days use `exercise_key: bicep_curl`.
The regular worker, replay, session sink and recap use this same route.

The counter selects the most visible shoulder/elbow/wrist and keeps that arm
until tracking is lost. It uses MediaPipe world elbow angles to avoid portrait
image aspect distortion. Start extended (at least 150 degrees), curl to at most
65 degrees, then extend again. Each threshold must hold for two frames at 10 fps;
a complete movement must last at least 0.8 seconds. A missing pose, occluded arm,
or invalid geometry discards the unfinished repetition. Completed counts survive
reacquisition; a new set starts at zero. Simultaneous two-arm curls count once;
alternating curls are not supported by this side-view counting protocol.

Rep events retain the existing `exercise`, `n`, `confidence`, `turning_t` and
`lag_s` fields and add `exercise_key: "bicep_curl"`. Confidence is null because
this counter does not use the multi-signal voting estimator. `turning_t` is the
flexed extreme; the count is emitted on the return to extension. There are no
trained curl form labels: unrelated classifier corrections are disabled for this
exercise. An empty faults list means no fault detected, not validated perfect form.

## Film the missing validation clip

The bundled run2/run3/live recordings contain squats, pushups, jacks and lunges;
no curl recording is supplied. Synthetic tests pass, but curls are **not yet
validated on a phone recording**.

Film a 25–35 second clip in portrait, phone steady at approximately elbow height,
2–3 metres away, directly side-on. Keep your entire body in view (the common
pipeline requires head and feet), particularly the nearer shoulder, elbow and
wrist. Stand still with the near arm extended for two seconds. Do five slow curls
with that arm (or both arms together), keeping upper arms by your torso: curl up
for roughly one second, lower for one second, briefly pause fully extended.
Then do two deliberately incomplete curls and pause for two seconds. Expected
count: five. Use a light weight suitable for your normal workout. Repeat from
the other side if time permits. Avoid overlapping the far arm in front of the
near arm. No count accuracy claim until the replay matches this manual count.

From the repository root, convert to **10 fps before replay**:

```sh
mkdir -p data/tmp
ffmpeg -i /path/to/curls.mov -vf "fps=10,scale='if(gt(iw,ih),-2,288)':'if(gt(iw,ih),288,-2)'" -an -c:v libx264 -preset fast -crf 23 data/tmp/curls_10fps.mp4
.venv/bin/python -m facetime.replay_local --video data/tmp/curls_10fps.mp4 --exercise "bicep curls" --fast --events data/tmp/curls.events.jsonl
```

Single-exercise mode keeps recording during the deliberate partial reps, so false
counts remain visible. The assignment demo uses `--plan "bicep curls:5"`.
Do not commit video, models or generated event files.

Local tests (no model, camera, keys or network required):

```sh
PYTHONPATH=src:. .venv/bin/python -m pytest tests/test_curl_counter.py -q
```

## Prerecorded announcements

The cue vocabulary includes canonical exercise names from `shared/muscles.json`,
including `bicep curls`. Existing downloaded voice banks need the three new clips:
`Let's do bicep curls`, `Moving on to bicep curls`, and `Looks like bicep curls`.
With the Gemini voice credential loaded in the environment, update the default
Puck bank before starting a worker:

```sh
.venv/bin/python -m facetime.cues_tts --backend gemini --dry-run
.venv/bin/python -m facetime.cues_tts --backend gemini --workers 1
```

The renderer retains cached clips and generates only missing vocabulary. If using
`CUE_AUDIO_DIR`, pass that directory with `--out-dir` and use its existing backend,
voice and style. Restart the worker after rendering so its cached manifest is
reloaded. Voice assets stay under ignored `data/`; they are not committed.
