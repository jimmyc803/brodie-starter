-- Judge j2 real-footage calibration (task 15, docs/challenge/CALIBRATION.md, CONTRACTS C7.c).
-- The 20261012 seed stored the whole j1 judge_thresholds dict (incl. knee_floor_margin 0.04, while the code default /
-- D-17 is 0.02), and that row overrides challenge/judge/gates.py DEFAULT_THRESHOLDS, so every calibrated gate value is
-- set explicitly here. jsonb merge: keys not listed (classifier / liveness / cue lists) keep their current value;
-- depth_margin (j1 only, replaced by depth_drop_max) is removed. Safe to run twice (no transaction wrapper needed).
update competition_config
   set value = (value - 'depth_margin') || '{"min_conf": 0.5, "frame_conf_frac": 0.9,
                                             "knee_min_deg": 150, "knee_floor_margin": 0.02,
                                             "hip_line_max_dev_deg": 17.5, "hip_pike_max_dev_deg": 20,
                                             "depth_elbow_max_deg": 100, "depth_drop_max": 0.75,
                                             "lockout_min_deg": 150, "incline_max_deg": 9, "decline_max_deg": 23,
                                             "min_rep_s": 0.8, "max_cadence_rpm": 60}'::jsonb,
       updated_by = 'migration:judge_j2', updated_at = now()
 where key = 'judge_thresholds' and jsonb_typeof(value) = 'object';

-- trigger function only; never callable by API roles
revoke all on function ch_stamp_frozen_at() from public, anon, authenticated;
