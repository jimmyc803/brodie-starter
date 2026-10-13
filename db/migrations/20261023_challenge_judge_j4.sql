-- Judge j4 launch leniency (docs/challenge/CALIBRATION.md "j4"): the owner asked that good reps actually count, that the
-- camera angle matter less (most callers will not prop the phone near the floor) while knee push-ups, tiny half reps
-- and standing / jiggling are still rejected. The judge_thresholds row overrides challenge/judge/gates.py
-- DEFAULT_THRESHOLDS, so every changed gate value is set explicitly here (equal to the code defaults). jsonb merge:
-- keys not listed keep their value.
-- knee_min_deg 145: j4 measures the knee with the view-independent world landmarks too, so a straight leg no longer
-- reads bent from a front or high camera; knees_down still needs the knee at the floor line.
-- hip_knee_min_deg 120 (new): the hip sag / pike gates are skipped when the legs are clearly bent (the shoulder-hip-ankle
-- line is not a body line then).
-- lockout_min_deg 130, decline_max_deg 65: a high or diagonal camera foreshortens the top elbow and tilts the image
-- support line.
-- Safe to run twice. Goes through ch_config_set. The deploy role may lack the privilege: then this is a notice and the
-- same values are applied with the service role (rpc ch_config_set).
do $$
begin
  perform ch_config_set('judge_thresholds',
         coalesce(ch_config_get() -> 'judge_thresholds', '{}'::jsonb)
         || '{"min_conf": 0.4, "leg_min_conf": 0.7, "frame_conf_frac": 0.6,
              "knee_min_deg": 145, "knee_floor_margin": 0.1, "hip_knee_min_deg": 120,
              "hip_line_max_dev_deg": 30, "hip_pike_max_dev_deg": 40,
              "depth_elbow_max_deg": 125, "depth_drop_max": 0.88,
              "lockout_min_deg": 130, "incline_max_deg": 25, "decline_max_deg": 65,
              "min_rep_s": 0.45, "max_cadence_rpm": 100,
              "classifier_veto": [], "classifier_veto_substrings": [],
              "liveness_enabled": false}'::jsonb,
         'migration:judge_j4', 'judge j4: owner asked for launch leniency, camera-angle robustness and counted good reps');
exception when insufficient_privilege then
  raise notice 'judge_j4: no privilege for ch_config_set; apply judge_thresholds with the service role';
end
$$;
