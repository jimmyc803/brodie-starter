import { describe, expect, it } from "vitest";

import { muscleRank, RANKS, rankForScore, sessionRank } from "@/lib/ranks";
import { sampleSessionView } from "@/lib/session-view";

// Hue in degrees + saturation, to assert no tier reads as pink (Brodie is never pink).
function hsl(hex: string) {
  const n = parseInt(hex.slice(1), 16);
  const r = ((n >> 16) & 255) / 255,
    g = ((n >> 8) & 255) / 255,
    b = (n & 255) / 255;
  const mx = Math.max(r, g, b),
    mn = Math.min(r, g, b),
    d = mx - mn;
  let h = 0;
  if (d !== 0) {
    if (mx === r) h = ((g - b) / d) % 6;
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h = (h * 60 + 360) % 360;
  }
  return { h, s: mx === 0 ? 0 : d / mx };
}

describe("rank ladder", () => {
  it("has eight tiers ordered weakest -> strongest with increasing thresholds", () => {
    expect(RANKS).toHaveLength(8);
    for (let i = 1; i < RANKS.length; i++) {
      expect(RANKS[i].tier).toBe(RANKS[i - 1].tier + 1);
      expect(RANKS[i].minScore).toBeGreaterThan(RANKS[i - 1].minScore);
    }
  });

  it("awards the highest tier a score reaches", () => {
    expect(rankForScore(0).key).toBe("chud-chicken");
    expect(rankForScore(0.1).key).toBe("chud-chicken");
    expect(rankForScore(0.15).key).toBe("egolift-elephant");
    expect(rankForScore(0.5).key).toBe("hypertrophy-hippo");
    expect(rankForScore(0.75).key).toBe("strength-gorilla");
    expect(rankForScore(0.86).key).toBe("strength-gorilla");
    expect(rankForScore(0.88).key).toBe("mega-mammoth");
    expect(rankForScore(1).key).toBe("godmode-griffin");
  });

  it("clamps below the first and at/above the last tier", () => {
    expect(rankForScore(-1).key).toBe("chud-chicken");
    expect(rankForScore(2).key).toBe("godmode-griffin");
  });

  it("never uses a pink tier color", () => {
    for (const r of RANKS) {
      const { h, s } = hsl(r.color);
      expect(h >= 300 && h <= 345 && s > 0.25, `${r.name} ${r.color} reads as pink`).toBe(false);
    }
  });

  it("tops out at white (god form)", () => {
    expect(RANKS[RANKS.length - 1].color.toUpperCase()).toBe("#F4F4F0");
  });
});

describe("session rank", () => {
  it("gives Chud Chicken (skipped) to a workout with no reps counted", () => {
    const view = sampleSessionView();
    for (const ex of view.exercises) for (const s of ex.sets) { s.completed_reps = 0; s.reps = []; }
    view.muscles = view.muscles.map((m) => ({ ...m, score: 0, color: "gray" as const, coverage: "none" as const }));
    expect(sessionRank(view)).toMatchObject({ skipped: true, rank: { key: "chud-chicken" } });
  });

  it("ranks the sample session and its muscles; untrained muscles get no rank", () => {
    const r = sessionRank(sampleSessionView());
    expect(r.skipped).toBe(false);
    expect(r.score).toBeGreaterThan(0);
    expect(muscleRank({ muscle: "lats", score: 0, color: "gray" })).toBeNull();
    expect(muscleRank({ muscle: "lats", score: 0.8, color: "green" })?.key).toBe("strength-gorilla");
  });
});
