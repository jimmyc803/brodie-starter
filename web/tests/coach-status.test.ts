import { describe, expect, it } from "vitest";

import { sortSummaries, summarizeClient } from "@/lib/coach-status";
import type { SessionView } from "@/lib/contract";
import sample from "@/lib/generated/sample_session.json";

const NOW = Date.parse("2026-10-11T18:00:00Z");
const DAY = 24 * 60 * 60 * 1000;
const base = sample as unknown as SessionView;

function at(daysAgo: number, clean = false): SessionView {
  const iso = new Date(NOW - daysAgo * DAY).toISOString();
  return {
    ...base,
    session: { ...base.session, started_at: iso },
    exercises: clean
      ? base.exercises.map((ex) => ({ ...ex, sets: ex.sets.map((s) => ({ ...s, completed_reps: s.planned_reps, reps: s.reps.map((r) => ({ ...r, faults: [] })) })) }))
      : base.exercises,
  };
}

describe("coach triage status", () => {
  it("flags a recent session with short or mostly-faulty sets for review", () => {
    const s = summarizeClient({ id: "a", name: "A", sessions: [at(0)] }, NOW);
    expect(s.status).toBe("review");
    expect(s.detail).toMatch(/^Today · \d+ sets to review$/);
  });
  it("calls an all-clean recent session on track", () => {
    expect(summarizeClient({ id: "b", name: "B", sessions: [at(1, true)] }, NOW).status).toBe("on_track");
  });
  it("flags a recent call with no counted reps for review", () => {
    const session = at(0, true);
    session.exercises = session.exercises.map((ex) => ({
      ...ex, sets: ex.sets.map((s) => ({ ...s, completed_reps: 0, reps: [] })),
    }));
    const summary = summarizeClient({ id: "empty", name: "Empty", sessions: [session] }, NOW);
    expect(summary.status).toBe("review");
    expect(summary.detail).toMatch(/no reps counted/i);
  });
  it("flags unreached sets even when every reached set was clean and complete", () => {
    const session = at(0, true);
    session.exercises = session.exercises.map((ex, i) => i === 0 ? ex : ({
      ...ex, sets: ex.sets.map((s) => ({ ...s, completed_reps: 0, reps: [] })),
    }));
    const summary = summarizeClient({ id: "partial", name: "Partial", sessions: [session] }, NOW);
    expect(summary.status).toBe("review");
    expect(summary.detail).toMatch(/incomplete/i);
  });
  it("calls a client inactive after 7 days or with no sessions", () => {
    expect(summarizeClient({ id: "c", name: "C", sessions: [at(9)] }, NOW).detail).toBe("No session in 9 days");
    expect(summarizeClient({ id: "d", name: "D", sessions: [] }, NOW).status).toBe("inactive");
  });
  it("sorts review, then on track, then inactive", () => {
    const list = sortSummaries([
      summarizeClient({ id: "i", name: "I", sessions: [] }, NOW),
      summarizeClient({ id: "o", name: "O", sessions: [at(1, true)] }, NOW),
      summarizeClient({ id: "r", name: "R", sessions: [at(2)] }, NOW),
    ]);
    expect(list.map((s) => s.id)).toEqual(["r", "o", "i"]);
  });
});
