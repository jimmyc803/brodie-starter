"""MediaPipe pose wrapper: frames (RGB uint8) -> (33,5) image landmarks [x,y,z,vis,pres] + (33,3) world landmarks.

num_poses (default 1, the coach as before): with num_poses >= 2 MediaPipe may return several people. __call__ still
returns the PRIMARY person's (img, world) - so every caller is unchanged - and sets, for that call:
  persons   number of people in frame (C5 / challenge judge, multiple_people gate): poses whose mean visibility over the
            torso landmarks (11, 12, 23, 24) is >= PERSON_VIS (0.5), minus duplicates of one body (count_persons).
            0 without poses; >= 1 whenever landmarks are returned.
  switched  True when the primary is not the person tracked so far (PrimaryTracker): the caller must not let a rep span
            the change (facetime.pipeline restarts the counter's partial rep and the judge window).
Primary (PrimaryTracker): the pose whose torso centroid is nearest the previous primary's (within TRACK_MAX_D normalised
image units; the previous centroid is kept through frames without a pose); otherwise the pose with the largest score =
landmark bbox area (in-image part) x mean presence, and that is a switch if a previous primary existed.
With num_poses == 1 the single pose is the primary (landmarks identical to the old wrapper).

Duplicates (count_persons): MediaPipe with num_poses=2 often returns a second, partial copy of the same body. A pose is
a duplicate of a counted one only if one bbox lies inside the other (each grown by DUP_GROW of its size) AND the mean
distance between their corresponding landmarks (both visible) is < DUP_DIST of the larger bbox diagonal. Two distinct
people whose boxes merely overlap (one behind the other, someone beside the plank) are both counted. Measured on the 9
local clips (MediaPipe full, 2026-10-12): the three side-view push-up clips report 0 frames with 2 people; front close-up
clips 2 to 16 frames (ghosts with different geometry), which a judge counts as people only when >= 2 frames of a rep do.
"""
import numpy as np, mediapipe as mp, os
from mediapipe.tasks.python import vision, BaseOptions
MODELS=os.path.join(os.path.dirname(__file__),'..','..','models')
TORSO=(11,12,23,24)
PERSON_VIS=0.5
TRACK_MAX_D=0.25
DUP_GROW=0.2
DUP_DIST=0.5
PERSON_PRES=0.5       # 2nd-person floor: mean presence over the torso landmarks of a non-primary pose
PERSON_MIN_LMS=10     # 2nd-person floor: landmarks with visibility >= PERSON_VIS (judge min_conf) in a non-primary pose
def _box(a):
    """Landmark bbox (x0,y0,x1,y1), clipped to the image, over the landmarks with visibility >= PERSON_VIS (all if < 4 are)."""
    m=a[:,3]>=PERSON_VIS; xy=np.clip(a[m if int(m.sum())>=4 else slice(None),:2].astype(float),0.0,1.0)
    return float(xy[:,0].min()),float(xy[:,1].min()),float(xy[:,0].max()),float(xy[:,1].max())
def _inside(b, outer, grow=DUP_GROW):
    w=outer[2]-outer[0]; h=outer[3]-outer[1]
    return b[0]>=outer[0]-grow*w and b[1]>=outer[1]-grow*h and b[2]<=outer[2]+grow*w and b[3]<=outer[3]+grow*h
def _diag(b):
    return float(np.hypot(b[2]-b[0],b[3]-b[1]))
def is_duplicate(a, b):
    """Is pose b a (partial) copy of pose a? Nested bboxes AND matching landmark geometry (module docstring)."""
    ba,bb=_box(a),_box(b)
    if not (_inside(bb,ba) or _inside(ba,bb)): return False
    m=(a[:,3]>=PERSON_VIS)&(b[:,3]>=PERSON_VIS)
    if int(m.sum())<4: m=np.ones(len(a),bool)
    d=float(np.mean(np.linalg.norm(a[m,:2].astype(float)-b[m,:2].astype(float),axis=1)))
    return d<DUP_DIST*max(_diag(ba),_diag(bb),1e-9)
def passes_floor(a):
    """2nd-person floor (non-primary poses only): mean torso presence >= PERSON_PRES AND >= PERSON_MIN_LMS landmarks with
    visibility >= PERSON_VIS. A low-confidence fragment is not a person."""
    pres=float(np.nanmean(a[list(TORSO),4])) if a.shape[1]>=5 else 1.0
    return pres>=PERSON_PRES and int((a[:,3]>=PERSON_VIS).sum())>=PERSON_MIN_LMS
def count_persons(poses, primary=0):
    """poses: list of (33,>=4) image-landmark arrays -> people in frame: poses with mean torso visibility >= PERSON_VIS that
    are not a duplicate (is_duplicate) of one already counted and (non-primary poses) pass the floor (passes_floor).
    The primary is considered first and is exempt from the floor (its own quality is the judge's not_in_frame gate)."""
    order=[primary]+[k for k in range(len(poses)) if k!=primary]; kept=[]
    for k in order:
        a=poses[k]
        if float(np.nanmean(a[list(TORSO),3]))<PERSON_VIS: continue
        if k!=primary and not passes_floor(a): continue
        if any(is_duplicate(q,a) for q in kept): continue
        kept.append(a)
    return len(kept)
def _centroid(a):
    return np.nanmean(a[list(TORSO),:2].astype(float),axis=0)
def _score(a):
    xy=np.clip(a[:,:2].astype(float),0.0,1.0); area=float(np.ptp(xy[:,0])*np.ptp(xy[:,1]))
    pres=float(np.nanmean(a[:,4])) if a.shape[1]>=5 else 1.0
    return area*pres
def select_primary(poses, prev_centroid=None, max_d=TRACK_MAX_D):
    """Index of the primary person in `poses` (non-empty list of (33,5) arrays); see the module docstring."""
    if len(poses)==1: return 0
    if prev_centroid is not None:
        d=[float(np.linalg.norm(_centroid(a)-prev_centroid)) for a in poses]; j=int(np.argmin(d))
        if d[j]<=max_d: return j
    return int(np.argmax([_score(a) for a in poses]))
class PrimaryTracker:
    """Primary-person choice across frames (module docstring). update(poses) -> (index or None, switched)."""
    def __init__(self, max_d=TRACK_MAX_D):
        self.max_d=max_d; self.prev=None
    def update(self, poses):
        if not poses: return None, False                       # keep the previous centroid through dropouts
        j=select_primary(poses, self.prev, self.max_d)
        c=_centroid(poses[j])
        switched=self.prev is not None and float(np.linalg.norm(c-self.prev))>self.max_d
        self.prev=c
        return j, switched
class Pose:
    def __init__(self, variant='full', video=True, num_poses=1):
        opts=vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=f'{MODELS}/pose_landmarker_{variant}.task'),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE, num_poses=int(num_poses),
            min_pose_detection_confidence=0.4, min_pose_presence_confidence=0.4, min_tracking_confidence=0.4)
        self.lm=vision.PoseLandmarker.create_from_options(opts); self.video=video; self.num_poses=int(num_poses)
        self.persons=0; self.switched=False; self.tracker=PrimaryTracker()
    def __call__(self, rgb, t_ms):
        img=mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        r=self.lm.detect_for_video(img, int(t_ms)) if self.video else self.lm.detect(img)
        poses=[np.array([[p.x,p.y,p.z,p.visibility or 0,p.presence or 0] for p in pl],np.float32) for pl in (r.pose_landmarks or [])]
        j,self.switched=self.tracker.update(poses)
        if j is None:
            self.persons=0; return None, None
        a=poses[j]; w=np.array([[p.x,p.y,p.z] for p in r.pose_world_landmarks[j]],np.float32)
        self.persons=max(1,count_persons(poses,j))
        return a,w
    def close(self): self.lm.close()
