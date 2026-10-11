// Heat map coloring options for the design lab (/lab/heatmap). Each variant turns a session view into a fill per
// muscle, using only what the data has: muscle_scores (score 0..1, color, coverage) and the reps per exercise.
import { mixOklch, ramp } from "@/lib/color";
import { allMuscles, COLORS, completedReps, EXERCISES, THRESHOLDS, type ExerciseKey, type MuscleKey, type SessionView } from "@/lib/contract";

export type Fill = { fill: string; glow: number }; // glow 0..1: how strongly this muscle glows (variants with glow)
export type Fills = Partial<Record<MuscleKey, Fill>>;
export type VariantId = "flat" | "gradient" | "depth" | "thermal" | "neon";

export const UNTRAINED = "#52525b"; // zinc-600: a muscle no exercise hit, darker than the old light gray so color pops

// Score -> color, with the team's three colors pinned at the contract thresholds (yellow at 0.5, green at 0.75).
export const SCORE_STOPS: [number, string][] = [
  [0, "#dc2626"],
  [0.3, COLORS.red],
  [THRESHOLDS.yellow_min, COLORS.yellow],
  [THRESHOLDS.green_min, COLORS.green],
  [1, "#4ade80"],
];
export const scoreColor = (score: number) => ramp(SCORE_STOPS, score);

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
    if (m.color === "gray") {
      out[m.muscle] = { fill: id === "flat" ? COLORS.gray : UNTRAINED, glow: 0 };
      continue;
    }
    if (id === "flat") {
      out[m.muscle] = { fill: COLORS[m.color], glow: 0 };
      continue;
    }
    let fill = scoreColor(m.score);
    // depth/neon: secondary muscles are a paler version (worked a little), primary at full strength (worked hard)
    if ((id === "depth" || id === "neon") && m.coverage === "secondary") fill = mixOklch(fill, UNTRAINED, 0.45);
    // neon: glow follows the score, so solid muscles shine and problem areas stay calm and readable
    const glow = id === "neon" ? (m.coverage === "primary" ? 0.35 + 0.65 * m.score : 0.2 * m.score) : 0;
    out[m.muscle] = { fill, glow };
  }
  return out;
}

// Order in which muscles light up for the animated reveal: by the first exercise (in workout order) that hit them.
export function revealOrder(view: SessionView): Partial<Record<MuscleKey, number>> {
  const order: Partial<Record<MuscleKey, number>> = {};
  view.exercises.forEach((ex, i) => {
    const info = EXERCISES[ex.exercise_key as ExerciseKey];
    if (!info || !completedReps(ex)) return;
    for (const m of [...info.primary, ...info.secondary]) if (order[m] === undefined) order[m] = i;
  });
  return order;
}
