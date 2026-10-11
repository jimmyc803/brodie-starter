import type { MuscleKey } from "@/lib/contract";
import type { JointName } from "@/lib/rep-review/pose-types";

// Rep review clips for <RepReviewPlayer />. Everything the overlay shows (rep times, scores, flags, cues, insight) is
// hardcoded here; the only computed data is the skeleton (pose landmarks, cached per clip — see lib/rep-review/pose.ts).
// A clip in public/clips/<name>.mp4 can ship a precomputed <name>.pose.json (scripts/pose-landmarks.py) to skip detection.

export type Accent = "volt" | "blood" | "ice";
export const ACCENTS: Record<Accent, string> = { volt: "#D4FF00", blood: "#FF2D2D", ice: "#3DF5FF" };

export type ReviewRep = {
  t: number; // seconds into the clip when the rep counts (the clicker ticks here)
  score: number; // 0–100
  flag?: string; // e.g. "KNEE CAVE": triggers the slow-mo flag moment
  cue?: string; // "Tristan's standard: knees track over toes" → lower third (text before ":" is the label)
  faultAt?: number; // seconds: when the fault is visible (slow-mo centres here); defaults to 0.45 s before t
};

export type TrackedAngle = {
  name: string; // "Knee"
  joints: [JointName, JointName, JointName]; // angle is measured at the middle joint
  target?: string; // "< 90°" or "> 160°": the pill flashes the accent while it's met
};

export type ReviewClip = {
  id: string;
  clipUrl: string;
  poster?: string;
  coachName: string;
  clientName: string; // "[Client]" is replaced by the dashboard's client name
  exercise: string;
  setLabel: string;
  muscles: MuscleKey[];
  trackedAngles: TrackedAngle[];
  traceJoint: JointName;
  reps: ReviewRep[];
  setScore: number;
  insight: string; // coach only
  accent?: Accent; // default volt
};

export const REVIEW_CLIPS: ReviewClip[] = [
  {
    id: "squat-set3",
    clipUrl: "/clips/squat-set3.mp4",
    poster: "/clips/squat-set3.jpg",
    coachName: "Tristan",
    clientName: "[Client]",
    exercise: "Squat",
    setLabel: "Set 3",
    muscles: ["quads", "glutes", "hamstrings", "adductors"],
    trackedAngles: [
      { name: "Knee", joints: ["right_hip", "right_knee", "right_ankle"], target: "< 120°" },
      { name: "Hip", joints: ["right_shoulder", "right_hip", "right_knee"] },
    ],
    traceJoint: "right_hip",
    reps: [
      { t: 1.63, score: 94 },
      { t: 3.8, score: 91 },
      { t: 6.3, score: 68, flag: "SHALLOW DEPTH", cue: "Tristan's standard: hips break below the knees", faultAt: 5.83 },
      { t: 9.13, score: 86 },
      { t: 11.37, score: 79 },
    ],
    setScore: 81,
    insight: "Form drops 23% in the final 3 reps — 4 of the last 5 sessions.",
  },
  {
    id: "squat-set2",
    clipUrl: "/clips/squat-form-set2.mp4",
    poster: "/clips/squat-form-set2.jpg",
    coachName: "Tristan",
    clientName: "[Client]",
    exercise: "Squat",
    setLabel: "Set 2",
    muscles: ["quads", "glutes", "hamstrings", "adductors"],
    trackedAngles: [
      { name: "Knee", joints: ["right_hip", "right_knee", "right_ankle"], target: "< 120°" },
      { name: "Hip", joints: ["right_shoulder", "right_hip", "right_knee"] },
    ],
    traceJoint: "right_hip",
    reps: [
      { t: 1.7, score: 92 },
      { t: 3.97, score: 74, flag: "SHALLOW DEPTH", cue: "Tristan's standard: sit back, chest up", faultAt: 3.47 },
      { t: 7.8, score: 90 },
      { t: 11.03, score: 89 },
    ],
    setScore: 87,
    insight: "Depth comes back after one cue — rep 2 is the only one above parallel.",
  },
];

// Clips that worked a muscle, worst set first (the coach sees what needs a look before what went well).
export function clipsForMuscle(muscle: MuscleKey, clips: ReviewClip[] = REVIEW_CLIPS): ReviewClip[] {
  return clips.filter((c) => c.muscles.includes(muscle)).sort((a, b) => a.setScore - b.setScore);
}
