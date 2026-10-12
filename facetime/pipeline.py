"""Per-frame perception + policy shared by coach_agent.py (LiveKit), replay_local.py (mp4) and webcam_local.py.

Correction trigger: --trigger PATH (default data/models/trigger_lr.json when present, "none" = threshold rule); with a
trigger the Coach runs the classifier every frame and --thr only restricts which cue is said.
Rep counter: REP_PARAMS_V2 (RepCounter2 via rtcoach.coach.make_counter, default: the exercise signal mask, body-state
gate and settle rule of rtcoach.repcount2 for squats, pushups and lunges), REP_PARAMS_V2_PLAIN (--counter v2plain: the
counter exactly as it ran in the 2026-10-08 Mac tests, before the guards) or REP_PARAMS_E1 (--counter e1).

RGB frame -> short side 288 (aspect kept, no padding) -> MediaPipe pose (rtcoach.pose.Pose, VIDEO mode with
monotonic ms timestamps) -> rtcoach.coach.Coach.step(img, world, ok) for the current exercise. The Coach can be
swapped per exercise (set_exercise) or detached (rest periods); the pose model and the classifier persist.
Returns the coach's new events, the pose and classifier compute times, the rep count, a "moving" flag from the
rep counter's amplitude gate and the classifier's exercise probabilities whenever it ran (for auto detection).
The classifier is timed and tapped by wrapping the Classifier instance (no edits to src/rtcoach).

Strict judge (challenge, CONTRACTS C5): judge=True (default: on when env CHALLENGE_MODE=competition; replay/eval pass it)
builds a challenge.judge.runtime.JudgeRuntime for every push-up Coach and runs MediaPipe with num_poses=2 (primary person +
people count, rtcoach.pose). Each frame feeds FrameObs(t = t_ms / 1000, img, world, persons, aspect) to it, the Coach's
correction labels go to on_label, and every count increase calls on_rep; the result dict then carries
judge = {rep n: RepVerdict.event_fields()} for the reps counted on that frame (facetime.perception merges them into the rep
events). judge=False: nothing of this runs and the result has no 'judge' key.

INJECTION SEAM (judge_eval, tests): FramePipeline.process_landmarks(img, world, persons, t_ms, aspect) is everything after
pose estimation; process(rgb) = to_short_side + Pose + process_landmarks. Build the pipeline with pose_variant=None to skip
loading MediaPipe entirely (process() then raises); feeding recorded/synthetic landmarks through process_landmarks runs the
identical counter, Coach, visibility and judge code as live.
"""
import json, logging, os, time
import numpy as np, cv2
from rtcoach.pose import Pose
from rtcoach.coach import Coach
from rtcoach.model import Classifier
from rtcoach.exmap import LR2CLF, COUNTABLE
from rtcoach.curl_counter import CURL_NAMES
from facetime.visibility import Visibility
from facetime.probe import ArmRaise, TPose

log = logging.getLogger('pipeline')
REP_PARAMS_E1 = {"win_s": 4, "hi": 0.65, "lo": 0.35, "min_amp": 0.35, "smooth": 3, "min_period_s": 0.5, "hp_s": 4}   # E1 pose-PCA counter
REP_PARAMS_V2_PLAIN = {"v2": True}      # E1b RepCounter2 (rtcoach.repcount2): exercise hint only, held-out exact 0.84 vs 0.49 (the Mac-test counter)
# Demo guards (2026-10-09): select='mask' votes only over the signals that move in the exercise, gate=True needs the right body state
# (upright for squats and lunges, horizontal for pushups), settle=True needs 0.8 s of standing still before the first rep after a
# (re)start; jumping jacks are untouched (no mask, gate or settle). MM-Fit held-out exact 0.847 / within-1 0.918, delay unchanged.
# Further guards from device recordings: walk_vx=1.0 turns
# the squat gate off while the hips move sideways faster than 1 torso length/s (walking back from the phone counted 2 squats),
# first_mask=True lets the first lunge count only once a leg or torso tracker has fired (a hand to the face counted a lunge).
# Segment false starts 5 -> 2 (the two left are pose garbage while handling the phone), MM-Fit held-out exact 0.867 / within-1 0.918 unchanged.
REP_PARAMS_V2 = {"v2": True, "select": "mask", "gate": True, "settle": True, "walk_vx": 1.0, "first_mask": True}
REP_PARAMS = REP_PARAMS_V2
COUNTERS = {'v2': REP_PARAMS_V2, 'v2plain': REP_PARAMS_V2_PLAIN, 'e1': REP_PARAMS_E1}
import os as _os
# Live defaults = E3 operating point (A) (PREREG.md), except counts are spoken every rep in the demo (the benchmark
# used fives to match the QEVD coaches); per-label thresholds = stage C (fewer wrong cues). --params / --thr override.
# Demo UX deviation from (A): corrections at most every 8 s per label and 3 per set, praise every 8 s, counts may follow
# any cue after 0.3 s (the benchmark optimum speaks a correction every 3 s and swallowed the count words).
POLICY_DEFAULT = {"every": 3, "thr": 0.3, "k": 1, "cue_cooldown": 8, "gap": 3.0, "praise_after": 8, "ema": 0.7,
                  "max_cues_per_label": 3, "count_mode": "every", "count_min_gap": 0.3, "cue_prior": True,
                  "count_blocks_gap": False, "count_defer": True, "trigger_label_limits": True,
                  "side_mode": "both", "cue_mask": True,
                  # E7 pose-geometry side cues, only for the four one-sided stretches; tuned params = data/runs/e7/side_tune.json
                  # "best" (the module defaults, cooldown 10 s restarted by every other cue, never get to speak next to the trigger)
                  "side_rules": {"dwell_wrong": 1.0, "dwell_nograb": 2.0, "start_delay": 2.0, "cooldown": 5.0, "switch_quiet": 2.0, "smooth": 9, "max_per_rule": 3, "raise_thr": 0.0, "behind_thr": 0.05, "grab_thr": 0.5, "cross_thr": -0.25, "wy_thr": 0.5, "scale_win": 30}}
THR_DEFAULT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'src', 'rtcoach', 'thresholds_e3c.json')
# Learned correction trigger (E3b, rtcoach.trigger): decides WHEN to correct (Benchmark correction-F 0.421 vs 0.292 for the
# threshold rule); the per-label thresholds then only restrict WHICH cue is said. On by default when the model file exists.
TRIGGER_DEFAULT = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), 'data', 'models', 'trigger_lr.json')

def resolve_trigger(arg):
    """--trigger value -> loaded model or None. None/'auto' = TRIGGER_DEFAULT if it exists; 'none'/'off' = disabled; else a path."""
    if arg is None or arg == 'auto':
        path = TRIGGER_DEFAULT if _os.path.exists(TRIGGER_DEFAULT) else None
    elif str(arg).lower() in ('none', 'off', ''):
        path = None
    else:
        path = arg
        if not _os.path.exists(path): raise SystemExit(f'trigger model not found: {path}')
    if path is None: return None, None
    from rtcoach.trigger import load_model
    return load_model(path), path
SHORT_SIDE = 288
JUDGE_EXERCISES = ('pushups',)   # classifier classes the strict judge runs for

def judge_default():
    """The judge option's default: on for CHALLENGE_MODE=competition."""
    return os.environ.get('CHALLENGE_MODE', '').strip().lower() == 'competition'
FPS = 10
PLAIN = {'squats': 'squats', 'pushups': 'pushups', 'jumping jacks': 'jumping jacks', 'lunges': 'alternating forward lunges'}
PLAIN.update({name: 'bicep curls' for name in CURL_NAMES})
CLF2NAME = {v: k for k, v in sorted(LR2CLF.items())}; CLF2NAME.update({v: k for k, v in PLAIN.items()})   # classifier class -> spoken name

CLF2NAME['bicep curls'] = 'bicep curls'

def to_short_side(rgb, short=SHORT_SIDE):
    h, w = rgb.shape[:2]
    s = min(h, w)
    if s == short:
        return np.ascontiguousarray(rgb)
    f = short / s
    return cv2.resize(rgb, (max(1, round(w * f)), max(1, round(h * f))), interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_LINEAR)

def map_exercise(name, clf=None):
    """Plain demo name, LR2CLF key (what the transition says) or classifier class -> classifier class."""
    if name in PLAIN:
        return PLAIN[name]
    if name in LR2CLF:
        return LR2CLF[name]
    if clf is not None and name in clf.exs:
        return name
    raise ValueError(f'unknown exercise {name!r}; accepted: {", ".join(accepted_names())}')

def accepted_names():
    """Every name --plan / --exercise accept: the plain demo names and the LR2CLF keys."""
    return sorted(set(PLAIN) | set(LR2CLF))

def spoken_name(clf_class):
    return CLF2NAME.get(clf_class, clf_class)

class _TimedClassifier:
    """Proxy that times predict_many and keeps the last exercise-probability vector; the rest is forwarded."""
    def __init__(self, clf):
        self._clf = clf; self.last_ms = 0.0; self.n = 0; self.total_ms = 0.0; self.last_ex_probs = None; self.ex_seq = 0
    def __getattr__(self, k):
        return getattr(self._clf, k)
    def predict_many(self, X):
        t = time.perf_counter(); r = self._clf.predict_many(X)
        self.last_ms = (time.perf_counter() - t) * 1000; self.n += 1; self.total_ms += self.last_ms
        self.last_ex_probs = r[0][0]; self.ex_seq += 1
        return r

class FramePipeline:
    def __init__(self, model_path, exercise=None, pose_variant='full', params=None, thresholds=None, rep_params=REP_PARAMS, fps=FPS, trigger='auto', gesture_next=False,
                 judge=None, judge_thr=None, num_poses=None):
        """judge: None = judge_default() (CHALLENGE_MODE=competition). judge_thr: judge thresholds over DEFAULT_THRESHOLDS.
        num_poses: None = 2 with the judge on (people count), else 1. pose_variant=None: no pose model (landmark injection)."""
        self.judge_on = judge_default() if judge is None else bool(judge); self.judge_thr = judge_thr; self.judge = None
        self.num_poses = int(num_poses) if num_poses is not None else (2 if self.judge_on else 1)
        self._judged = 0; self.persons = 0
        self.clf = _TimedClassifier(Classifier(model_path)) if model_path else None
        self.params = dict(POLICY_DEFAULT, **(params or {})); self.rep_params = rep_params; self.fps = fps
        self.thresholds = thresholds if thresholds is not None else (json.load(open(THR_DEFAULT)) if _os.path.exists(THR_DEFAULT) else None)
        self.trigger, self.trigger_path = resolve_trigger(trigger)
        if self.trigger is not None:
            self.params['every'] = 1                   # the trigger is trained at a 1-frame stride: classifier every frame
        log.info('policy %s | thresholds %s | trigger %s', json.dumps(self.params, sort_keys=True), 'given' if thresholds is not None else THR_DEFAULT, self.trigger_path or 'off')
        self.coach = None; self.exercise = None; self.countable = False; self.armed = True
        if exercise:
            self.set_exercise(exercise)
        self.pose_variant = pose_variant
        self.pose = Pose(pose_variant, video=True, num_poses=self.num_poses) if pose_variant is not None else None
        self.t0 = time.monotonic(); self.last_ms = -1
        self.n = 0; self.n_ok = 0; self.pose_ms_sum = 0.0; self.clf_ms_sum = 0.0; self.last_landmarks = None
        self.vis = Visibility(fps); self.probe = ArmRaise(fps); self.was_visible = True
        self.gesture = None; self.set_gesture_next(gesture_next)

    def set_gesture_next(self, on):
        """--gesture-next: a T-pose held 1.5 s (facetime/probe.py TPose) sets r['gesture_next'] = True on the firing frame; off by
        default (no key, nothing observed). Settable after construction so the standby agent can switch it on per call."""
        if on and self.gesture is None: self.gesture = TPose(self.fps)
        elif not on: self.gesture = None

    def set_exercise(self, name, params=None, armed=True):
        """Fresh Coach for `name`; None = classifier only (exercise probabilities, no cues, no counter).
        armed=False: warm-up, only the rep counter is fed (lead-in plateau for the counter), the Coach's policy, classifier
        window and trigger are untouched until arm() so nothing is recorded as said and no gap is consumed."""
        ex = map_exercise(name, self.clf) if name else None
        self.exercise = ex; self.countable = ex in COUNTABLE; self.armed = armed
        p = dict(self.params, **(params or {}))
        # Curls have no trained form labels: do not emit another exercise's faults.
        curl = ex in CURL_NAMES
        self.coach = Coach(clf=None if curl else self.clf, exercise=ex, fps=self.fps, params=p,
                           rep_params=(self.rep_params if self.countable else None), thresholds=self.thresholds, trigger=None if curl else self.trigger)
        if not p.get('start_line', True):
            self.coach.last_say = 0.0            # the session script spoke instead; praise waits praise_after s as usual
        self.judge = self._build_judge(ex); self._judged = 0
        return ex

    def _build_judge(self, ex):
        if not (self.judge_on and ex in JUDGE_EXERCISES and self.coach is not None and self.coach.rc is not None):
            return None
        from challenge.judge.runtime import JudgeRuntime
        return JudgeRuntime(self.judge_thr)

    def arm(self):
        """End of the warm-up: from the next frame the Coach's policy runs (counter state carries over; the counter's settle
        window is extended from here, so steps while walking into place after the announcement are not reps)."""
        self.armed = True
        rc = self.coach.rc if self.coach is not None else None
        if rc is not None and hasattr(rc, 'resettle'): rc.resettle(keep=True)

    def detach(self):
        self.coach = None; self.exercise = None; self.countable = False; self.armed = True; self.judge = None; self._judged = 0

    def switch_pose(self, variant):
        """Swap the MediaPipe model (e.g. full -> lite when the box cannot hold 10 fps)."""
        old = self.pose; self.pose = Pose(variant, video=True, num_poses=self.num_poses); self.pose_variant = variant
        if old is not None: old.close()
        log.warning('pose model switched to %s', variant)

    def process(self, rgb, t_ms=None):
        """rgb: HxWx3 uint8 at any size. Returns dict(events, pose_ms, clf_ms, ok, count, moving, ex_probs, visible, vis_cues).
        t_ms: optional frame timestamp for MediaPipe's VIDEO mode (replays pass i * 1000 / FPS so runs are reproducible);
        live callers leave it None and the wall clock is used."""
        if self.pose is None:
            raise RuntimeError('FramePipeline was built without a pose model (pose_variant=None): feed landmarks via process_landmarks')
        img = to_short_side(rgb)
        ms = int((time.monotonic() - self.t0) * 1000) if t_ms is None else int(t_ms)
        if ms <= self.last_ms:                     # MediaPipe VIDEO mode needs strictly increasing timestamps
            ms = self.last_ms + 1
        self.last_ms = ms
        t = time.perf_counter(); a, w = self.pose(img, ms); pose_ms = (time.perf_counter() - t) * 1000
        persons = getattr(self.pose, 'persons', None)
        return self.process_landmarks(a, w, persons=persons, t_ms=ms, aspect=img.shape[1] / img.shape[0], pose_ms=pose_ms)

    def process_landmarks(self, a, w, persons=None, t_ms=None, aspect=None, pose_ms=0.0):
        """The injection seam (module docstring): one frame's pose -> the same result dict as process().
        a: (33,5) normalised image landmarks [x,y,z,visibility,presence] of the primary person or None (no pose);
        w: (33,3) world landmarks or None; persons: people in frame (None: 1 with a pose, 0 without);
        t_ms: frame time in ms (None: wall clock since construction); aspect: frame width / height (None: 16/9, judge only);
        pose_ms: pose compute time to report (0 for injected landmarks)."""
        ms = int((time.monotonic() - self.t0) * 1000) if t_ms is None else int(t_ms)
        ok = a is not None; self.last_landmarks = a                      # (33,5) normalised x,y,z,vis,pres or None (for --show overlays)
        if persons is None: persons = 1 if ok else 0
        self.persons = int(persons)
        if self.clf is not None: self.clf.last_ms = 0.0; seq0 = self.clf.ex_seq
        ev = []; step_ms = 0.0
        v = self.vis.update(a, ok)                                     # whole body in frame? (facetime/visibility.py)
        if v['visible'] and not self.was_visible:
            rc0 = self.coach.rc if self.coach is not None else None
            if rc0 is not None and hasattr(rc0, 'resettle'): rc0.resettle()   # back in view: stand still 0.8 s before the next rep counts
        self.was_visible = v['visible']
        if not v['visible']:
            pass                                                        # paused: no counting, no corrections, counter keeps its state
        elif self.coach is not None and not self.armed:                 # warm-up: counter only
            if self.coach.rc is not None: self.coach.rc.update(a if ok else None, w, ok)
        elif self.coach is not None:
            t = time.perf_counter(); ev = self.coach.step(a, w, ok); step_ms = (time.perf_counter() - t) * 1000
        clf_ms = self.clf.last_ms if self.clf is not None else 0.0
        ex_probs = self.clf.last_ex_probs if (self.clf is not None and self.clf.ex_seq != seq0) else None
        rc = self.coach.rc if self.coach is not None else None
        self.n += 1; self.n_ok += ok; self.pose_ms_sum += pose_ms; self.clf_ms_sum += clf_ms
        turning = getattr(rc, 'turning', None)         # RepCounter2: frame index of each counted rep's turning point
        probe_fire = self.probe.update(a, ok)
        r = dict(events=ev, pose_ms=pose_ms, clf_ms=clf_ms, step_ms=step_ms, ok=ok, ex_probs=ex_probs,
                 visible=v['visible'], vis_cues=v['cues'], full_body=v['full'], no_pose_s=v['no_pose_s'],
                 rep_imminent=self._rep_imminent(rc), probe_fire=probe_fire, probe_span=self.probe.confirm,   # frames the fire spanned: time the beep from the first
                 count=(rc.count if rc is not None else 0), moving=self._moving(rc),
                 turning_t=((turning[-1] / self.fps) if turning else None),
                 coach_t=(self.coach.i / self.fps if self.coach is not None else None))
        if self.gesture is not None and v['visible'] and self.gesture.observe(a, ok):   # not while the coach cannot see the whole body
            r['gesture_next'] = True                                   # the T-pose hold completed on this frame (--gesture-next)
        if self.judge is not None:
            r['persons'] = self.persons; r['judge_t'] = ms / 1000.0
            r['judge'] = self._judge_step(a, w, ok, ms / 1000.0, aspect, ev, rc)
        return r

    def _judge_step(self, a, w, ok, t_s, aspect, ev, rc):
        """Feed the judge this frame and its correction labels; verdicts for the reps counted on this frame: {n: event fields}."""
        from challenge.judge.metrics import FrameObs
        j = self.judge
        j.on_frame(FrameObs(t=t_s, img=(a if ok else None), world=(w if ok else None), persons=self.persons,
                            **({'aspect': float(aspect)} if aspect else {})))
        for e in ev:
            if e.get('intent') == 'correction' and e.get('why'): j.on_label(t_s, e['why'])
        out = {}
        c = rc.count if rc is not None else 0
        if c < self._judged: self._judged = 0
        for n in range(self._judged + 1, c + 1):
            out[n] = j.on_rep({'t': t_s, 'n': n}).event_fields()
        self._judged = c
        return out

    @staticmethod
    def _rep_imminent(rc):
        """A rep completion is about to be counted: a RepCounter2 tracker is active and already recovering from its extreme,
        or the time since the last count is >= 0.8 x the median rep period (after 3 reps). The session holds corrections
        and praise for up to 0.7 s while this is true so the count is spoken first."""
        if rc is None: return False
        try:
            if hasattr(rc, 'tr'):
                sel = rc.sel if isinstance(getattr(rc, 'sel', None), list) and rc.sel else list(rc.tr)
                for n in sel:
                    tr = rc.tr.get(n)
                    if tr is None or tr.state != 'active' or tr.R is None or not tr.buf: continue
                    side = (tr.buf[-1] - tr.R) * tr.sign
                    if tr.ext > 0 and side < 0.9 * tr.ext: return True
            ev = getattr(rc, 'events', None)
            if ev and len(ev) >= 3:
                per = float(np.median(np.diff(ev[-4:])))
                if rc.i - ev[-1] >= 0.8 * per: return True
        except Exception:
            return False
        return False

    @staticmethod
    def _moving(rc):
        """Amplitude gate: E1 sets .state once the window's amplitude passes min_amp; RepCounter2 has a tracker per
        signal, moving = any tracker has left its rest level."""
        if rc is None: return False
        if hasattr(rc, 'moving'): return rc.moving
        if hasattr(rc, 'tr'): return any(t.state in ('active', 'fired') for t in rc.tr.values())
        return getattr(rc, 'state', None) is not None

    def close(self):
        if self.pose is not None: self.pose.close()

def load_json_arg(s, default=None):
    if s is None: return default
    return json.loads(open(s).read()) if (len(s) < 400 and s.endswith('.json')) else json.loads(s)
