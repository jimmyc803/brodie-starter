import { describe, expect, it } from "vitest";
import { competitionPhase } from "@/lib/format";

const comp = {
  frozen: false,
  windowStart: "2026-10-12T04:00:00.000Z",
  windowEnd: "2026-10-19T03:59:59.000Z",
};
const at = (iso: string) => Date.parse(iso);

describe("competitionPhase", () => {
  it("is final once the window has ended even if the freeze flag has not been set", () => {
    expect(competitionPhase(comp, at("2026-10-19T03:59:59.000Z"))).toBe("final");
    expect(competitionPhase(comp, at("2026-10-20T00:00:00.000Z"))).toBe("final");
  });
  it("is final whenever frozen, regardless of time", () => {
    expect(competitionPhase({ ...comp, frozen: true }, at("2026-10-14T12:00:00.000Z"))).toBe("final");
  });
  it("is live inside the window and pre before it opens", () => {
    expect(competitionPhase(comp, at("2026-10-14T12:00:00.000Z"))).toBe("live");
    expect(competitionPhase(comp, at("2026-10-19T03:59:58.999Z"))).toBe("live");
    expect(competitionPhase(comp, at("2026-10-11T12:00:00.000Z"))).toBe("pre");
  });
  it("tolerates missing or unparseable data", () => {
    expect(competitionPhase(null, 0)).toBe("live");
    expect(competitionPhase({ frozen: false, windowStart: "nope", windowEnd: "nope" }, 0)).toBe("live");
    expect(competitionPhase({ frozen: false, windowStart: null, windowEnd: null }, 0)).toBe("live");
  });
});
