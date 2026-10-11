import { describe, expect, it } from "vitest";

import { muscleRank, RANKS, rankForScore, sessionRank } from "@/lib/ranks";
import { sampleSessionView } from "@/lib/session-view";

describe("ranks", () => {
  it("climbs the ladder by score", () => {
    expect(rankForScore(0).name).toBe("Noodle Newt");
    expect(rankForScore(0.4).name).toBe("Gym Goblin");
    expect(rankForScore(0.7).name).toBe("Hypertrophy Hippo");
    expect(rankForScore(0.99).name).toBe("Ascended Brodie");
  });
  it("gives Chud Chicken only to a workout with no reps", () => {
    const view = sampleSessionView();
    for (const ex of view.exercises) for (const s of ex.sets) { s.completed_reps = 0; s.reps = []; }
    view.muscles = view.muscles.map((m) => ({ ...m, score: 0, color: "gray" as const, coverage: "none" as const }));
    expect(sessionRank(view)).toMatchObject({ skipped: true, rank: { id: "chud" } });
    expect(rankForScore(0).id).not.toBe("chud");
  });
  it("ranks the sample session and its muscles; untrained muscles get no rank", () => {
    const r = sessionRank(sampleSessionView());
    expect(r.skipped).toBe(false);
    expect(r.score).toBeGreaterThan(0);
    expect(muscleRank({ muscle: "lats", score: 0, color: "gray" })).toBeNull();
  });
  it("never uses pink and ends in white", () => {
    for (const x of RANKS) expect(x.color.toLowerCase()).not.toMatch(/^#(f9a8d4|ec4899|f472b6|db2777|ffc0cb)$/);
    expect(RANKS.at(-1)?.color).toBe("#ffffff");
  });
});
