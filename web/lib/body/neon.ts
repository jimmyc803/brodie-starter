// Every trained muscle uses its exact rank color on the web and recap image. Coverage changes
// only the surrounding halo, never the fill, so the body always matches the rank legend.
import { SHAPES, type BodySide } from "@/lib/body/shapes";
import { ramp } from "@/lib/color";
import { rankForScore } from "@/lib/ranks";
import { COLORS, MUSCLE_KEYS, THRESHOLDS, type Color, type Coverage, type MuscleKey } from "@/lib/contract";

export type Fill = { fill: string; glow: number }; // glow 0..1
export type Fills = Partial<Record<MuscleKey, Fill>>;
export type MuscleInput = { muscle: MuscleKey; score: number; color: Color; coverage: Coverage };

export const UNTRAINED = "#52525b"; // a muscle no exercise hit ("not trained this session")
export const BODY_BASE = "#3f3f46"; // unscored parts: head, neck, knees, lower back
export const BODY_STROKE = "#18181b";

// The continuous score ramp (team colors pinned at the contract thresholds), kept for the /lab/heatmap variants.
export const SCORE_STOPS: [number, string][] = [
  [0, "#dc2626"],
  [0.3, COLORS.red],
  [THRESHOLDS.yellow_min, COLORS.yellow],
  [THRESHOLDS.green_min, COLORS.green],
  [1, "#4ade80"],
];
export const scoreColor = (score: number) => ramp(SCORE_STOPS, score);

export function neonFill(m: MuscleInput): Fill {
  if (m.color === "gray") return { fill: UNTRAINED, glow: 0 };
  const base = rankForScore(m.score).color;
  if (m.coverage === "secondary") return { fill: base, glow: 0.2 * m.score };
  return { fill: base, glow: 0.35 + 0.65 * m.score };
}

// Every contract muscle gets a fill; muscles missing from the input are untrained.
export function neonFills(muscles: MuscleInput[]): Fills {
  const by = new Map(muscles.map((m) => [m.muscle, m]));
  return Object.fromEntries(
    MUSCLE_KEYS.map((k) => [k, by.has(k) ? neonFill(by.get(k)!) : { fill: UNTRAINED, glow: 0 }]),
  ) as Fills;
}

export type NeonLayers = {
  gradients: { id: string; inner: string; outer: string }[];
  halo: { points: string; fill: string; opacity: number; muscle: MuscleKey }[];
  shapes: { points: string; muscle: MuscleKey | null; fill: string; solid: string }[]; // solid rank colors
};

export function neonLayers(side: BodySide, fills: Fills, _idPrefix: string, glow = true): NeonLayers {
  const out: NeonLayers = { gradients: [], halo: [], shapes: [] };
  SHAPES[side].forEach((s) => {
    const f = s.muscle ? fills[s.muscle] : undefined;
    if (!s.muscle || !f) {
      out.shapes.push({ points: s.points, muscle: s.muscle, fill: BODY_BASE, solid: BODY_BASE });
      return;
    }
    if (glow && f.glow > 0) {
      out.halo.push({ points: s.points, fill: f.fill, opacity: 0.75 * f.glow, muscle: s.muscle });
    }
    out.shapes.push({ points: s.points, muscle: s.muscle, fill: f.fill, solid: f.fill });
  });
  return out;
}
