import { beforeEach, describe, expect, it } from "vitest";

import { SHAPES } from "@/lib/body/shapes";
import { neonFill, neonFills, UNTRAINED } from "@/lib/body/neon";
import { bodySvg } from "@/lib/body/svg";
import { allMuscles, faultText, MUSCLE_KEYS } from "@/lib/contract";
import { getCoachView } from "@/lib/coach-view";
import { flaggedSets, muscleDetails, sessionStats } from "@/lib/recap";
import { getSessionView, SAMPLE_COACH_TOKEN, SAMPLE_SESSION_TOKEN, sampleSessionView } from "@/lib/session-view";

beforeEach(() => {
  delete process.env.SUPABASE_URL;
  delete process.env.SUPABASE_SERVICE_ROLE_KEY;
});

describe("session view without Supabase", () => {
  it("serves the sample session for its token and for 'demo'", async () => {
    expect((await getSessionView(SAMPLE_SESSION_TOKEN))?.client.name).toBe("Ryan");
    expect((await getSessionView("demo"))?.coach.name).toBe("Tristan");
  });
  it("404s other tokens, including malformed ones", async () => {
    expect(await getSessionView("not-a-real-token")).toBeNull();
    expect(await getSessionView("../etc/passwd")).toBeNull();
    expect(await getSessionView("")).toBeNull();
  });
  it("coach view lists the sample client with one session", async () => {
    const v = await getCoachView(SAMPLE_COACH_TOKEN);
    expect(v?.coach.name).toBe("Tristan");
    expect(v?.clients[0].sessions).toHaveLength(1);
    expect(await getCoachView("nope-nope")).toBeNull();
  });
});

describe("contract helpers", () => {
  it("turns fault labels into Brodie's spoken cue", () => {
    expect(faultText("squats - knees over toes")).toBe("Hips back");
    expect(faultText("alternating forward lunges - leaning forward")).toBe("Keep chest up");
    expect(faultText("bicep curls - swinging")).toBe("Swinging"); // no cue yet: label text
  });
  it("covers every muscle, untrained ones gray", () => {
    const view = sampleSessionView();
    view.muscles = view.muscles.filter((m) => m.muscle !== "lats");
    const all = allMuscles(view);
    expect(all.map((m) => m.muscle)).toEqual(MUSCLE_KEYS);
    expect(all.find((m) => m.muscle === "lats")).toMatchObject({ color: "gray", coverage: "none" });
  });
  it("every muscle has a body shape", () => {
    const drawn = new Set([...SHAPES.front, ...SHAPES.back].map((s) => s.muscle));
    for (const m of MUSCLE_KEYS) expect(drawn.has(m)).toBe(true);
  });
});

describe("recap numbers on the sample session", () => {
  const view = sampleSessionView();
  it("labels gray muscles honestly and lists what worked the rest", () => {
    const d = muscleDetails(view);
    expect(d.find((m) => m.muscle === "lats")?.note).toBe("not trained this session");
    const biceps = d.find((m) => m.muscle === "biceps")!;
    expect(biceps.color).toBe("red");
    expect(biceps.exercises[0]).toMatchObject({ name: "Bicep curls", role: "primary", completed: 22, planned: 36 });
  });
  it("counts reps and sets, and notices the call ended early", () => {
    const s = sessionStats(view);
    expect(s.planned).toBe(30 + 24 + 20 + 36);
    expect(s.completed).toBe(29 + 22 + 17 + 22);
    expect(s.setsPlanned).toBe(11);
    expect(s.setsDone).toBe(10);
    expect(s.endedEarly).toBe(true);
  });
  it("flags weak sets but not the set that never happened", () => {
    const f = flaggedSets(view);
    expect(f.some((x) => x.exercise === "Bicep curls" && x.set_number === 3)).toBe(false);
    expect(f.some((x) => x.exercise === "Bicep curls" && x.set_number === 2)).toBe(true);
  });
});

describe("body svg (neon)", () => {
  it("draws the score color, a glow for trained muscles, and untrained muscles flat", () => {
    const fills = neonFills([
      { muscle: "chest", score: 0.9, color: "green", coverage: "primary" },
      { muscle: "lats", score: 0, color: "gray", coverage: "none" },
    ]);
    const svg = bodySvg("front", fills);
    expect(svg.startsWith("<svg")).toBe(true);
    expect(svg).not.toContain("radialGradient");
    expect(svg).toContain(`fill="${fills.chest!.fill}"`);
    expect(svg).toContain("feGaussianBlur");
    expect(fills.lats).toEqual({ fill: UNTRAINED, glow: 0 });
    expect(bodySvg("front", fills, { glow: false })).not.toContain("feGaussianBlur");
  });
  it("keeps secondary and primary rank colors equal while using less halo for helpers", () => {
    const p = neonFill({ muscle: "quads", score: 0.8, color: "green", coverage: "primary" });
    const s = neonFill({ muscle: "quads", score: 0.8, color: "green", coverage: "secondary" });
    expect(s.fill).toBe(p.fill);
    expect(s.glow).toBeLessThan(p.glow);
  });
});

describe("public demo coach link", () => {
  it("the sample coach token is view-only for program upload and assign", async () => {
    const { readOnlyCoachToken } = await import("@/lib/programWorkflow");
    expect(readOnlyCoachToken(SAMPLE_COACH_TOKEN)).toBe(true);
    expect(readOnlyCoachToken("some-private-coach-token-1234")).toBe(false);
  });
});
