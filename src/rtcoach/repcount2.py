"""Online rep counter v2 (E1b): a bank of 1-D pose signals, one rest-anchored hysteresis tracker per signal that fires
at the rep's active turning point, and a consensus over the trackers with the largest rep amplitude.

Interface (same as RepCounter): update(img, world, ok) -> new count when a rep completes on this frame, else None.
Attributes: count, events (frame indices of the fired counts), turning (frame index of each counted rep's turning point).
Optional exercise=<name> fixes the rest side of the signals that are known for that exercise and its minimum rep period.

Why this shape: inside MM-Fit's labelled bounds the label equals the number of active extremes (squat bottoms,
elbows-bent troughs, wrists-up peaks); rest-side extremes are one fewer because a set starts and ends on a rest plateau.
A tracker therefore keeps a rest level (the pre-set plateau, then the level the signal returns to between reps), goes
'active' when the signal leaves it by more than the entry amplitude, and fires as soon as the signal has recovered a
margin from its running extreme, 1 to 3 frames after the turning point. An extreme that is held for longer than
`max_hold_s` is a new resting position, not a rep (people step into position before a set), and after a few reps a
descent much slower than the set's rhythm is not a rep either (bending down after the set). The counter's count follows
the median count of the `top_k` trackers ranked by rep amplitude (times a ramp over the first reps and a recency decay),
so no exercise name is needed, one bad signal cannot add or lose a rep, and the count lands when the median tracker fires.

Demo guards (2026-10-09, after the Mac device tests counted arm raises, posture shifts and standing as reps):
- select='mask': for squats and pushups the vote runs only over the signals that physically move in that exercise (MASK;
  live names are mapped by ALIAS) and the median is taken over the best mask_top_k (3) trackers, so an arm raise cannot
  win a squat vote and two of the three best signals must agree. Other exercises keep the full top-5 vote.
- gate=True: a per-frame body-state precondition (body_state / gate_ok): squats and lunges need the world torso within
  about 53 deg of vertical and no wrist higher than 0.35 torso above the nose; pushups need the torso near horizontal
  (world uprightness < 0.6, or the image torso line > 60 deg from vertical). After `gate_off_s` of a false precondition
  the counter stops feeding the trackers and resets them; `gate_on_s` of a true one re-arms them on the new posture
  (for exercises without the settle rule with a provisional rest level after seed_s, so the first pushup after lying down
  is tracked at once), so a rep whose descent started in the wrong body state never exists. Jumping jacks have no gate.
- settle=True (SETTLE exercises only): for settle_max_s after the counter starts, after a gate re-arm and after resettle() (the pipeline calls
  it when the whole body comes back into view) a tracker's rep counts only if its rest level came from a real plateau
  (plateau_s = 0.8 s of the smoothed signal inside plateau_eps) and not from the median fallback it uses when the signal
  is already moving, so steps while walking into place are rejected ('anchor') and the first rep needs 0.8 s of standing
  still before it. A rep that started from a true rest and is followed by a pause at the top is kept.
Further guards (from device recordings):
- walk_vx=1.0 (WALK_EX, squats only): while the hip centre moves sideways faster than walk_vx image-torso lengths per second
  (walking back from the phone reached 1.2 to 1.8, squats and jacks stay under 0.7) the upright gate goes off on that frame,
  so the trackers are rebuilt once the person stands and the settle rule needs a new plateau: the two walk-away dips counted
  as squats on the phone run are gone. Lunges are excluded because a lunge is itself a step (MM-Fit lunges exact 1.0 -> 0.67).
  Cost: a person who steps into place and squats within a second loses that first rep (1 of 8 QEVD squat read-outs).
- first_mask=True (FIRST_MASK, lunges only, with select='mask'): the set's first count needs one of the leg or torso trackers
  (hip_h, knee, knee_w, sh_y) to have fired; the full top-5 vote stays for every later count. A hand to the face before the first
  lunge had fired elbow, wrist and wrist-height trackers and won the vote. A hard lunges mask was measured and loses lunges.
- settle_plateau_s (SETTLE_LONG_EX, squats): a longer plateau for the settle anchor; measured at 1.2 and 1.5 s, no gain on the
  recordings and QEVD squats drop, so it stays off (None).
"""
import numpy as np
EPS=1e-6
def _ang(a,b,c):
    v1=a-b; v2=c-b
    cos=float((v1*v2).sum()/(np.linalg.norm(v1)*np.linalg.norm(v2)+EPS))
    return float(np.degrees(np.arccos(max(-1.0,min(1.0,cos)))))
# candidate signals; joint angles are the left+right sum in degrees / 90 (a 90 deg bend of both = 2.0) and distances are in torso
# lengths, so one rep moves the right signal by roughly 0.5 to 3 units and the amplitude gate min_amp (0.3) is well below that
SIGNALS=['hip_h','knee','elbow','elbow_w','wr_h','wr_spread','an_spread','sh_y','sh_hip_v','wr_hip','sh_h_w','wr_h_w','knee_w']
HINT={'squats':['hip_h','knee','sh_y'],'lunges':['hip_h','knee','sh_y'],'pushups':['elbow','sh_y','wr_h'],'jumping_jacks':['wr_h','wr_hip','an_spread'],
      'situps':['sh_hip_v','sh_y','hip_h'],'bicep_curls':['wr_h','elbow','wr_hip'],'dumbbell_rows':['wr_h','elbow','wr_h_w'],
      'dumbbell_shoulder_press':['elbow','wr_h','wr_hip'],'lateral_shoulder_raises':['wr_h','wr_hip','wr_h_w'],'tricep_extensions':['elbow_w','elbow','wr_h']}
# known active direction per (exercise, signal), used only when the exercise is given: +1 the signal rises away from rest,
# -1 it falls. Only pairs whose active extreme matched the labels offline on the dev workers; situps, triceps and press have none.
ACTIVE={'squats':{'hip_h':-1,'knee':-1,'knee_w':-1,'sh_y':-1},'lunges':{'hip_h':-1,'knee':-1,'knee_w':-1,'sh_y':-1},
        'pushups':{'elbow':-1,'elbow_w':-1,'wr_h':1},'jumping_jacks':{'wr_h':1,'wr_hip':1,'wr_h_w':1,'an_spread':1,'sh_h_w':1},
        'bicep_curls':{'wr_h':1,'wr_hip':1,'wr_spread':1},'dumbbell_rows':{'wr_h':1,'wr_h_w':1},
        'lateral_shoulder_raises':{'wr_h':1,'wr_h_w':1,'wr_hip':1}}   # press: free sign counts better (pre-set plateau = active level)
MIN_AMP={'squats':0.4,'lunges':0.35,'pushups':0.5,'jumping_jacks':0.65,'situps':0.3,'bicep_curls':0.3,'dumbbell_rows':0.4,
         'dumbbell_shoulder_press':0.5,'lateral_shoulder_raises':0.6,'tricep_extensions':0.5}
ALIAS={'alternating forward lunges':'lunges'}   # live classifier names -> the table keys ('jumping jacks' stays unhinted: the hint costs QEVD jacks)
# signals that physically move in the exercise (select='mask' votes only over these). Measured 2026-10-09: a lunges mask
# [hip_h,knee,knee_w,sh_y] lost reps on the QEVD walking lunges and a jacks mask gained nothing, so both keep the full vote.
MASK={'squats':['hip_h','knee','knee_w','sh_y','sh_hip_v'],'pushups':['elbow','elbow_w','sh_y','sh_h_w','wr_h']}
GATE={'squats':'upright','lunges':'upright','pushups':'prone'}   # body-state precondition per exercise (gate=True)
SETTLE={'squats','lunges'}   # exercises with the plateau-anchored settle rule (settle=True); pushups start right after lying down (QEVD exact 0.81 -> 0.46 with it), jacks start too fast
WALK_EX=('squats',)          # walk_vx applies here: a lunge is itself a step (MM-Fit lunges exact 1.0 -> 0.67 with the veto), so lunges are excluded
SETTLE_LONG_EX=('squats',)   # settle_plateau_s applies here: MM-Fit lunges lose first reps with a 1.2 s plateau (exact 1.0 -> 0.79), squats do not
FIRST_MASK={'lunges':['hip_h','knee','knee_w','sh_y']}   # first_mask=True: the set's first count needs one of these trackers to have fired (full vote otherwise)
MIN_PERIOD={'squats':1.0,'lunges':1.2,'pushups':0.8,'jumping_jacks':0.5,'situps':1.0,'bicep_curls':0.8,'dumbbell_rows':0.8,
            'dumbbell_shoulder_press':0.8,'lateral_shoulder_raises':0.8,'tricep_extensions':0.8}
ARMS={'left':(11,13,15),'right':(12,14,16)}
SIDE_VIEW_EX=('pushups',)   # side_view=None -> on for these exercises only
def arm_visibility(img):
    """(left, right) mean visibility of the shoulder, elbow and wrist of each arm (column 3; 1.0 when img has no visibility)."""
    if img.shape[1]<4: return 1.0,1.0
    v=np.nan_to_num(img[:,3].astype(np.float64),nan=0.0)
    return float(v[list(ARMS['left'])].mean()), float(v[list(ARMS['right'])].mean())
def pose_signals(img, world, torso, torso_w, arm_side=None):
    """img (33,>=2), world (33,3) -> dict of scalar signals. torso, torso_w: slowly varying scales (image, world).
    arm_side None: elbow / elbow_w are the left+right sum (front view). 'left' / 'right' (side view, the other arm hidden):
    2 x that arm's angle / 90, the same scale, so a side-view rep moves the signal as much as a front-view one."""
    xy=img[:,:2]
    sh=(xy[11]+xy[12])/2; hp=(xy[23]+xy[24])/2; an=(xy[27]+xy[28])/2; wr=(xy[15]+xy[16])/2
    S={}
    S['hip_h']=(an[1]-hp[1])/torso
    S['knee']=(_ang(xy[23],xy[25],xy[27])+_ang(xy[24],xy[26],xy[28]))/90.0
    if arm_side is None: S['elbow']=(_ang(xy[11],xy[13],xy[15])+_ang(xy[12],xy[14],xy[16]))/90.0
    else: s_,e_,w_=ARMS[arm_side]; S['elbow']=2.0*_ang(xy[s_],xy[e_],xy[w_])/90.0
    S['wr_h']=(sh[1]-wr[1])/torso
    S['wr_spread']=float(np.linalg.norm(xy[15]-xy[16]))/torso
    S['an_spread']=float(np.linalg.norm(xy[27]-xy[28]))/torso
    S['sh_y']=-sh[1]/torso
    S['sh_hip_v']=(hp[1]-sh[1])/torso
    S['wr_hip']=float(np.linalg.norm(wr-hp))/torso
    if world is not None:
        w=world
        if arm_side is None: S['elbow_w']=(_ang(w[11],w[13],w[15])+_ang(w[12],w[14],w[16]))/90.0
        else: s_,e_,w_=ARMS[arm_side]; S['elbow_w']=2.0*_ang(w[s_],w[e_],w[w_])/90.0
        S['knee_w']=(_ang(w[23],w[25],w[27])+_ang(w[24],w[26],w[28]))/90.0
        S['sh_h_w']=-(w[11,1]+w[12,1])/2/torso_w
        S['wr_h_w']=-(w[15,1]+w[16,1])/2/torso_w
    return S
def body_state(img, world, torso):
    """Per-frame body-state scalars: up = world torso uprightness (1 vertical, 0 horizontal; None without world landmarks),
    wr_nose = (highest wrist y - nose y) / torso in image coords (negative when a wrist is above the nose),
    ang_img = image torso line angle from vertical in normalised coords (aspect-distorted, only used for 'near horizontal')."""
    xy=img[:,:2]; sh=(xy[11]+xy[12])/2; hp=(xy[23]+xy[24])/2; d=sh-hp
    ang=float(np.degrees(np.arctan2(abs(d[0]),abs(d[1])+EPS)))
    wr_nose=float((min(xy[15,1],xy[16,1])-xy[0,1])/torso)
    up=None
    if world is not None:
        dw=(world[11]+world[12])/2-(world[23]+world[24])/2; up=float(-dw[1]/(np.linalg.norm(dw)+EPS))
    return dict(up=up,wr_nose=wr_nose,ang_img=ang)
def gate_ok(kind, bs, up_min=0.6, wr_margin=0.35, prone_max=0.6, prone_ang=60.0):
    """Does the body state allow a rep of this kind? 'upright' (squats, lunges): torso within about 53 deg of vertical and no
    wrist more than wr_margin torso above the nose. 'prone' (pushups): torso near horizontal in the world, or the image
    torso line more than prone_ang from vertical (a side view). Unknown kinds always pass."""
    if kind=='upright': return (bs['up'] is None or bs['up']>up_min) and bs['wr_nose']>-wr_margin
    if kind=='prone': return (bs['up'] is not None and bs['up']<prone_max) or bs['ang_img']>prone_ang
    return True
class _Track:
    """Rest-anchored hysteresis tracker on one signal. Fires at the active turning point.
    States: None (no rest level yet) -> 'rest' -> 'active' (left rest by more than the entry amplitude) -> 'fired' -> 'rest'.
    The active side (sign) is free until the first accepted rep, then fixed; a rest-side excursion larger than
    `flip` times the active amplitude means the sides were wrong and swaps them (keeps count)."""
    def __init__(self, fps, smooth, min_amp, hi, lo, rec, rec_first, rec_abs, plateau_s, plateau_eps, max_hold_s, desc_gate, desc_after, min_period_s, win_s, amp_ema, flip, rest_ema, init_s=0.8, sign=0, amp_cap=0.0, reg_w=0.0, hold_first=None, hold_ratio=0.0, rej_w=0.0, fire='recover', confirm=1, turn_gap=0.0, turn_depth=0.0, settle_plateau_s=None):
        self.fps=fps; self.k=smooth; self.min_amp=min_amp; self.hi=hi; self.lo=lo; self.rec=rec; self.rec_first=rec_first; self.rec_abs=rec_abs
        self.P=int(plateau_s*fps); self.peps=plateau_eps; self.max_hold=int(max_hold_s*fps); self.desc_gate=desc_gate; self.desc_after=desc_after
        self.SP=self.P if settle_plateau_s is None else max(self.P,int(settle_plateau_s*fps))   # plateau length that makes a rest level 'anchored' (the settle rule)
        self.minp=int(min_period_s*fps); self.W=int(win_s*fps); self.amp_ema=amp_ema; self.flip=flip; self.rest_ema=rest_ema
        self.init=int(init_s*fps); self.amp_cap=amp_cap; self.reg_w=reg_w; self.fire_i=[]; self.hold_first=self.max_hold if hold_first is None else int(hold_first*fps); self.hold_ratio=hold_ratio; self.rej_w=rej_w; self.fire_mode=fire; self.confirm=confirm; self.prev_side=None; self.down=0; self.turn_gap=turn_gap; self.turn_depth=turn_depth
        self.raw=[]; self.buf=[]; self.state=None; self.R=None; self.A_ref=None; self.sign=sign; self.sign0=sign; self.fixed=bool(sign)
        self.ext=0.0; self.ext_i=-1; self.leave_i=-1; self.near_i=-1; self.rest_ext=None; self.last_fire=-999
        self.fired=False; self.tp=-1; self.n_fire=0; self.desc=[]; self.fire_amps=[]; self.period_score=0.0; self.lag=0; self.amp=0.0; self.info=None; self.rejected=[]; self.flips=0
        self.anchored=False; self.anch_leave=False   # rest level comes from a real plateau (not the mid-motion median fallback); value when the current rep left rest
    def _reversals(self):
        """Number of direction reversals of at least min_amp in the buffer (2 = one full cycle seen)."""
        n=0; d=0; hi=lo=self.buf[0]
        for v in self.buf:
            hi=max(hi,v); lo=min(lo,v)
            if d>=0 and hi-v>=self.min_amp: n+=1; d=-1; lo=v
            elif d<=0 and v-lo>=self.min_amp: n+=1; d=1; hi=v
        return n
    def _plateau(self, n=None):
        n=self.P if n is None else n
        if len(self.buf)<n: return None
        seg=self.buf[-n:]; eps=max(self.peps, 0.15*self.A_ref) if self.A_ref else self.peps
        return float(np.mean(seg)) if (max(seg)-min(seg))<eps else None
    def push(self, v, i, anchor_only=False):
        """anchor_only: reject a rep unless this tracker's rest level was a real plateau when the rep began (the settle rule)."""
        self.raw.append(v); self.raw=self.raw[-(self.k+2):]
        s=float(np.mean(self.raw[-self.k:])); self.buf.append(s); self.buf=self.buf[-self.W:]
        self.fired=False; self.info=None
        pl=self._plateau(); longp=(self.SP==self.P)
        anch=(pl is not None) if longp else (self._plateau(self.SP) is not None)   # settle_plateau_s: only a longer plateau anchors
        if self.state is None:
            real=anch
            if pl is None and len(self.buf)>=self.init:
                # no rest plateau yet. If the signal is already oscillating (the counter started mid-set) anchor on the
                # median now and let the rest level follow the returns; otherwise wait for a plateau, and after 4 plateau
                # lengths give up and take the median (the hold rule moves it to the next real rest).
                seg=self.buf[-self.P:]
                if max(seg)-min(seg)<3*self.peps: pl=float(np.mean(seg)); real=longp
                elif self._reversals()>=2 or len(self.buf)>=4*self.P: pl=float(np.median(self.buf))
            if pl is not None: self.R=pl; self.state='rest'; self.rest_ext=None; self.anchored=real
            return
        dev=s-self.R
        entry=max(0.5*self.min_amp, self.hi*self.A_ref) if self.A_ref else self.min_amp
        if self.state=='rest':
            if pl is not None: self.R=(1-self.rest_ema)*self.R+self.rest_ema*pl; dev=s-self.R; self.anchored=self.anchored or anch
            if self.fixed:
                side=dev*self.sign
                if side<=0.3*entry: self.near_i=i
                if side<0 and (self.rest_ext is None or side<self.rest_ext): self.rest_ext=side; self.rest_val=s
                if self.A_ref and side<-self.flip*self.A_ref:
                    # a far larger excursion on the "rest" side: the sides were wrong, swap them
                    self.R=self.R+self.sign*self.A_ref; self.sign=-self.sign; self.A_ref=None; self.desc=[]; self.flips+=1; self.fire_amps=[float('inf')]*len(self.fire_amps)
                    dev=s-self.R; self.state='active'; self.ext=dev*self.sign; self.ext_i=i; self.leave_i=i; self.rest_ext=None; self.anch_leave=self.anchored; return
                base=self.rest_val if self.rest_ext is not None else self.R
                if (s-base)*self.sign>entry:
                    if self.rest_ext is not None:
                        # the level the signal actually returned to is the rest level; adopt it outright when it is far
                        # from the old one (a pre-set plateau at the active level, as in a press that starts arms-down)
                        self.R=self.rest_val if -self.rest_ext>self.min_amp else (1-self.rest_ema)*self.R+self.rest_ema*self.rest_val
                        dev=s-self.R; side=dev*self.sign
                    self.state='active'; self.ext=side; self.ext_i=i; self.leave_i=self.near_i; self.rest_ext=None; self.prev_side=None; self.down=0; self.anch_leave=self.anchored
            elif abs(dev)>entry:
                self.state='active'; self.sign=1 if dev>0 else -1; self.ext=abs(dev); self.ext_i=i; self.leave_i=i; self.rest_ext=None; self.prev_side=None; self.down=0; self.anch_leave=self.anchored
            return
        side=dev*self.sign
        if self.state=='active':
            if self.fire_mode=='turn':
                # turning point: the extreme is exact and `down` counts consecutive frames moving back toward rest
                if side>self.ext: self.ext=side; self.ext_i=i; self.down=0
                elif self.prev_side is not None and side<self.prev_side: self.down+=1
                else: self.down=0
            elif side>self.ext*1.02: self.ext=side; self.ext_i=i
            self.prev_side=side
            hold=i-self.ext_i
            lim=self.hold_first if not self.fixed else self.max_hold
            if self.hold_ratio and len(self.fire_i)>=2: lim=max(lim,int(self.hold_ratio*float(np.median(np.diff(self.fire_i[-5:])))))
            if pl is not None and hold>=lim:
                # the person is holding this position: it is a new rest, not a rep
                self.R=pl; self.state='rest'; self.rest_ext=None; self.anchored=True; self.rejected.append((i,'hold')); return
            recov=self.ext-side
            rec=self.rec if self.fixed else self.rec_first
            fast=self.fire_mode=='turn' and self.fixed
            if fast and self.turn_gap and len(self.fire_i)>=2:
                # fast fire only in rhythm: an isolated late candidate (getting up after the set) must earn the full recovery
                fast=(i-self.fire_i[-1])<=self.turn_gap*float(np.median(np.diff(self.fire_i[-5:])))
            if fast and self.turn_depth and self.A_ref: fast=self.ext>=self.turn_depth*self.A_ref
            if fast: go=self.down>=self.confirm and recov>=self.rec_abs   # one smoothed step past the extreme, velocity sign test
            else: go=recov>=max(rec*self.ext,self.rec_abs)
            if go:
                desc=self.ext_i-self.leave_i; self.amp=self.ext; ok=True
                if hold>lim: ok=False; self.rejected.append((i,'hold2'))
                elif anchor_only and not self.anch_leave: ok=False; self.rejected.append((i,'anchor'))
                elif self.desc_gate and len(self.desc)>=self.desc_after and desc>self.desc_gate*float(np.median(self.desc[-5:])):
                    ok=False; self.rejected.append((i,'desc'))
                self.state='fired'
                if ok and i-self.last_fire>=self.minp:
                    self.last_fire=i; self.fired=True; self.tp=self.ext_i; self.n_fire+=1; self.desc.append(desc); self.fixed=True; self.fire_amps.append(self.ext); self.fire_i.append(i)
                    self.A_ref=self.ext if self.A_ref is None else (1-self.amp_ema)*self.A_ref+self.amp_ema*self.ext
                    self.info=dict(desc=desc,hold=hold,amp=self.ext,ref=self.A_ref)
            return
        if self.state=='fired':
            if side>self.ext: self.ext=side; self.ext_i=i
            elif side<self.lo*self.ext: self.state='rest'; self.rest_ext=None; self.near_i=i
            elif pl is not None and side<0.6*self.ext:
                # resting at a level the hysteresis never reached (the rest level moved): adopt it
                self.R=(1-self.rest_ema)*self.R+self.rest_ema*pl; self.state='rest'; self.rest_ext=None; self.near_i=i; self.anchored=True
            return
    def forget(self):
        """Forget every fire (the settle rule: what happened before the person stood still was not a rep) but keep the rest level."""
        self.n_fire=0; self.fire_amps=[]; self.fire_i=[]; self.A_ref=None; self.desc=[]; self.rejected=[]; self.last_fire=-999
        self.fired=False; self.tp=-1; self.info=None; self.amp=0.0; self.fixed=bool(self.sign0)
    def quality(self, i, rank):
        """Ranking score for the vote: rep amplitude, times a ramp over the first 3 reps, times a recency decay
        (a tracker that has not fired for 2.5 s is going stale), optionally times (0.5 + in-window periodicity)."""
        if self.A_ref is None or not self.n_fire: return -1.0
        q=min(self.A_ref,self.amp_cap) if self.amp_cap else self.A_ref
        if rank in ('ampn','ampnp'):
            q*=min(self.n_fire,3)/3.0; q*=float(np.exp(-max(0,i-self.last_fire-2.5*self.fps)/(2.0*self.fps)))
        if rank=='ampnp': q*=0.5+self.periodicity()
        if self.rej_w and self.rejected: q*=self.n_fire/(self.n_fire+self.rej_w*len(self.rejected))   # trackers that keep rejecting are unreliable
        if self.reg_w and len(self.fire_i)>=3:
            # rhythm regularity of the last fires: junk trackers fire at irregular intervals
            d=np.diff(self.fire_i[-5:]); cv=float(d.std()/(d.mean()+EPS)); q*=1.0/(1.0+self.reg_w*cv)
        return q
    def rebased(self, frac):
        """Count of accepted reps whose amplitude is at least `frac` of the current reference amplitude (drops a small pre-set
        movement once real reps have shown what a rep looks like)."""
        if not self.fire_amps or self.A_ref is None: return len(self.fire_amps)
        thr=frac*self.A_ref; return int(sum(1 for a in self.fire_amps if a>=thr))
    def periodicity(self, min_period_s=0.5, max_period_s=4.0):
        b=np.asarray(self.buf); n=len(b)
        lo=int(min_period_s*self.fps); hi=min(int(max_period_s*self.fps),n//2)
        if n<2*lo+2 or hi<=lo: self.period_score=0.0; return 0.0
        b=b-b.mean(); den=float(b@b)
        if den<EPS: self.period_score=0.0; return 0.0
        ac=np.correlate(b,b,'full')[n-1:n+hi]/den
        seg=ac[lo:hi]; j=int(np.argmax(seg)); self.period_score=float(seg[j]); self.lag=lo+j
        return self.period_score
class RepCounter2:
    """select: 'vote' (default): the count follows the median count of the `top_k` trackers with the largest rep amplitude;
    'mask': the same vote over MASK[exercise] (squats, pushups; the best mask_top_k trackers), else the full vote;
    'hint': the same vote restricted to the exercise's hinted signals (needs exercise=); 'single': one tracker (the first
    hinted signal, or the largest-amplitude tracker when no exercise is given).
    gate (bool): body-state precondition per GATE[exercise]; settle (bool): plateau-anchored rest required for settle_max_s
    after a (re)start (see the module docstring); alias: map live classifier names through ALIAS (default: on for
    select='mask' only, so 'vote' is HEAD); mask_min_amp: use MIN_AMP[exercise] for the masked trackers."""
    def __init__(self, fps=10, exercise=None, select='vote', smooth=3, min_amp=0.3, hi=0.6, lo=0.4, rec=0.15, rec_first=0.4, rec_abs=0.08,
                 plateau_s=0.8, plateau_eps=0.08, max_hold_s=0.8, desc_gate=3.0, desc_after=3, min_period_s=0.5, win_s=6.0, amp_ema=0.3,
                 flip=1.5, rest_ema=0.5, top_k=5, amp_frac=0.5, rank='ampn', gap_gate=0.0, gap_confirm=1.5, init_s=1.2, amp_cap=0.0, reg_w=2.0, pad=True, scale='ema', scale_decay=0.02, torso_sig=False,
                 hold_first_s=None, hold_ratio=0.0, rej_w=0.0, fire='recover', confirm=1, turn_gap=0.0, turn_depth=0.0, signals=None,
                 gate=False, gate_off_s=0.5, gate_on_s=0.3, up_min=0.6, wr_margin=0.35, prone_max=0.6, prone_ang=60.0,
                 settle=False, settle_max_s=4.0, alias=None, mask_min_amp=False, mask_top_k=3, seed_s=0.3, settle_plateau_s=None, walk_vx=0.0, walk_n=3, walk_ex=WALK_EX, mask=None, settle_long_ex=SETTLE_LONG_EX, first_mask=False,
                 side_view=None, side_hi=0.8, side_diff=0.3, side_exit_min=0.7, side_exit_diff=0.15, side_on_s=1.0, side_off_s=1.0):
        if alias is None: alias=(select=='mask')
        if alias and exercise in ALIAS: exercise=ALIAS[exercise]
        # side view (challenge, 2026-10-12): pushups filmed from the side hide one arm, and the bilateral elbow sum then mixes
        # in MediaPipe's guess of the hidden arm. With side_view on (default for SIDE_VIEW_EX) elbow / elbow_w switch to 2 x the
        # visible arm once one arm's mean visibility is >= side_hi and >= side_diff above the other's for side_on_s, and back to
        # the sum after side_off_s with both arms >= side_exit_min and within side_exit_diff. Measured on the local clips with
        # MediaPipe full (2026-10-12): the hidden arm reads 0.4 to 0.8 and swings with the rep phase in side views, so the
        # choice is sticky; the five front-view clips never switch (rep events identical to side_view=False).
        self.side_view=(exercise in SIDE_VIEW_EX) if side_view is None else bool(side_view)
        self.side_hi=float(side_hi); self.side_diff=float(side_diff); self.side_exit_min=float(side_exit_min); self.side_exit_diff=float(side_exit_diff)
        self.side_on_n=max(1,int(round(side_on_s*fps))); self.side_off_n=max(1,int(round(side_off_s*fps)))
        self.arm_side=None; self._side_cand=(None,0); self.side_i=[]
        MASKS=dict(MASK, **(mask or {}))   # mask: extra or replacement MASK entries, e.g. {'lunges': [...]}
        self.walk_vx=float(walk_vx or 0.0) if exercise in tuple(walk_ex) else 0.0; self.walk_n=max(1,int(walk_n)); self.hx=[]; self.n_walk=0; self.walk_i=[]
        fm=FIRST_MASK if first_mask is True else (first_mask or {}); self.fm=list(fm.get(exercise,[])) if (fm and select=='mask' and exercise not in MASKS) else []
        self.fps=fps; self.ex=exercise; self.i=-1; self.count=0; self.events=[]; self.turning=[]; self.sel=None; self.sel_hist=[]; self.infos=[]
        self.gate_kind=GATE.get(exercise) if gate else None; self.gate_on=True; self.g_false=0; self.g_true=0; self.n_gate_off=0; self.gate_i=[]
        self.gate_p=dict(up_min=up_min,wr_margin=wr_margin,prone_max=prone_max,prone_ang=prone_ang); self.gate_off_n=max(1,int(round(gate_off_s*fps))); self.gate_on_n=max(1,int(round(gate_on_s*fps)))
        self.settle=bool(settle) and exercise in SETTLE; self.settle_max_n=int(round(settle_max_s*fps)); self.settle_i0=0; self.n_resettle=0
        self.select=select; self.top_k=top_k; self.amp_frac=amp_frac; self.rank=rank; self.gap_gate=gap_gate; self.gap_confirm=gap_confirm; self.pad=pad; self.scale=scale; self.scale_decay=scale_decay; self.torso_now=None
        self.pending=None; self.skip=0; self.deferred=[]
        self.minp=int((MIN_PERIOD.get(exercise,min_period_s) if exercise else min_period_s)*fps)
        masked=(select=='mask' and exercise in MASKS)
        if masked and mask_top_k: self.top_k=mask_top_k   # a masked vote has at most 5 signals and some views move only 3 of them: 2 of the best 3 must agree
        self.seed_n=int(round(seed_s*fps)) if seed_s is not None and seed_s>=0 else None; self.seed_at=None   # seed_s None or negative: no provisional rest
        names=signals or (HINT[exercise] if (exercise in HINT and select in ('hint','single')) else (MASKS[exercise] if masked else SIGNALS))
        self.names=list(names)+(['torso'] if torso_sig and not signals else [])
        ma=MIN_AMP.get(exercise,min_amp) if (exercise in MIN_AMP and (select in ('hint','single') or (masked and mask_min_amp))) else min_amp
        act=ACTIVE.get(exercise,{}) if exercise else {}
        sps=settle_plateau_s if (self.settle and exercise in tuple(settle_long_ex)) else None   # the longer anchoring plateau, where the settle rule runs
        self.tr={n:_Track(fps,smooth,ma,hi,lo,rec,rec_first,rec_abs,plateau_s,plateau_eps,max_hold_s,desc_gate,desc_after,min_period_s,win_s,amp_ema,flip,rest_ema,init_s,act.get(n,0),amp_cap,reg_w,hold_first_s,hold_ratio,rej_w,fire,confirm,turn_gap,turn_depth,sps) for n in self.names}
        self.torso=None; self.torso_w=None; self.last=None; self.last_event=-999
    def _reset_trackers(self):
        """Fresh trackers (new body state): the rest level is learned again from the frames that follow."""
        for n,tr in self.tr.items():
            tr.raw=[]; tr.buf=[]; tr.state=None; tr.R=None; tr.rest_ext=None; tr.ext=0.0; tr.ext_i=-1; tr.leave_i=-1; tr.near_i=-1
            tr.sign=tr.sign0; tr.flips=0; tr.anchored=False; tr.anch_leave=False; tr.forget()
        self.sel=None; self.pending=None
    def resettle(self, keep=False):
        """Start the settle window again (after a visibility pause or a gate re-arm): every tracker must see a real plateau
        before its next rep counts, for settle_max_s. keep=True only extends the window (the session arming the Coach:
        a tracker that already rests on a plateau keeps that)."""
        if not self.settle: return
        self.settle_i0=self.i+1; self.n_resettle+=1
        if not keep:
            for tr in self.tr.values(): tr.anchored=False
    def _scales(self, img, world):
        t=float(np.linalg.norm((img[11,:2]+img[12,:2])/2-(img[23,:2]+img[24,:2])/2)); self.torso_now=t
        if self.scale=='body':
            # bending to the floor collapses the projected torso (a front view of a toe touch leaves 0.02 of it); the legs do not
            leg=float(np.linalg.norm((img[23,:2]+img[24,:2])/2-(img[27,:2]+img[28,:2])/2)); t=max(t,0.5*leg)
        if self.torso is None: self.torso=t
        elif self.scale in ('max','body'): self.torso=max(t,(1-self.scale_decay)*self.torso+self.scale_decay*t)   # keep the upright length
        else: self.torso=0.9*self.torso+0.1*t
        if world is not None:
            tw=float(np.linalg.norm((world[11]+world[12])/2-(world[23]+world[24])/2))
            self.torso_w=tw if self.torso_w is None else 0.9*self.torso_w+0.1*tw
        return max(self.torso,1e-3), max(self.torso_w or 1.0,1e-3)
    def _walking(self, img, t):
        """Is the person walking across the frame? Hip centre x speed over the last walk_n frames, in torso lengths per second
        (image torso length, so a step reads the same near and far), above walk_vx. Squats, lunges and jacks move the hips
        by well under 1 torso/s sideways; walking into place or to the phone reaches 1.2 to 1.8 (2026-10-09 recordings)."""
        self.hx.append(float((img[23,0]+img[24,0])/2)); self.hx=self.hx[-(self.walk_n+1):]
        if len(self.hx)<=self.walk_n: return False
        vx=abs(self.hx[-1]-self.hx[0])/(self.walk_n/self.fps)/max(t,1e-3)
        return vx>self.walk_vx
    def _update_arm_side(self, img):
        """Side-view arm choice with hysteresis (see __init__). Records (frame, side) in side_i on a change."""
        vl,vr=arm_visibility(img)
        if self.arm_side is None:
            want='left' if (vl>=self.side_hi and vl-vr>=self.side_diff) else ('right' if (vr>=self.side_hi and vr-vl>=self.side_diff) else None)
            need=self.side_on_n
        else:
            front=min(vl,vr)>=self.side_exit_min and abs(vl-vr)<=self.side_exit_diff
            want=None if front else self.arm_side; need=self.side_off_n
        if want==self.arm_side: self._side_cand=(None,0); return
        c,n=self._side_cand; n=n+1 if c==want else 1; self._side_cand=(want,n)
        if n>=need: self.arm_side=want; self._side_cand=(None,0); self.side_i.append((self.i,want))
    def _emit(self, tp):
        self.last_event=self.i; self.count+=1; self.events.append(self.i); self.turning.append(tp); return self.count
    def update(self, img, world=None, ok=True):
        self.i+=1
        if ok and img is not None:
            img=np.asarray(img,np.float32); world=None if world is None else np.asarray(world,np.float32)
            t,tw=self._scales(img,world)
            if self.side_view: self._update_arm_side(img)
            self.last=pose_signals(img,world,t,tw,self.arm_side); self.last['torso']=self.torso_now/t
        S=self.last
        if S is None: return None
        if self.gate_kind is not None:
            if ok and img is not None:
                g=gate_ok(self.gate_kind, body_state(img,world,t), **self.gate_p)
                if g and self.walk_vx and self.gate_kind=='upright' and self._walking(img,t):
                    # walking: the gate goes off on this frame (no 0.5 s grace) and the trackers are rebuilt once the person stands
                    g=False; self.n_walk+=1; self.walk_i.append(self.i); self.g_false=max(self.g_false,self.gate_off_n-1)
                if g: self.g_true+=1; self.g_false=0
                else: self.g_false+=1; self.g_true=0
            if self.gate_on and self.g_false>=self.gate_off_n:
                # wrong body state (standing before pushups, bending to the floor, arms overhead): stop feeding the trackers and
                # drop what they had, so no rep can start here
                self.gate_on=False; self.n_gate_off+=1; self.gate_i.append((self.i,'off')); self._reset_trackers()
            elif not self.gate_on and self.g_true>=self.gate_on_n:
                self.gate_on=True; self.gate_i.append((self.i,'on')); self._reset_trackers(); self.resettle(); self.seed_at=None if (self.seed_n is None or self.settle) else self.i+self.seed_n   # settle exercises wait for a real plateau instead
            if not self.gate_on: return None
        anchor_only=self.settle and (self.i-self.settle_i0)<self.settle_max_n
        for n,tr in self.tr.items():
            if n in S: tr.push(S[n],self.i,anchor_only)
        if self.seed_at is not None and self.i>=self.seed_at:
            # just re-armed in a new body state (lying down for pushups): a provisional rest level now, so the first rep is
            # tracked at once instead of after a plateau; it is not 'anchored', so the settle rule (where on) still applies
            self.seed_at=None
            for tr in self.tr.values():
                if tr.state is None and tr.buf: tr.R=tr.buf[-1]; tr.state='rest'; tr.rest_ext=None; tr.anchored=False
        if self.i-self.last_event<self.minp: return None
        if self.select=='single':
            if self.sel is None:
                if self.ex in HINT: self.sel=self.names[0]
                else:
                    c=[(tr.A_ref,n) for n,tr in self.tr.items() if tr.n_fire and tr.A_ref is not None]
                    if c: self.sel=max(c)[1]
            if self.sel is None: return None
            tr=self.tr[self.sel]
            return self._emit(tr.tp) if tr.fired else None
        # vote: median count of the top_k trackers by rep amplitude (missing trackers count as 0)
        c=sorted(((tr.quality(self.i,self.rank),n) for n,tr in self.tr.items() if tr.n_fire and tr.A_ref is not None),reverse=True)[:self.top_k]
        if not c: return None
        counts=[self.tr[n].rebased(self.amp_frac) for _,n in c]
        if self.pad: counts+=[0]*(self.top_k-len(c))   # trackers that have not fired vote 0 (guards the first rep)
        k=len(counts); med=int(np.median(counts)) if k%2 else int(sorted(counts)[k//2])
        top=[n for _,n in c]
        if top!=self.sel: self.sel_hist.append((self.i,top)); self.sel=top
        med-=self.skip
        tps=[self.tr[n].tp for n in top if self.tr[n].n_fire and self.i-self.tr[n].last_fire<=self.minp]; tp=max(tps) if tps else self.i
        if self.pending is not None:
            # a rep after a long gap is held until the next rep confirms the set goes on; dropped if none follows
            pi,ptp,pmed=self.pending
            if med>pmed:
                self.pending=None; self.deferred.append(self.i); self._emit(ptp); return self._emit(tp)
            if self.i-pi>self.gap_confirm*self._med_int(): self.pending=None; self.skip+=1
            return None
        if med>self.count:
            if self.count==0 and self.fm and not any(self.tr[n].n_fire for n in self.fm if n in self.tr): return None   # first_mask: no first count from the arms alone
            if self.gap_gate and len(self.events)>=3 and self.i-self.events[-1]>self.gap_gate*self._med_int():
                self.pending=(self.i,tp,med); return None
            return self._emit(tp)
        return None
    def _med_int(self):
        return float(np.median(np.diff(self.events[-6:]))) if len(self.events)>=2 else 2.0*self.fps
