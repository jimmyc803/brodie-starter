# Judge calibration on real footage (task 15, judge j2)

Footage: 32 labelled clips in `judge_eval/clips` (gitignored, local only; labels in `judge_eval/labels.yaml`):
6 clean side-view, 10 off-angle, 2 bad light, 3 partial frame, 1 knees, 4 two people, 6 not horizontal. No real
half / sag / pike / no-lockout / replay footage exists yet, so those cheats are calibrated against the synthetic
suites only (`tests/challenge/test_judge_core.py`, `test_judge_runtime.py`, `python -m judge_eval.run --synthetic`).

Method: pose landmarks of every clip were cached once (scratchpad) and replayed through
`FramePipeline.process_landmarks` (same post-pose path as `judge_eval.run`). Every disagreement with a label was
checked on extracted frames with a skeleton overlay before deciding judge error vs label error. Final numbers come
from the real path: `python -m judge_eval.run --labels ... --clips-dir ... --bench`.
`judge_eval/check_real_clips.py` (run explicitly as a ship-gate step; fails if the clips are missing) re-runs it and pins the achieved values.

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
without overfitting; more clean side-view footage is needed. check_real_clips pins 86% / 2 so a regression fails.
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
- Knee pivot (fix round, revised in fix round 2): knee_floor_contact is also true when the knee is planted on the
  floor, whatever the knee angle. A knee push-up with the foot raised reads 161.7 deg at the knee, so the < 160 deg
  rule alone scored it 5/5. Over the judged frames (3-frame moving average) the least-squares slope of knee height vs
  hip height is ~0.5 in a plank (the knee rides on the ankle-hip line) and ~0 or negative with the knee on the floor.
  Heights are image vertical from the median ankle in one per-rep scale (median torso length), so moving the body in
  the frame changes nothing (fix round 2: per-frame torso division made the slope placement-dependent, e.g. hip_offset
  0.05, depth 90, sigma 0.02, seed 0 flipped knees_down -> accepted when shifted up 0.3; test_verdicts_invariant_to_
  body_placement_in_frame). Rule: only a knee whose 2nd-lowest height above the wrist-ankle line is < 0.1 torso
  (KNEE_PIVOT_MAX_KF) can be planted; it is planted iff slope < 0.2 (KNEE_PIVOT_SLOPE) or there is no plank evidence:
  < 6 frames or hip travel (range of the smoothed hip height) < 0.2 torso (KNEE_PIVOT_MIN_HIP). Fix round 2: before,
  missing evidence counted as "not planted", so knees planted at 160.1 deg with stationary hips (torso pivoting at the
  hip) or 0.022-torso hip travel passed 5/5 (test_planted_knees_with_little_hip_motion_rejected). A static test (knee
  height vs the person's own ankle / the ankle-hip chord) was measured and rejected: on real clean side-view clips the
  knee sits from 0.06 torso below to 0.16 above the ankle in the image and the hip only 0.05-0.43 above it, overlapping
  a planted knee, so only the motion evidence separates. The knee angle stays a soft factor only through the bent-knee
  floor-line rule (kc).
  Real (judged frames, knee near the line): clean slopes 0.46-0.72 (margin 0.26), hip travel >= 0.26 (margin 0.06,
  thin); cm_interval (kettlebells, knee 161-167, floor-line height -0.06) slopes 0.58-0.62; the knees clip -0.94..-0.73
  (all 4 reps flagged). Real replay after fix round 2: clean acceptance and counts unchanged on every clip (26/30), no
  clean rep flagged; latency p95 17.2 ms (machine shared with other test runs).
  Synthetic false contact on planks (5 seeds x 6 bodies/sides = 150 reps per case: depth 75/100/105, 1.5 s bottom
  hold, hip offset +-0.05, 1 s reps): 0 at sigma 0 and 0.01; at 0.02 only the 1.5 s bottom hold, 1/150.
- Incline / decline: median wrist-ankle support-line tilt over the judged frames, folded into torso_ok.
- src/rtcoach/video.py: the ffprobe size parse now uses JSON. On this ffprobe build the CSV output had blank
  stream-group lines, so `read_frames` crashed on every clip.

### Residuals (synthetic, accepted cheat reps)

| case | sigma 0.01 | sigma 0.02 |
|---|---|---|
| no_lockout 140 deg | 0/60 | 12/60 (bound 25%, D-31) |
| knees on floor, knee 161.7 deg | 0/150 | 6/150 (test: 0/60, bound 10%) |
| knees planted 160.1 deg, stationary hips | 0/150 | 0/150 (test bound 10%) |
| knees planted 160.1 deg, hip motion x0.1 / x0.3 | 0/150 / 0/150 | 0/150 / 6/150 (test 3/60, bound 10%) |
| depth +5 deg (near miss) | 4% | 28% (bound 30%) |

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

## j3 lenient (owner decision, 2026-10-13)

The owner's first real call scored 0/34 under j2. 25 of the reps failed on gates, and the other 9 failed only because
of liveness_fail. The owner asked for these changes: no liveness "cheater test", acceptance from more camera angles,
no need to prop the phone close to the floor, and leniency in general. JUDGE_VERSION is now "j3", and `scripts/rejudge.py`
re-judges j2 and j3 rows (`REJUDGE_FAMILIES`). j2 metrics are a stricter reading of the same quantities.

Liveness. The challenge is off unless `judge_thresholds.liveness_enabled` is true. The default is false, and migration
20261022 also sets it to false. When it is off, the controller starts no challenge, plays no challenge_* cues, opens no
window and voids no reps. Commits carry `liveness_result = 'skipped'`, which ch_commit_reps treats as neutral because it
voids only on 'fail'. The liveness code and its tests stay in place, and the tests turn it on explicitly.

Gates and metrics (challenge/judge/gates.py, metrics.py):
- Per-signal keypoints. Each signal needs only its own landmarks. not_in_frame now means only that the upper body
  (shoulder, elbow, wrist on either side) is unmeasurable. Missing hips, knees or ankles never reject a rep.
  `frame_conf_frac` is the share of judged frames in which an arm is measurable.
- `leg_min_conf` is 0.7. A knee or ankle counts only at this confidence or higher. MediaPipe extrapolates legs that
  are outside the frame at about 0.4-0.6, and those guesses caused a false knees_down on px_10280888.
- Hip line. It uses shoulder-hip-ankle when the ankle is measurable and shoulder-hip-knee otherwise. Only clear sag
  (more than 30 deg) or pike (more than 40 deg) is rejected.
- knees_down requires both a knee at the floor line and a measured knee angle below `knee_min_deg` (120). The knee-pivot
  heuristic is gone. A straight-legged plank is never knees_down, and neither is a plank with the legs out of frame.
- Depth. A rep is deep if the better side's elbow is at or below `depth_elbow_max_deg` (125), or if the
  shoulder-wrist drop ratio is at or below `depth_drop_max` (0.88). The live DB value of 0.92 combined with the OR rule
  accepted 150-deg bends on the synthetic suite (23/60). 0.88 accepts 125 deg, and sometimes 130-135 deg, but never
  150 deg.
- Incline and decline use the wrist-to-ankle support line in MediaPipe world landmarks, which is metric and does not
  depend on camera perspective. The image line is only a fallback for clips without world landmarks. The limits are
  25 deg incline and 35 deg decline. Under j2 the image line read -25..-43 deg on off-angle clips.
- Lockout is 135 deg. too_fast fires only on clear bouncing (under 0.45 s, or a cadence above 100 rpm). Classifier
  vetoes are empty. multiple_people is unchanged.

Owner call rejudge, read-only from the stored j2 metrics (`reps`, last 3 hours): 0/34 before, 26/34 after, both with the
code defaults and with the live DB config. Of the 8 still rejected, 4 are setup or junk frames (frame_conf 0.12-0.47,
hip line -132/-82). The others are one rep with hips at -97 and knee 81, one with the torso not horizontal, one at
elbow 128 with drop 0.96, and one with top 125 that is not horizontal. Live j3 metrics (per-signal keypoints) are at
least as lenient as this rejudge, which uses stricter j2 metrics.

Real clips (`judge_eval.run`, j2 then j3):

| | j2 | j3 |
|---|---|---|
| clean reps accepted | 26/30 = 86.7% | 29/30 = 93.3% (ship gate met) |
| worst clean count error | 2 | 1 |
| off_angle reps accepted (44 expected) | 3 | 31 |
| bad_light | - | 8/10 |
| partial_frame | - | 6/15 (counter arms on few reps) |
| knees, two_people accepted | 0 | 0 |
| not_horizontal reps accepted | 0 | 8/12 (moderate inclines, by design) |

`judge_eval/check_real_clips.py` now pins clean at 93% / 1 and off_angle at 31 or more accepted, and
not_horizontal at 8 or fewer accepted. not_horizontal is no longer a never-accept category.
The default synthetic suite (`--synthetic`) now accepts some synthetic cheats by design, such as the 140-150 deg
"half" reps near the boundary and inclines. The mechanism tests and the synthetic ship-gate test pin the j2 values
explicitly (`STRICT` / `STRICT_THR`).

Known trade-off: a classic knee push-up with flat shins reads 140-160 deg at the knee and passes knee_min 120. The real
knees clip (about 90 deg) is caught. Raising `knee_min_deg` in the DB, for example to 150, catches more of these but
starts flagging bent-leg planks.

DB config (competition_config.judge_thresholds). The live row was set by hand to j3-like values. Applying migration
`db/migrations/20261022_challenge_judge_j3.sql` (not yet applied) aligns it with the code defaults: it adds
leg_min_conf 0.7 and liveness_enabled false, changes depth to 125 / 0.88 (from 120 / 0.92), and changes
knee_floor_margin to 0.1 (from -1, which turns knees_down off completely).

## j4 launch leniency (owner decision, 2026-10-13)

The owner asked for this before the public launch: good reps must count, the camera angle should matter less (most
callers will not prop the phone near the floor), and obvious non-push-ups (knee push-ups, tiny half reps, standing or
jiggling) must still be rejected. JUDGE_VERSION is now "j4". `REJUDGE_FAMILIES` is j2, j3 and j4. j3 metrics are a
stricter reading than j4 metrics, so a rejudge never accepts more than j4 would have measured live. The one exception
is the bent-leg hip skip below.

Counting at the live frame rate (facetime/pipeline.py). Live EC2 processes 4-8 fps, but RepCounter2 indexes frames on a
fixed 10 fps clock (smoothing, 0.8 s minimum period, plateaus). At 4 fps a 0.9 s rep looked like 0.36 s, and a synthetic
set of 8 counted 1. FramePipeline now resamples the landmark stream onto the 10 fps counter clock. A gap of up to 1 s
between frames is filled with linearly interpolated landmarks (a fractional accumulator keeps the tick rate exact).
Longer gaps, an exercise switch, and `resample=False` feed only the real frame. The judge sees the same interpolated
ticks. Perception spreads the service time over the invented counter indices, so `turning_t` and `lag_s` stay set.

Gates and metrics (challenge/judge/gates.py, metrics.py):
- World landmarks are used for the hip line, knee and lockout. MediaPipe world landmarks are metric and 3-D, so their
  angles do not depend on the view. Hip deviation is the image and world readings combined: the smaller magnitude when
  they agree in sign, and 0 when they disagree (a bend that only the image shows is perspective). The knee uses the
  world angle when it is straighter than the image angle by more than 15 deg (a foreshortened leg), and the image angle
  otherwise. top_elbow_deg is the larger of the image and world 2nd-highest values (a foreshortened forearm).
- `hip_knee_min_deg` 120 is new. The hip sag/pike gates are skipped when min_knee_deg < 120: with clearly bent legs the
  shoulder-hip-ankle line is not a body line. A knee push-up is still caught by knees_down, which needs floor contact
  and a bent knee.
- `knee_min_deg` 145 (was 120) catches more flat-shin knee push-ups (synthetic ~141 deg: 4/6 still accepted at
  default thresholds, 0/6 with 150). It is safe now because a foreshortened straight leg reads straight in the world.
- `lockout_min_deg` 130 (was 135). `decline_max_deg` 65 (was 35): the image support line tilts with a raised camera.
- Cues (challenge/judge/cues.py `CUE_PRIORITY`, runtime.py). The spoken reason is the most useful correction, not the C5
  storage order: multiple_people, not_in_frame, knees_down, too_shallow ("Lower!"), no_lockout, hips, then
  not_horizontal last. `cue_repeat_gap_s` 10 (new) means the same cue is spoken at most once per 10 s, on top of
  `cue_min_gap_s` 4 between any two cues. A caller repeating one fault hears it once instead of every other rep.

Owner calls, read-only rejudge of the stored metrics (liveness_fail dropped, j3 then j4): owner call 14aa 26 then 27
out of 34; 0dee 16 then 17 out of 31; d8ef 2 then 2 out of 6; 46ac 4 then 4 out of 6. On 14aa the newly accepted rep is
rep 8 (hips -97 with knee 81 mid-set, a bent-leg reading). The 7 still rejected are correct: rep 1 is setup, reps 2, 3
and 27 are junk frames, rep 33 is shallow (elbow 128, drop 0.96), and rep 34 has top 125 and is not horizontal. Rep 32
(torso_ok false under the stricter j2 torso test) is probably valid, but a rejudge cannot change torso_ok. On 0dee the
newly accepted rep is rep 22 (top 133). Reps 18 and 19 (pike -50/-45 with straight knees) may be view-inflated, but only
live j4 metrics (world agreement) can tell. The rest are setup, end-of-set junk or double fires. Live j4 metrics are
at least as lenient as these rejudge numbers, which use the stricter stored metrics.

Real clips (cached landmarks replayed through FramePipeline.process_landmarks; j3, then j4 with resampling):

| | j3 @10 | j4 @10 | j3 @6 | j4 @6 | j3 @4 | j4 @4 |
|---|---|---|---|---|---|---|
| clean accepted | 29/30 | 29/30 | 29/29 | 29/30 | 28/28 | 29/29 |
| off_angle accepted (44 expected) | 31 | 36 | 28 | 34 | 21 | 34 |
| partial_frame accepted | 6/7 | 7/7 | 9/9 | 9/9 | 10/10 | 11/11 |
| bad_light accepted | 8/10 | 8/10 | 8/9 | 7/8 | 8/9 | 8/8 |
| knees accepted | 0 | 0 | 0 | 0 | 1 | 0 |
| two_people accepted | 0 | 0 | 0 | 1 | 1 | 0 |
| not_horizontal accepted | 8/12 | 8/12 | 9/13 | 10/13 | 10/12 | 12/13 |

`judge_eval/check_real_clips.py` (10 fps, the full decode path) passes, and it now pins off_angle at 36 or more.

Synthetic camera sweep (`synth_pushups(camera=(yaw, pitch))`, 6 reps at 10 and 4 fps). Clean reps are now accepted 6/6
for every yaw from 0 to 90 (side to head-on) and every pitch from 0 to 50. Under j3, clean reps were rejected as
not_horizontal at yaw >= 45 with pitch 50, and at yaw >= 75 with pitch 35. Half reps at 140 deg are still rejected from
the side and from raised side or diagonal cameras (tests/challenge/test_judge_j4.py).

Residuals:
- A raised oblique camera (pitch >= 35 at yaw 45-90) foreshortens the image elbow, so 140-deg half reps can pass.
- A raised camera behind the feet (negative yaw, pitch >= 20) counts nothing. The world torso then looks upright to
  RepCounter2's prone gate, and loosening that gate would let standing callers count.
- On px_6980138 (burpees with an undetected second person), one rep is accepted at 6 fps.
- not_horizontal acceptance grows at low fps (12/13 at 4 fps). The pin of 8 or fewer is at 10 fps.

DB config: migration `db/migrations/20261023_challenge_judge_j4.sql` (not yet applied) sets knee_min_deg 145,
hip_knee_min_deg 120, lockout_min_deg 130 and decline_max_deg 65, along with the unchanged gate values.
cue_repeat_gap_s comes from the code default.
