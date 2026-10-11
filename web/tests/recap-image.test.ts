import { describe, expect, it } from "vitest";

import { UNTRAINED } from "@/lib/body/neon";
import { ALL_SOLID, LEGEND, NO_REPS, recapCard } from "@/lib/recap-image/model";
import { sampleSessionView } from "@/lib/session-view";

describe("recap image card", () => {
  it("summarizes the sample session", () => {
    const card = recapCard(sampleSessionView());
    expect(card.title).toBe("Ryan's workout");
    expect(card.subtitle).toBe("Day 1 - Full body · Coach Tristan");
    expect(card.stats.map((s) => s.value)).toEqual(["90/110", "10/11", expect.stringMatching(/^\d+%$/)]);
    expect(card.focus).toEqual(["Biceps", "Forearms", "Front delts"]); // red first, then the lowest yellow
    expect(card.fills.lats).toEqual({ fill: UNTRAINED, glow: 0 });
    expect(card.fills.quads?.glow).toBeGreaterThan(0);
  });

  it("says everything is solid when nothing is red or yellow", () => {
    const view = sampleSessionView();
    view.muscles = view.muscles.map((m) => (m.color === "gray" ? m : { ...m, color: "green" }));
    expect(recapCard(view).focus).toEqual([]);
    expect(recapCard(view).focusLine).toBe(ALL_SOLID);
  });

  it("never uses the word weak", () => {
    const text = JSON.stringify([recapCard(sampleSessionView()), LEGEND]);
    expect(text.toLowerCase()).not.toContain("weak");
  });
  it("does not praise a session where no reps were counted", () => {
    const view = sampleSessionView();
    for (const ex of view.exercises) for (const set of ex.sets) { set.completed_reps = 0; set.reps = []; }
    view.muscles = view.muscles.map((m) => ({ ...m, score: 0, color: "gray" as const, coverage: "none" as const }));
    const card = recapCard(view);
    expect(card.focusKind).toBe("empty");
    expect(card.focusLine).toBe(NO_REPS);
  });
});
