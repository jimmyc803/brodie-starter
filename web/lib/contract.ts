// Types and rules for the team data contract (db/schema.sql, shared/muscles.json). The JSON comes from
// lib/generated/, copied from the repo root by scripts/sync-contract.mjs.
import muscles from "@/lib/generated/muscles.json";
import faultCues from "@/lib/generated/fault_cues.json";

export type MuscleKey =
  | "quads" | "glutes" | "hamstrings" | "calves" | "adductors" | "abductors" | "chest" | "front_delts" | "triceps"
  | "biceps" | "forearms" | "abs" | "obliques" | "lats" | "traps" | "rear_delts";
export type ExerciseKey = "squat" | "pushup" | "lunge" | "jumping_jack" | "bicep_curl" | "pullup";
export type Color = "green" | "yellow" | "red" | "gray";
export type Coverage = "primary" | "secondary" | "none";

export type Rep = { rep_number: number; t?: number; faults: string[] };
export type SetView = {
  set_number: number;
  planned_reps: number;
  completed_reps: number;
  started_at?: string | null;
  ended_at?: string | null;
  reps: Rep[];
};
export type ExerciseView = {
  exercise_key: string;
  name: string;
  planned_sets: number;
  planned_reps: number;
  sets: SetView[];
};
// A stretch of workout footage for one exercise (signed storage URL, seconds into the video; end null = to the end).
export type ExerciseClip = { exercise_key: string; url: string; start: number; end: number | null };
export type MuscleScore = { muscle: MuscleKey; score: number; color: Color; coverage: Coverage };

// GET /api/session/[token]: what the recap page and the recap image read.
export type SessionView = {
  session: { id: string; started_at: string; ended_at: string | null; share_token: string };
  client: { name: string };
  coach: { name: string };
  day: { title: string; day_number: number } | null;
  exercises: ExerciseView[];
  muscles: MuscleScore[];
};

type MuscleInfo = { label: string; view: "front" | "back" | "both" };
type ExerciseInfo = { name: string; plan_name: string; primary: MuscleKey[]; secondary: MuscleKey[] };

export const MUSCLES = muscles.muscles as Record<MuscleKey, MuscleInfo>;
export const MUSCLE_KEYS = Object.keys(MUSCLES) as MuscleKey[];
export const EXERCISES = muscles.exercises as unknown as Record<ExerciseKey, ExerciseInfo>;
export const COLORS = muscles.scoring.colors as Record<Color, string>;
export const GRAY_LABEL: string = muscles.scoring.gray_label;
export const THRESHOLDS = muscles.scoring.thresholds as { green_min: number; yellow_min: number };
const FAULT_PREFIX = muscles.fault_prefix as unknown as Record<string, string>;
const CUES = faultCues as Record<string, string>;

export function exerciseName(key: string, fallback?: string): string {
  return EXERCISES[key as ExerciseKey]?.name ?? fallback ?? key;
}

// Brodie fault labels ("squats - knees over toes") -> the short cue Brodie says out loud ("Hips back").
// Labels without a cue (bicep curls are new) fall back to the label text after the exercise prefix.
export function faultText(label: string): string {
  if (CUES[label]) return CUES[label];
  const dash = label.indexOf(" - ");
  const rest = dash >= 0 ? label.slice(dash + 3) : label;
  return rest.charAt(0).toUpperCase() + rest.slice(1);
}

export function faultPrefix(exerciseKey: string): string | undefined {
  return FAULT_PREFIX[exerciseKey];
}

// Exercises that hit a muscle in this session, with the role, for the tap-a-muscle detail.
export function exercisesForMuscle(view: SessionView, muscle: MuscleKey) {
  const out: { exercise: ExerciseView; role: "primary" | "secondary" }[] = [];
  for (const ex of view.exercises) {
    const info = EXERCISES[ex.exercise_key as ExerciseKey];
    if (!info || completedReps(ex) === 0) continue;
    if (info.primary.includes(muscle)) out.push({ exercise: ex, role: "primary" });
    else if (info.secondary.includes(muscle)) out.push({ exercise: ex, role: "secondary" });
  }
  return out;
}

export const completedReps = (ex: ExerciseView) => ex.sets.reduce((n, s) => n + s.completed_reps, 0);
export const plannedReps = (ex: ExerciseView) => ex.sets.reduce((n, s) => n + s.planned_reps, 0);
export const faultyReps = (s: SetView) => s.reps.filter((r) => r.faults.length > 0).length;
export const setReached = (s: SetView) => s.completed_reps > 0 || s.reps.length > 0;

// The most common faults across a set of reps, as [cue text, count], most frequent first.
export function topFaults(reps: Rep[], n = 3): [string, number][] {
  const counts = new Map<string, number>();
  for (const r of reps) for (const f of r.faults) counts.set(faultText(f), (counts.get(faultText(f)) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, n);
}

// Every muscle in contract order; muscles missing from the view are gray / not trained.
export function allMuscles(view: SessionView): MuscleScore[] {
  const by = new Map(view.muscles.map((m) => [m.muscle, m]));
  return MUSCLE_KEYS.map((k) => by.get(k) ?? { muscle: k, score: 0, color: "gray", coverage: "none" });
}
