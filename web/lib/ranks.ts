// Ranks: a game layer on top of the heat map (Squash feature #3). The rank comes from the same stored scores as the
// heat map, so it measures how well you trained today (form + completion), not how strong you are.
// Brodie tier art goes here later (art from the official character kit only: cream body, never pink).
import type { MuscleKey, SessionView } from "@/lib/contract";
import { completedReps } from "@/lib/contract";

export type RankId = "chud" | "newt" | "goblin" | "seal" | "hippo" | "moose" | "ascended";
export type Rank = { id: RankId; name: string; min: number; color: string; tier: number };

// Ladder, lowest first. min = lowest score that earns the rank. Chud Chicken is only for a skipped workout.
export const RANKS: Rank[] = [
  { id: "chud", name: "Chud Chicken", min: -1, color: "#6b7280", tier: 0 },
  { id: "newt", name: "Noodle Newt", min: 0, color: "#a1a1aa", tier: 1 },
  { id: "goblin", name: "Gym Goblin", min: 0.4, color: "#cd7f32", tier: 2 },
  { id: "seal", name: "Swole Seal", min: 0.55, color: "#d4d4d8", tier: 3 },
  { id: "hippo", name: "Hypertrophy Hippo", min: 0.7, color: "#facc15", tier: 4 },
  { id: "moose", name: "Mega Moose", min: 0.85, color: "#10b981", tier: 5 },
  { id: "ascended", name: "Ascended Brodie", min: 0.95, color: "#ffffff", tier: 6 },
];
const LADDER = RANKS.slice(1); // ranks a trained muscle or a real workout can earn

export function rankForScore(score: number): Rank {
  let r = LADDER[0];
  for (const x of LADDER) if (score >= x.min) r = x;
  return r;
}

export function nextRank(rank: Rank): Rank | null {
  return rank.id === "chud" ? LADDER[0] : (LADDER[LADDER.indexOf(rank) + 1] ?? null);
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

export function sessionRank(view: SessionView): SessionRank {
  const reps = view.exercises.reduce((n, ex) => n + completedReps(ex), 0);
  const score = sessionScore(view);
  if (reps === 0 || score === null) return { rank: RANKS[0], score: null, next: LADDER[0], skipped: true };
  const rank = rankForScore(score);
  return { rank, score, next: nextRank(rank), skipped: false };
}

export function muscleRank(m: { muscle: MuscleKey; score: number; color: string }): Rank | null {
  return m.color === "gray" ? null : rankForScore(m.score);
}
