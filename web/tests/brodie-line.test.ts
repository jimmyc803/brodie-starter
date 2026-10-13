import { describe, expect, it } from "vitest";
import { brodieLine } from "@/lib/brodie-line";
import type { SessionView, SetView } from "@/lib/contract";

const set = (n: number, completed: number, planned: number, faults: string[][] = []): SetView => ({
  set_number: n, planned_reps: planned, completed_reps: completed,
  reps: Array.from({ length: completed }, (_, i) => ({ rep_number: i + 1, faults: faults[i] ?? [] })),
});
const view = (...exercises: { key: string; name: string; sets: SetView[] }[]) =>
  ({ exercises: exercises.map((e) => ({ exercise_key: e.key, name: e.name, sets: e.sets })) }) as unknown as SessionView;

describe("brodieLine", () => {
  it("nudges when no reps were counted", () =>
    expect(brodieLine(view({ key: "squat", name: "Squats", sets: [set(1, 0, 10)] }))).toMatch(/No reps counted/));
  it("praises a complete, clean session", () =>
    expect(brodieLine(view({ key: "squat", name: "Squats", sets: [set(1, 10, 10)] }))).toBe("Every set done, clean form. That's how it's done."));
  it("asks to finish when clean but short", () =>
    expect(brodieLine(view({ key: "squat", name: "Squats", sets: [set(1, 6, 10)] }))).toBe("Clean form. Finish every set next time."));
  it("names the most common cue and its exercise", () => {
    const line = brodieLine(view(
      { key: "pushup", name: "Push-ups", sets: [set(1, 8, 8, [["pushup - hips sagging"]])] },
      { key: "squat", name: "Squats", sets: [set(1, 10, 10, [["squats - shallow"], ["squats - shallow"]])] },
    ));
    expect(line).toMatch(/^Every set done\. Next time on squats: /);
    expect(line.endsWith(".")).toBe(true);
  });
  it("ignores exercises whose form Brodie doesn't check", () =>
    expect(brodieLine(view({ key: "bicep_curl", name: "Bicep curls", sets: [set(1, 12, 12, [["curl - swinging"]])] }))).toBe(
      "Every set done, clean form. That's how it's done.",
    ));
});
