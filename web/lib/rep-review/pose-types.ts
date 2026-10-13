// Shared shape for cached pose landmarks (MediaPipe Pose Landmarker, 33 landmarks, normalized image coords).
// The same JSON is produced by the in-browser pipeline (pose.ts) and by scripts/pose-landmarks.py, so a clip can ship
// with a precomputed public/clips/<id>.pose.json and skip detection entirely.

export const POSE_VERSION = 1;

// One frame: [t, x0, y0, v0, x1, y1, v1, ... x32, y32, v32]; t in seconds of video time, v = visibility 0..1.
export type PoseFrameRow = number[];

export type PoseTrack = {
  v: typeof POSE_VERSION;
  fps: number; // sample rate of `frames`
  w: number; // source video width in px
  h: number; // source video height in px
  duration: number; // seconds
  frames: PoseFrameRow[]; // sorted by t, already smoothed (One Euro)
};

// MediaPipe landmark indices for the joints the player uses.
export const JOINT = {
  nose: 0,
  left_shoulder: 11,
  right_shoulder: 12,
  left_elbow: 13,
  right_elbow: 14,
  left_wrist: 15,
  right_wrist: 16,
  left_hip: 23,
  right_hip: 24,
  left_knee: 25,
  right_knee: 26,
  left_ankle: 27,
  right_ankle: 28,
} as const;

export type JointName = keyof typeof JOINT;
