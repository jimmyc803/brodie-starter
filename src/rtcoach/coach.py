"""Streaming coach policy. Frame-synchronous at 10 fps; the classifier is evaluated every `every` frames on the last
`win` frames; the rep counter runs every frame. Emits events dict(t, text, intent, why)."""
import json, os, numpy as np
from .repcount import RepCounter
CUES=json.load(open(os.path.join(os.path.dirname(__file__),'cues.json')))
try: CUE_PRIOR=json.load(open(os.path.join(os.path.dirname(__file__),'cue_prior.json')))   # P(cue agrees with the coach | exercise), from train judge verdicts
except FileNotFoundError: CUE_PRIOR={}
PRAISE=["Nice work","Looking strong","Good pace","That's it","Keep it up","Great rhythm"]
COUNT_WORDS={i:w for i,w in enumerate("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split())}
DEFAULT=dict(every=5, thr=0.6, k=2, cue_cooldown=8.0, gap=2.5, praise_after=6.0, count_mode='every', count_every=5,
             ack_window=6.0, start_line=True, ema=0.5, max_cues_per_label=3, count_min_gap=0.8,
             count_blocks_gap=True,        # False: a spoken count does not reset the correction/praise gap (demo)
             count_defer=False,            # True: a count that cannot be said yet is said at the next allowed frame
             trigger_label_limits=False)   # True: trigger mode also applies cue_cooldown and max_cues_per_label
def make_counter(rep_params, exercise=None, fps=10):
    """rep_params {'v2': True, ...} -> RepCounter2 (E1b, exercise hint fixes the rest side; the other keys are RepCounter2 kwargs:
    the live default facetime.pipeline.REP_PARAMS_V2 adds select='mask', gate=True, settle=True, see rtcoach.repcount2);
    otherwise the E1 RepCounter."""
    from .curl_counter import CURL_NAMES, CurlCounter
    if exercise in CURL_NAMES:
        return CurlCounter(fps=fps)
    rp=dict(rep_params or {})
    if rp.pop('v2', False):
        from .repcount2 import RepCounter2
        return RepCounter2(fps=fps, exercise=exercise, **rp)
    return RepCounter(fps=fps, **rp)
class Coach:
    def __init__(self, clf=None, exercise=None, fps=10, params=None, rep_params=None, thresholds=None, trigger=None):
        """trigger: a loaded E3b model (rtcoach.trigger.load_model) replaces the threshold rule for WHEN to correct;
        the cue is still the highest-EMA fault label of the exercise."""
        self.p=dict(DEFAULT, **(params or {})); self.clf=clf; self.fps=fps
        self.ex=exercise; self.thr=thresholds or {}; self.trig=trigger; self.tstate=None; self.sstate=None; self.cstate=None
        self.rc=make_counter(rep_params, exercise, fps) if rep_params is not None else None
        self.img=[]; self.world=[]; self.ok=[]; self.dino=[]; self.i=-1; self.events=[]
        self.last_say=-1e9; self.last_any=-1e9; self.pending_count=None; self.last_cue={}; self.n_cue={}; self.ema=None; self.streak={}; self.last_fault=None
        self.ex_idx=None; self.lab_sel=None
        if clf is not None and exercise is not None: self.set_exercise(exercise)
    def set_exercise(self, ex):
        self.ex=ex
        if self.trig is not None:
            from .trigger import init_state
            self.tstate=init_state(self.trig, ex)
        if self.p.get('side_rules'):   # E7 pose-geometry rules for one-sided stretches (None for other exercises)
            from .side_rules import init_side_state
            self.sstate=init_side_state(ex, self.fps, self.p['side_rules'] if isinstance(self.p['side_rules'],dict) else None)
        if self.p.get('cadence_rules'):   # E8 cadence rules (quick feet, high knees, buttkickers, shoulder gators); dict of per-exercise params or True
            from .cadence_rules import init_cadence_state
            cr=self.p['cadence_rules']; self.cstate=init_cadence_state(ex, self.fps, cr.get(ex) if isinstance(cr,dict) else None)
        if self.clf is None: return
        self.ex_idx=self.clf.exs.index(ex) if ex in self.clf.exs else None
        self.lab_sel=[j for j,l in enumerate(self.clf.labs) if (self.ex_idx is None or self.clf.lab_ex[j]==self.ex_idx)]
    def say(self, t, text, intent, why=''):
        self.events.append(dict(t=round(t,2), text=text, intent=intent, why=why)); self.last_any=t
        if self.sstate is not None and not str(why).endswith((' - wrong side',' - no grab')):
            from .side_rules import note_said; note_said(self.sstate, t)
        if self.cstate is not None and not str(why).endswith((' - too slow',' - too fast',' - stepping')):
            from .cadence_rules import note_said as _cn; _cn(self.cstate, t)
        if intent=='count' and not self.p['count_blocks_gap']: return
        self.last_say=t
        if self.tstate is not None: self.tstate['last_say']=self.i   # the trigger's gap counts anything said
    def step(self, img, world, ok, dino=None, probs=None, rep=None, ex_probs=None):
        """Feed one frame. Returns list of new events.
        probs: optional precomputed label-probability vector for this frame (same classifier, same window); when given
        the feature build and the network call are skipped, so policy tuning replays the exact live logic from a cache.
        rep: None = run the live rep counter (if any); otherwise the cached counter output for this frame (0 = no rep,
        c = a rep just completed with running count c)."""
        self.i+=1; t=self.i/self.fps; n0=len(self.events); P=self.p
        self.img.append(img if ok else np.zeros((33,5),np.float32)); self.world.append(world if ok else np.zeros((33,3),np.float32)); self.ok.append(bool(ok))
        if dino is not None: self.dino.append(dino)
        for L in (self.img,self.world,self.ok,self.dino):
            if len(L)>60: del L[:len(L)-60]
        if P['start_line'] and self.i==int(1.0*self.fps): self.say(t,"Let's go",'start')
        # reps
        if self.rc is not None or rep is not None:
            c=self.rc.update(img if ok else None, world, ok) if rep is None else (rep or None)
            if c and (P['count_mode']=='every' or (P['count_mode']=='fives' and c%P['count_every']==0)): self.pending_count=c
            if self.pending_count is not None:
                if t-self.last_any>=P['count_min_gap']:
                    c=self.pending_count; self.pending_count=None
                    self.say(t, COUNT_WORDS.get(c,str(c)).capitalize() if P['count_mode']=='every' else f"That's {c}", 'count')
                elif not P['count_defer']: self.pending_count=None
        # side rules (E7): observe every detected frame; in 'both' mode speak when the gap allows
        if self.sstate is not None and img is not None and ok:
            from .side_rules import signals, classify, observe, active_rule, speak
            observe(self.sstate, classify(self.sstate, signals(self.sstate, img, world, ok)), t)
            if P.get('side_mode','override')=='both' and t-self.last_say>=P['gap']:
                c=speak(self.sstate, active_rule(self.sstate,t), t)
                if c: self.say(t, c[0], 'correction', c[1]); self.last_cue[c[1]]=t; self.n_cue[c[1]]=self.n_cue.get(c[1],0)+1
        if self.cstate is not None and img is not None and ok:   # E8: observe the cadence every detected frame
            from .cadence_rules import observe as _cobs; _cobs(self.cstate, img, world, ok, t)
        # form
        if self.clf is not None and self.i%P['every']==0 and len(self.img)>=15:
            if probs is None:
                X=self.clf.window_feats(np.array(self.img[-self.clf.win:]),np.array(self.world[-self.clf.win:]),np.array(self.ok[-self.clf.win:]),np.array(self.dino[-self.clf.win:]) if self.dino else None)
                pe,pl=self.clf.predict_many([X]); pl=pl[0]; pe=pe[0]
            else: pl=np.asarray(probs,np.float32); pe=None if ex_probs is None else np.asarray(ex_probs,np.float32)
            self.ema=pl if self.ema is None else P['ema']*self.ema+(1-P['ema'])*pl
            best=None
            if self.tstate is not None:
                from .trigger import predict_frame, decide, cue_text
                pt=predict_frame(self.tstate, pl, pe if pe is not None else np.zeros(len(self.tstate['exo']),np.float32))
                self._pre_say=self.tstate['last_say']; self._pre_corr=self.tstate['last_corr']
                fire,li=decide(self.tstate, pt, self.i)
                if fire:
                    faults=[j for j in (self.lab_sel or []) if CUES.get(self.clf.labs[j],{}).get('kind')=='fault' and CUES[self.clf.labs[j]].get('cue')]
                    above=[j for j in faults if (not self.thr) or self.ema[j]>self.thr.get(self.clf.labs[j],P['thr'])]   # stage C thresholds restrict the choice when loaded
                    if P.get('cue_prior'):   # cue choice = EMA x learned prior that this cue agrees with what coaches say for this exercise
                        pri=CUE_PRIOR.get(self.ex,{}); d=P.get('cue_prior_default',0.1)
                        cand=[(self.ema[j]*pri.get(CUES[self.clf.labs[j]]['cue'],d),j) for j in (above or faults)]
                        if cand: li=max(cand)[1]
                    elif self.thr:   # highest margin above its threshold
                        cand=[(self.ema[j]-self.thr.get(self.clf.labs[j],P['thr']),j) for j in above]
                        if cand: li=max(cand)[1]
                    if self.thr and not above and P.get('trigger_strict'):   # strict: no label above its threshold -> stay silent and give the gap back
                        fire=False
                    if fire and P['trigger_label_limits']:
                        l=self.clf.labs[li]
                        if t-self.last_cue.get(l,-1e9)<P['cue_cooldown'] or self.n_cue.get(l,0)>=P['max_cues_per_label']: fire=False
                    side=None
                    if fire and self.sstate is not None:   # E7 override: the active side rule replaces the cue text at the trigger's time
                        from .side_rules import override
                        side=override(self.sstate, t)
                    if fire and side is None and self.cstate is not None:   # E8 override: the active cadence rule
                        from .cadence_rules import override as _cov
                        side=_cov(self.cstate, t)
                    if fire and P.get('cue_mask') and not faults and side is None: fire=False   # no cue vocabulary for this exercise and no rule: stay silent
                    if not fire: self.tstate['last_say']=self._pre_say; self.tstate['last_corr']=self._pre_corr
                    if fire:
                        l=self.clf.labs[li]; text=cue_text(self.tstate, li)
                        if side: text,l=side
                        self.say(t, text, 'correction', l); self.last_cue[l]=t; self.n_cue[l]=self.n_cue.get(l,0)+1
                        if l in self.clf.labs: self.last_fault=(l,t)   # side-rule pseudo-labels have no classifier column to acknowledge
                best='trigger'   # skip the threshold rule below
            for j in (self.lab_sel or []) if best is None else []:
                l=self.clf.labs[j]; c=CUES.get(l,{})
                if c.get('kind')!='fault' or not c.get('cue'): continue
                th=self.thr.get(l,P['thr'])
                if self.ema[j]>th: self.streak[l]=self.streak.get(l,0)+1
                else: self.streak[l]=0
                sc=(self.ema[j]-th)*(CUE_PRIOR.get(self.ex,{}).get(c['cue'],P.get('cue_prior_default',0.1)) if P.get('cue_prior') else 1.0)
                if self.streak[l]>=P['k'] and (best is None or sc>best[1]): best=(l,sc)
            if best=='trigger': best=None
            if best and t-self.last_say>=P['gap']:
                l=best[0]
                if t-self.last_cue.get(l,-1e9)>=P['cue_cooldown'] and self.n_cue.get(l,0)<P['max_cues_per_label']:
                    self.say(t,CUES[l]['cue'],'correction',l); self.last_cue[l]=t; self.n_cue[l]=self.n_cue.get(l,0)+1; self.last_fault=(l,t)
            # acknowledge a fixed fault
            if self.last_fault and not best:
                l,tf=self.last_fault; j=self.clf.labs.index(l)
                if self.ema[j]<self.thr.get(l,P['thr'])*0.5 and t-tf<=P['ack_window'] and t-self.last_say>=P['gap']:
                    self.say(t,"That's it",'positive','ack'); self.last_fault=None
        if P['praise_after'] and t-self.last_say>=P['praise_after'] and t>3:
            self.say(t, PRAISE[(self.i//7)%len(PRAISE)], 'positive','idle')
        return self.events[n0:]
