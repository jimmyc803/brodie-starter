-- Judge j5 front-view depth (docs/challenge/CALIBRATION.md "j5", D-45): the owner asked that a phone standing in
-- front of the person doing push-ups work too, not only side-on. Clean reps already counted from every front angle;
-- the problem was the other direction. From a raised front phone, perspective shrinks the shoulder's travel in the
-- image, so a half rep's shoulder_wrist_drop read "deep" and 5 of 6 synthetic half reps were ACCEPTED at yaw 90 /
-- pitch 35. j5 reads the depth elbow from the view-independent world landmarks when the image angle is foreshortened,
-- and `depth_elbow_veto_deg` (new, 10) stops the drop from passing a rep whose elbow is that far past the depth limit:
-- a straight arm is not a push-up, whatever the camera makes the shoulder look like.
-- Only this one key is added; every other value is j4's and is restated so the row stays explicit (the judge_thresholds
-- row overrides challenge/judge/gates.py DEFAULT_THRESHOLDS; keys not listed keep their value). A missing key already
-- falls back to the code default, so the veto is live with or without this migration - it is here so the owner's row
-- says what the judge is doing.
-- Safe to run twice. Goes through ch_config_set. The deploy role may lack the privilege: then this is a notice and the
-- same values are applied with the service role (rpc ch_config_set).
do $$
begin
  perform ch_config_set('judge_thresholds',
         coalesce(ch_config_get() -> 'judge_thresholds', '{}'::jsonb)
         || '{"min_conf": 0.4, "leg_min_conf": 0.7, "frame_conf_frac": 0.6,
              "knee_min_deg": 145, "knee_floor_margin": 0.1, "hip_knee_min_deg": 120,
              "hip_line_max_dev_deg": 30, "hip_pike_max_dev_deg": 40,
              "depth_elbow_max_deg": 125, "depth_drop_max": 0.88, "depth_elbow_veto_deg": 10,
              "lockout_min_deg": 130, "incline_max_deg": 25, "decline_max_deg": 65,
              "min_rep_s": 0.45, "max_cadence_rpm": 100,
              "classifier_veto": [], "classifier_veto_substrings": [],
              "liveness_enabled": false}'::jsonb,
         'migration:judge_j5', 'judge j5: front-view depth, a straight arm is not passed by the shoulder drop (D-45)');
exception when insufficient_privilege then
  raise notice 'judge_j5: no privilege for ch_config_set; apply judge_thresholds with the service role';
end
$$;
