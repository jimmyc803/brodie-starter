// Strength ranks: the discrete, named tiers that replace the old continuous score gradient. Each muscle group earns one
// rank from its stored score (0..1) — the highest tier whose `minScore` it meets. Every tier is a Brodie at a different
// stage (shriveled -> ascended) with its own alliterative-animal name, a brand-safe color (Brodie is never pink) and a
// graphic (see RankBadge). The top tier is pure white: Brodie ascends into god form.
//
// On top of the per-muscle rank, a session earns one overall rank (today's rank badge + the rank on the recap image):
// the same scores drive it, so it measures how well you trained today (form + completion), not how strong you are.
import type { MuscleKey, SessionView } from "@/lib/contract";
import { completedReps } from "@/lib/contract";

export type Rank = {
  key: string;
  tier: number; // 1..8, weakest -> strongest
  name: string;
  animal: string;
  color: string;
  minScore: number; // 0..1; a score earns the highest tier it reaches
  brodie: string; // which Brodie this is
  blurb: string;
};

export const RANKS: Rank[] = [
  { key: "chud-chicken",     tier: 1, name: "Chud Chicken",      animal: "Chicken",    color: "#B5835A", minScore: 0,    brodie: "Shriveled Brodie",   blurb: "Skipped the workout. Rest day became rest week." },
  { key: "egolift-elephant", tier: 2, name: "Egolift Elephant",  animal: "Elephant",   color: "#8A8F98", minScore: 0.15, brodie: "Soft Brodie",        blurb: "All ego, no form. Heavy bar, light on reps that count." },
  { key: "endurance-eagle",  tier: 3, name: "Endurance Eagle",   animal: "Eagle",      color: "#C98A2B", minScore: 0.30, brodie: "Lean Brodie",        blurb: "Built a base. Goes the distance — now add mass." },
  { key: "hypertrophy-hippo",tier: 4, name: "Hypertrophy Hippo", animal: "Hippo",      color: "#159A8C", minScore: 0.45, brodie: "Growing Brodie",     blurb: "The pump is real. Size added week over week." },
  { key: "microtear-mako",   tier: 5, name: "Microtear Mako",    animal: "Mako Shark", color: "#2F7FE4", minScore: 0.60, brodie: "Shredded Brodie",    blurb: "Fibers torn, lines showing. Sharp and still hungry." },
  { key: "strength-gorilla", tier: 6, name: "Strength Gorilla",  animal: "Gorilla",    color: "#7A4FD0", minScore: 0.75, brodie: "Powerful Brodie",    blurb: "Raw silverback strength. The bar bends." },
  { key: "mega-mammoth",     tier: 7, name: "Mega Mammoth",      animal: "Mammoth",    color: "#E8B923", minScore: 0.88, brodie: "Mega-Jacked Brodie", blurb: "Prehistoric mass. The gym bought heavier plates for you." },
  { key: "godmode-griffin",  tier: 8, name: "Godmode Griffin",   animal: "Griffin",    color: "#F4F4F0", minScore: 0.97, brodie: "Ascended Brodie",    blurb: "Full send into super-god form. Leaves the mortal plane." },
];

// The rank a 0..1 score earns. An untrained muscle (no score) has no rank — handle that at the call site.
export function rankForScore(score: number): Rank {
  let out = RANKS[0];
  for (const r of RANKS) if (score >= r.minScore) out = r;
  return out;
}

// The next tier up the ladder, or null at the top (Godmode Griffin).
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

// Today's overall rank. A workout with no reps counted is skipped: it lands on the lowest tier (Chud Chicken) with no
// score, so the recap stays honest ("every Brodie starts somewhere") instead of celebrating a session that never happened.
export function sessionRank(view: SessionView): SessionRank {
  const reps = view.exercises.reduce((n, ex) => n + completedReps(ex), 0);
  const score = sessionScore(view);
  if (reps === 0 || score === null) return { rank: RANKS[0], score: null, next: nextRank(RANKS[0]), skipped: true };
  const rank = rankForScore(score);
  return { rank, score, next: nextRank(rank), skipped: false };
}
