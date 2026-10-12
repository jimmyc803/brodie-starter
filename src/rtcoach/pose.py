"""MediaPipe pose wrapper: frames (RGB uint8) -> (33,5) image landmarks [x,y,z,vis,pres] + (33,3) world landmarks.

num_poses (default 1, the coach as before): with num_poses >= 2 MediaPipe may return several people. __call__ still
returns the PRIMARY person's (img, world) - so every caller is unchanged - and sets `self.persons` to the number of
people in frame on that call (C5 / challenge judge, multiple_people gate):
  persons   = poses whose mean visibility over the torso landmarks (11, 12, 23, 24) is >= PERSON_VIS (0.5), minus duplicates
              of the same body (count_persons: bbox overlap / smaller bbox >= DUP_OVERLAP); 0 without poses.
  primary   = stable across frames by nearest centroid: the pose whose torso centroid is nearest the previous primary's
              (within TRACK_MAX_D normalised image units); otherwise (first frame, previous one lost, or nobody near it)
              the pose with the largest score = landmark bbox area (in-image part) x mean presence.
A detected primary always counts (persons >= 1 whenever landmarks are returned). With num_poses == 1 the single pose
is the primary (identical to the old wrapper) and persons is 1 or 0.
"""
import numpy as np, mediapipe as mp, os
from mediapipe.tasks.python import vision, BaseOptions
MODELS=os.path.join(os.path.dirname(__file__),'..','..','models')
TORSO=(11,12,23,24)
PERSON_VIS=0.5
TRACK_MAX_D=0.25
DUP_OVERLAP=0.5
def _box(a):
    """Landmark bbox (x0,y0,x1,y1), clipped to the image, over the landmarks with visibility >= PERSON_VIS (all if < 4 are)."""
    m=a[:,3]>=PERSON_VIS; xy=np.clip(a[m if int(m.sum())>=4 else slice(None),:2].astype(float),0.0,1.0)
    return float(xy[:,0].min()),float(xy[:,1].min()),float(xy[:,0].max()),float(xy[:,1].max())
def _overlap(b1, b2):
    """Intersection area / area of the smaller box."""
    ix=max(0.0,min(b1[2],b2[2])-max(b1[0],b2[0])); iy=max(0.0,min(b1[3],b2[3])-max(b1[1],b2[1]))
    small=min((b1[2]-b1[0])*(b1[3]-b1[1]),(b2[2]-b2[0])*(b2[3]-b2[1]))
    return ix*iy/small if small>1e-9 else (1.0 if ix*iy>0 else 0.0)
def count_persons(poses, primary=0):
    """poses: list of (33,>=4) image-landmark arrays -> people in frame: poses with mean torso visibility >= PERSON_VIS that are
    not a duplicate of one already counted (bbox overlap / smaller bbox >= DUP_OVERLAP; MediaPipe with num_poses=2 often
    returns a second, partial copy of the same body - 0 sustained false doubles on the 9 local clips at 0.5, vs up to 9
    at 0.8). The primary is considered first."""
    order=[primary]+[k for k in range(len(poses)) if k!=primary]; kept=[]
    for k in order:
        a=poses[k]
        if float(np.nanmean(a[list(TORSO),3]))<PERSON_VIS: continue
        b=_box(a)
        if any(_overlap(b,q)>=DUP_OVERLAP for q in kept): continue
        kept.append(b)
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
class Pose:
    def __init__(self, variant='full', video=True, num_poses=1):
        opts=vision.PoseLandmarkerOptions(base_options=BaseOptions(model_asset_path=f'{MODELS}/pose_landmarker_{variant}.task'),
            running_mode=vision.RunningMode.VIDEO if video else vision.RunningMode.IMAGE, num_poses=int(num_poses),
            min_pose_detection_confidence=0.4, min_pose_presence_confidence=0.4, min_tracking_confidence=0.4)
        self.lm=vision.PoseLandmarker.create_from_options(opts); self.video=video; self.num_poses=int(num_poses)
        self.persons=0; self._prev_c=None
    def __call__(self, rgb, t_ms):
        img=mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        r=self.lm.detect_for_video(img, int(t_ms)) if self.video else self.lm.detect(img)
        if not r.pose_landmarks:
            self.persons=0; self._prev_c=None; return None, None
        poses=[np.array([[p.x,p.y,p.z,p.visibility or 0,p.presence or 0] for p in pl],np.float32) for pl in r.pose_landmarks]
        j=select_primary(poses, self._prev_c)
        a=poses[j]; w=np.array([[p.x,p.y,p.z] for p in r.pose_world_landmarks[j]],np.float32)
        self.persons=max(1,count_persons(poses,j)); self._prev_c=_centroid(a)
        return a,w
    def close(self): self.lm.close()
