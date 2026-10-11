// Strength ranks: discrete, named tiers (Novice -> Legendary). Each muscle group earns one rank from its stored score
// (0..1): the highest tier whose `minScore` it meets. A tier's color is exactly the color its muscles are painted on the
// heat map (see neonFill), built from the team's red / yellow / green so the ladder reads like the body does. The tier
// edges include the contract thresholds (0.5 yellow, 0.75 green), so a rank never disagrees with a muscle's color dot.
//
// On top of the per-muscle rank, a session earns one overall rank (today's rank on the recap + the recap image): the
// same scores drive it, so it measures how well you trained today (form + completion), not how strong you are.
import { mixOklch } from "@/lib/color";
import type { MuscleKey, SessionView } from "@/lib/contract";
import { COLORS, completedReps } from "@/lib/contract";

export type Rank = {
  key: string;
  tier: number; // 1..8, weakest -> strongest
  name: string;
  color: string;
  minScore: number; // 0..1; a score earns the highest tier it reaches
};

const { red, yellow, green } = COLORS;

export const RANKS: Rank[] = [
  { key: "novice",       tier: 1, name: "Novice",       color: mixOklch(red, "#000000", 0.22), minScore: 0 },
  { key: "beginner",     tier: 2, name: "Beginner",     color: red,                            minScore: 0.2 },
  { key: "intermediate", tier: 3, name: "Intermediate", color: mixOklch(red, yellow, 0.5),     minScore: 0.35 },
  { key: "advanced",     tier: 4, name: "Advanced",     color: yellow,                         minScore: 0.5 },
  { key: "expert",       tier: 5, name: "Expert",       color: mixOklch(yellow, green, 0.45),  minScore: 0.62 },
  { key: "elite",        tier: 6, name: "Elite",        color: green,                          minScore: 0.75 },
  { key: "master",       tier: 7, name: "Master",       color: mixOklch(green, "#ffffff", 0.3), minScore: 0.88 },
  { key: "legendary",    tier: 8, name: "Legendary",    color: mixOklch(green, "#ffffff", 0.6), minScore: 0.97 },
];

// The rank a 0..1 score earns. An untrained muscle (no score) has no rank — handle that at the call site.
export function rankForScore(score: number): Rank {
  let out = RANKS[0];
  for (const r of RANKS) if (score >= r.minScore) out = r;
  return out;
}

// The next tier up the ladder, or null at the top (Legendary).
export function nextRank(rank: Rank): Rank | null {
  return RANKS[RANKS.indexOf(rank) + 1] ?? null;
}

// A single muscle's rank. Untrained (gray) muscles have no rank.
export function muscleRank(m: { muscle: MuscleKey; score: number; color: string }): Rank | null {
  return m.color === "gray" ? null : rankForScore(m.score);
}

// The session's score: average of the trained muscles' scores, main muscles counting double (helpers half).
export function sessionScore(view: SessionView): number | null {
  let num = 0;
  let den = 0;
  for (const m of view.muscles) {
    if (m.color === "gray" || m.coverage === "none") continue;
    const w = m.coverage === "primary" ? 1 : 0.5;
    num += w * m.score;
    den += w;
  }
  return den ? num / den : null;
}

export type SessionRank = { rank: Rank; score: number | null; next: Rank | null; skipped: boolean };

// Today's overall rank. A workout with no reps counted is skipped: it lands on the lowest tier (Novice) with no score,
// so the recap stays honest instead of celebrating a session that never happened.
export function sessionRank(view: SessionView): SessionRank {
  const reps = view.exercises.reduce((n, ex) => n + completedReps(ex), 0);
  const score = sessionScore(view);
  if (reps === 0 || score === null) return { rank: RANKS[0], score: null, next: nextRank(RANKS[0]), skipped: true };
  const rank = rankForScore(score);
  return { rank, score, next: nextRank(rank), skipped: false };
}
