// Heat map coloring options for the design lab (/lab/heatmap). Each variant turns a session view into a fill per
// muscle, using only what the data has: muscle_scores (score 0..1, color, coverage) and the reps per exercise.
// The chosen look ("neon") lives in lib/body/neon.ts and is what the app ships.
import { neonFill, scoreColor, UNTRAINED, type Fills } from "@/lib/body/neon";
import { mixOklch, ramp } from "@/lib/color";
import { allMuscles, COLORS, completedReps, EXERCISES, type ExerciseKey, type MuscleKey, type SessionView } from "@/lib/contract";

export { revealOrder } from "@/lib/recap";
export { SCORE_STOPS, UNTRAINED, scoreColor, type Fill, type Fills } from "@/lib/body/neon";
export type VariantId = "flat" | "gradient" | "depth" | "thermal" | "neon";

// Volume (reps x role weight) -> heat, for the thermal look.
export const THERMAL_STOPS: [number, string][] = [
  [0, "#312e81"],
  [0.3, "#9333ea"],
  [0.55, "#ef4444"],
  [0.8, "#f97316"],
  [1, "#fde68a"],
];

export function muscleVolume(view: SessionView): Partial<Record<MuscleKey, number>> {
  const v: Partial<Record<MuscleKey, number>> = {};
  for (const ex of view.exercises) {
    const info = EXERCISES[ex.exercise_key as ExerciseKey];
    const reps = completedReps(ex);
    if (!info || !reps) continue;
    for (const m of info.primary) v[m] = (v[m] ?? 0) + reps;
    for (const m of info.secondary) v[m] = (v[m] ?? 0) + reps * 0.5;
  }
  return v;
}

export function variantFills(view: SessionView, id: VariantId): Fills {
  const muscles = allMuscles(view);
  const out: Fills = {};
  if (id === "thermal") {
    const vol = muscleVolume(view);
    const max = Math.max(1, ...Object.values(vol).map((x) => x ?? 0));
    for (const m of muscles) {
      const x = vol[m.muscle];
      out[m.muscle] = x ? { fill: ramp(THERMAL_STOPS, x / max), glow: x / max } : { fill: UNTRAINED, glow: 0 };
    }
    return out;
  }
  for (const m of muscles) {
    if (id === "neon") {
      out[m.muscle] = neonFill(m);
      continue;
    }
    if (m.color === "gray") {
      out[m.muscle] = { fill: id === "flat" ? COLORS.gray : UNTRAINED, glow: 0 };
      continue;
    }
    if (id === "flat") {
      out[m.muscle] = { fill: COLORS[m.color], glow: 0 };
      continue;
    }
    let fill = scoreColor(m.score);
    if (id === "depth" && m.coverage === "secondary") fill = mixOklch(fill, UNTRAINED, 0.45);
    out[m.muscle] = { fill, glow: 0 };
  }
  return out;
}
