# Judge calibration on real footage (task 15, judge j2)

Footage: 32 labelled clips in `judge_eval/clips` (gitignored, local only; labels in `judge_eval/labels.yaml`):
6 clean side-view, 10 off-angle, 2 bad light, 3 partial frame, 1 knees, 4 two people, 6 not horizontal. No real
half / sag / pike / no-lockout / replay footage exists yet, so those cheats are calibrated against the synthetic
suites only (`tests/challenge/test_judge_core.py`, `test_judge_runtime.py`, `python -m judge_eval.run --synthetic`).

Method: pose landmarks of every clip were cached once (scratchpad) and replayed through
`FramePipeline.process_landmarks` (same post-pose path as `judge_eval.run`). Every disagreement with a label was
checked on extracted frames with a skeleton overlay before deciding judge error vs label error. Final numbers come
from the real path: `python -m judge_eval.run --labels ... --clips-dir ... --bench`.
`tests/challenge/test_calibration_real.py` re-runs it wherever the clips exist and pins the achieved values.

## Result

| | j1 (before) | j2 (after) | ship goal |
|---|---|---|---|
| clean reps accepted (min(got, expected) / expected) | 3/30 = 10% | 26/30 = 86.7% | >= 90% (not yet) |
| cheat reps accepted (knees, two_people) | 0 | 0 | 0 |
| not_horizontal reps accepted | 0 | 0 | 0 |
| worst clean count error | 6 | 2 (px_8456661, rejected reps) | <= 1 (not yet) |
| latency p95 per frame (pose + judge) | - | 16.1 ms (p50 15.2) | < 50 ms |
| synthetic suite (`--synthetic`) | PASS | PASS (all cheats 0 accepted) | |

Clean per clip (expected / accepted / counted): 4964650 4/5/5, 4964649 4/3/3, 6022716 5/5/5, 6022762 5/5/5,
8456661 4/2/4 (2 x no_lockout), 4945123 8/7/8 (1 x no_lockout).

The 90% / <= 1 goal stays the target (judge_eval.run SHIP GATE). The six clean clips are too few to tune further
without overfitting; more clean side-view footage is needed. test_calibration_real pins 86% / 2 so a regression fails.
The gate numbers above are unchanged by the fix round (sag/pike independence, knee pivot).

### Count errors: judge, counter or label

- px_8456661 (error 2): rejected reps, not a miscount (4 of 4 counted). Reps 3 and 4 top out at 146.8 / 145.6 deg:
  the jacket sleeves hide the elbow. Kept clean (D-31: an honest hard case).
- px_4964649 (error 1): the counter is right. After the 2.4 s lockout the elbow series has three bottoms (4.7, 9.0,
  13.2 s) and the clip ends on the ascent at 15.5 s; the counter fires 3 times. The label says 4 ("4 conservative,
  5 if the judge credits the opening rep"), which appears to include the opening half rep. Label left unchanged (D-31).
- px_4964650 (+1): the opening half rep the label already allows.
- px_4945123 (error 1): 8 counted for 8 reps, so the count is right, but the counter's fire timing is off at a ~30 deg
  front camera. It misses the 5.9 s bottom, fires early in the 9.8 s and 12.2 s descents, and fires twice around
  12.8 s. The early fire at 12.2 s gives a window with no lockout, which is rejected. RepCounter2 is the shared,
  benchmark-tuned counter (QEVD / MM-Fit, PREREG), and the count itself is correct, so it was not changed here.

## Lockout (D-31)

Real clean lockouts read 145.6 - 177 deg (6022762 bounces through 1-2 frame tops at 152.6 / 152.9; 8456661 sleeves
145.6 - 150.6). The synthetic `no_lockout` cheat (140 deg commanded) reads up to 151.6 deg at noise sigma 0.02 (145.6
at 0.01, 142.8 at 0.005). The distributions overlap. Tried and rejected: world-landmark elbow angles, the far arm's
elbow (reads 133-150 at the bottom), and a longer median (5, 7) for the top (the cheat's max stayed at 151.2-151.6).

Decision D-31: `lockout_min_deg` 150. False rejects of honest users are worse than near-lockout leniency.
- Synthetic no_lockout must still be 0 accepted at sigma <= 0.01 (`test_zero_cheat_reps_accepted_at_high_noise`).
- Accepted residual: at sigma 0.02, 12/60 = 20% of synthetic 140 deg near-lockout reps pass, and the test bounds this
  at <= 25%. A 140 deg near-lockout under heavy noise is a minor form issue, not a scoring exploit. Half reps
  (depth) are unchanged: 0 accepted at every noise level.

## Thresholds (j2)

Clean = real clean side-view reps (plus synthetic clean where noted); cheat = real cheat clips and synthetic cheats.

| key | j1 | j2 | clean range measured | cheat range measured | margin clean / cheat |
|---|---|---|---|---|---|
| knee_min_deg | 160 | 150 | min knee 156.7 (clean), 153.7 (off-angle 8401382) | real knees 76-93; synthetic knees <= 142 | 6.7 / 8 |
| knee_floor_margin | 0.02 (seed row 0.04) | 0.02 | knee height of bent (< 160) knees >= 0.066 (4964649); straight knees ignored | synthetic knee on floor line ~0; real knees -0.08..0.005 | 0.046 / 0.02 |
| KNEE_CONTACT_MAX_DEG (metrics constant) | - (all knees) | 160 | knees at low knee height: 162.3-172 (4945123, 6022716 at 0.013) | synthetic knee-to-floor fault knee 155.1-157.2 | 2.3 / 2.8 (thin) |
| hip_line_max_dev_deg (sag) | 15 | 17.5 | max sag +15.88 (6022716) | synthetic sag >= 19.6 | 1.6 / 2.1 |
| hip_pike_max_dev_deg (new) | (15) | 20 | pike -17.39 in reps (walk-in excluded, below) | synthetic pike <= -23.7 | 2.6 / 3.7 |
| depth_elbow_max_deg | 90 | 100 | max bottom elbow 96.41 (6022716, ~90 deg on frames) | synthetic half rep 125 | 3.6 / 25 |
| depth_drop_max (new, replaces depth_margin) | - | 0.75 | max ratio 0.685 (6022716) | synthetic 125 deg half rep 0.85 (min 0.733 at sigma 0.02) | 0.065 / 0.017 |
| lockout_min_deg | 160 | 150 (D-31) | tops 145.6-177 (3 below 150) | synthetic 140 deg: <= 145.6 at sigma 0.01, <= 151.6 at 0.02 | overlap, see D-31 |
| incline_max_deg (new) | - | 9 | support tilt clean -19.2..-4.2; kettlebell handles +5.6..+6.0 | incline clips +12.5..+15.6 | 3 / 3.5 |
| decline_max_deg (new) | - | 23 | clean down to -19.2 | decline (8171386) -27.7..-40.6 | 3.8 / 4.7 |
| min_conf, frame_conf_frac, min_rep_s, max_cadence_rpm | 0.5, 0.9, 0.8, 60 | unchanged | | | |

`depth_margin` (shoulder-elbow gap) was removed. Real clean bottoms read gaps from -0.26 to +0.33 torso lengths
(camera height and arm length move the elbow), and 15 of 30 clean reps were above 0.05. `shoulder_elbow_gap` is still
stored.

Near-threshold synthetic pass rates (50 reps; cases relative to the thresholds): sigma 0.01: clean 1.00,
lockout-10 0.00, lockout-5 0.10, depth+5 0.04, depth+10 0.00. sigma 0.02: clean 1.00, lockout-10 0.14,
lockout-5 0.30, depth+5 0.28, depth+10 0.04. The depth+5 bound at sigma 0.02 was raised from 0.20 to 0.30 because the
gap gate is gone (j1 measured 0.14).

## Metric changes (challenge/judge/metrics.py)

- Judged frames: RepCounter2 fires near the bottom, so each window held the previous rep's lockout hold and, for
  the first rep, the whole setup (kneeling down, walking into the plank). The first rep is now judged from its last
  lockout before the descent. Later reps are judged on the previous ascent up to its lockout plus this rep's descent
  (the lockout hold in between is skipped). Lockout, person count and side still use the whole window.
- Walk-in pike: in the first rep only, the pike side of the hip line counts from the first frame at or above
  -hip_pike_max_dev_deg, so hips still coming down from walking into the plank (px_8456661 rep 1: -20..-23 deg in the
  first 0.6 s of the descent) are not a pike. If the hips never reach the limit, every frame counts, so a piked first
  rep still fails. The sag side always uses every frame. A later rep with the same hip path is still rejected
  (test_first_rep_walk_in_pike_ignored_later_pike_kept).
- Depth: shoulder_wrist_drop is now the bottom / lockout ratio of the shoulder's height above the wrist.
- Knee floor contact only from bent knees (< 160 deg). With straight legs, the wrist-ankle line is not the floor
  under the knee (low camera perspective in 4945123, kettlebell handles in cm_interval_pushups).
- Sag and pike are judged independently (fix round). The 2nd-highest dev (sag side) and 2nd-lowest dev (pike side)
  are each compared with their own limit, and the stored max_hip_line_dev_deg is the side that exceeds its limit
  more. Before, the side with the larger |dev| was kept, so an allowed -19.5 deg pike hid a sustained +18.5 deg sag
  (test_allowed_pike_cannot_mask_sustained_sag). Only one column is stored, so a rejudge with different hip limits
  judges the stored side only.
- Knee pivot (fix round): knee_floor_contact is also true when the knee is the pivot of the rep, whatever the knee
  angle. A knee push-up with the foot raised reads 161.7 deg at the knee, so the < 160 deg rule alone scored it 5/5.
  Over the judged frames (3-frame moving average) the least-squares slope of knee height vs hip height (image
  vertical, torso lengths) is ~0.5 in a plank (the knee rides on the ankle-hip line) and ~0 or negative with the
  knee on the floor. Pivot iff slope < 0.2 (KNEE_PIVOT_SLOPE), hip travel p90-p10 >= 0.1 torso, >= 6 frames, and
  the knee's 2nd-lowest height above the wrist-ankle line < 0.1 torso (KNEE_PIVOT_MAX_KF; without it, sigma 0.02
  jitter flagged 6-12% of synthetic plank reps at depth 90-105, now 0/150 at every depth and noise).
  Real slopes: clean side-view 0.36-0.75 (one rep 0.26), cm_interval (kettlebells, knee 161-166) 0.50-0.63, the
  knees clip -0.83..-0.19 (all 4 reps flagged). Margins: 0.16 clean / 0.39 knees. Real replay after the fix: clean
  acceptance and counts unchanged on every clip (26/30); only reason mixes on already-rejected off-angle / two-people
  reps moved between hips_sag and hips_pike.
  Synthetic knees-on-floor at knee 161.7 deg: 0/60 accepted at noise 0 and 0.01, 6/60 at 0.02 (test bound 15%).

### Residuals (synthetic)

| case | sigma 0.01 | sigma 0.02 |
|---|---|---|
| no_lockout 140 deg | 0/60 | 12/60 (bound 25%, D-31) |
| knees on floor, knee 161.7 deg | 0/60 | 6/60 (bound 15%) |
| depth +5 deg (near miss) | 4% | 28% (bound 30%) |
- Incline / decline: median wrist-ankle support-line tilt over the judged frames, folded into torso_ok.
- src/rtcoach/video.py: the ffprobe size parse now uses JSON. On this ffprobe build the CSV output had blank
  stream-group lines, so `read_frames` crashed on every clip.

## Labels

All labels were re-checked on frames. Per D-31 no label was changed. Notes:
- px_8456661 (clean): sleeves hide the elbows; the lockouts look complete by eye but read 145-151 deg.
- px_6022762 (clean): reps 3 and 4 reach lockout for only 1-2 frames at 10 fps; accepted at 150.
- px_4964649 (clean): the elbow series shows 3 full reps after 2.4 s, while the label says 4 (see count errors).
- px_4964650: the +1 counted rep is the opening half rep the label already allows.

## Zero-rep clips

RepCounter2 decides whether a rep happened, and these clips never arm it:
- px_6970183 (partial_frame): ankles outside the frame (normalised x ~1.13, visibility 0.04-0.23).
- px_4804790 (not_horizontal): incline on a ledge with the ankles below the frame (y ~1.12).
Every off-angle clip counts reps (3-10 per clip). 9 of 10 are rejected, mostly not_horizontal because their support
line reads -25..-43 deg from the camera angle. px_8435123 is accepted 3/4.

## Rejudge

`torso_ok` (incline / decline) and `knee_floor_contact` are decided when the metrics are computed, so a rejudge
cannot change them. j1 rows stored a different `shoulder_wrist_drop` and other judged frames, so
`scripts/rejudge.py` (and `/admin/rejudge`) only re-judge reps whose judge_version family (before the first '.')
is the current JUDGE_VERSION. Other reps are kept as stored and reported as "skipped".
