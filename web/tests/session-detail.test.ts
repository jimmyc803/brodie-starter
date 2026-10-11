import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { SessionDetail } from "@/components/coach/session-detail";
import type { SessionView } from "@/lib/contract";
import sample from "@/lib/generated/sample_session.json";

const base = sample as unknown as SessionView;

function viewWithCompletedExercises(count: number): SessionView {
  return {
    ...base,
    exercises: base.exercises.map((ex, i) => ({
      ...ex,
      sets: ex.sets.map((s) => ({
        ...s,
        completed_reps: i < count ? s.planned_reps : 0,
        reps: i < count ? s.reps.map((r) => ({ ...r, faults: [] })) : [],
      })),
    })),
  };
}

describe("coach session completion feedback", () => {
  it.each([0, 1])("does not praise unreached exercises or a session with only %i exercises completed", (count) => {
    const html = renderToStaticMarkup(createElement(SessionDetail, { view: viewWithCompletedExercises(count), clientName: "Client" }));
    expect(html).not.toContain("Every set hit its reps");
    expect(html).toContain("Not reached");
    expect(html).toContain(count === 0 ? "No reps counted this session" : "Session incomplete");
  });

  it("keeps positive feedback for a completed clean session", () => {
    const html = renderToStaticMarkup(createElement(SessionDetail, { view: viewWithCompletedExercises(base.exercises.length), clientName: "Client" }));
    expect(html).toContain("Every set hit its reps");
    expect(html).not.toContain("Not reached");
  });
});
