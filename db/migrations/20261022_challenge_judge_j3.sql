-- Judge j3 lenient (docs/challenge/CALIBRATION.md "j3 lenient"): the owner asked for a lenient, angle-robust judge and
-- no liveness challenge. The judge_thresholds row overrides challenge/judge/gates.py DEFAULT_THRESHOLDS, so every gate
-- value is set explicitly here (equal to the code defaults). classifier vetoes are emptied; liveness_enabled false
-- keeps the liveness challenge off (flip it to true to bring it back). jsonb merge: keys not listed keep their value.
-- knee_floor_margin 0.1 (torso lengths): knees_down now needs the knee at the floor line AND a measured knee angle below
-- knee_min_deg (no pivot heuristic), so a positive margin no longer rejects straight-legged planks.
-- Safe to run twice (no transaction wrapper needed).
update competition_config
   set value = value || '{"min_conf": 0.4, "leg_min_conf": 0.7, "frame_conf_frac": 0.6,
                          "knee_min_deg": 120, "knee_floor_margin": 0.1,
                          "hip_line_max_dev_deg": 30, "hip_pike_max_dev_deg": 40,
                          "depth_elbow_max_deg": 125, "depth_drop_max": 0.88,
                          "lockout_min_deg": 135, "incline_max_deg": 25, "decline_max_deg": 35,
                          "min_rep_s": 0.45, "max_cadence_rpm": 100,
                          "classifier_veto": [], "classifier_veto_substrings": [],
                          "liveness_enabled": false}'::jsonb,
       updated_by = 'migration:judge_j3', updated_at = now()
 where key = 'judge_thresholds' and jsonb_typeof(value) = 'object';
