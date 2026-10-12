import { describe, expect, it } from "vitest";
import { formChecked, muscleBalance, setQuality, setSummary } from "@/lib/quality";
import type { SessionView, SetView } from "@/lib/contract";

const set = (completed: number, planned: number, flagged: string[][] = []): SetView => ({
  set_number: 3, planned_reps: planned, completed_reps: completed,
  reps: Array.from({ length: completed }, (_, i) => ({ rep_number: i + 1, faults: flagged[i] ?? [] })),
});

describe("formChecked", () => {
  it("is true for exercises Brodie has form cues for", () => {
    expect(formChecked("squat")).toBe(true);
    expect(formChecked("pushup")).toBe(true);
  });
  it("is false for bicep curls, pull-ups and unknown keys", () => {
    expect(formChecked("bicep_curl")).toBe(false);
    expect(formChecked("pullup")).toBe(false);
    expect(formChecked("bench_press")).toBe(false);
  });
});

describe("setQuality", () => {
  it("good: all planned reps, clean", () => expect(setQuality(set(10, 10), "squat")).toBe("good"));
  it("warn: short of planned", () => expect(setQuality(set(9, 10), "squat")).toBe("warn"));
  it("warn: some flagged (clean 70%)", () =>
    expect(setQuality(set(10, 10, [["squats - shallow"], ["squats - shallow"], ["squats - shallow"]]), "squat")).toBe("warn"));
  it("bad: under half clean", () =>
    expect(setQuality(set(4, 4, [["a"], ["a"], ["a"]]), "squat")).toBe("bad"));
  it("skipped: set not reached", () => expect(setQuality(set(0, 10), "squat")).toBe("skipped"));
  it("none: form not checked, even when every rep is done", () => expect(setQuality(set(12, 12), "bicep_curl")).toBe("none"));
});

describe("setSummary", () => {
  it("names reps, flags and the top cue", () =>
    expect(setSummary(set(9, 10, [["squats - shallow"], ["squats - shallow"]]), "squat")).toMatch(/^Set 3 · 9 of 10 reps · 2 flagged: /));
  it("says clean when nothing is flagged", () => expect(setSummary(set(10, 10), "squat")).toBe("Set 3 · 10 of 10 reps · clean"));
  it("says form not checked for curls", () => expect(setSummary(set(12, 12), "bicep_curl")).toBe("Set 3 · 12 of 12 reps · form not checked"));
  it("says not reached", () => expect(setSummary(set(0, 10), "squat")).toBe("Set 3 · not reached"));
});

describe("muscleBalance", () => {
  const view = (colors: string[]) =>
    ({ muscles: colors.map((c, i) => ({ muscle: `m${i}`, score: 0, color: c, coverage: "primary" })) }) as unknown as SessionView;
  it("counts colors and writes one caption", () => {
    expect(muscleBalance(view(["green", "green", "yellow", "red", "gray"]))).toEqual({ good: 2, warn: 1, bad: 1, caption: "2 solid · 1 okay · 1 work on" });
  });
  it("drops zero groups from the caption", () => {
    expect(muscleBalance(view(["green"])).caption).toBe("1 solid");
  });
  it("handles a session with no trained muscles", () => {
    expect(muscleBalance(view(["gray"])).caption).toBe("No muscles trained");
  });
});
