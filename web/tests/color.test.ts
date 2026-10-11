import { describe, expect, it } from "vitest";

import { mixOklch, ramp } from "@/lib/color";
import { scoreColor, SCORE_STOPS } from "@/lib/body/variants";
import { COLORS } from "@/lib/contract";

const hue = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return { r, g, b };
};

describe("color mixing", () => {
  it("returns the ends at t = 0 and 1", () => {
    expect(mixOklch("#ef4444", "#22c55e", 0)).toBe("#ef4444");
    expect(mixOklch("#ef4444", "#22c55e", 1)).toBe("#22c55e");
  });
  it("fading green toward gray stays green, never blue", () => {
    const { r, g, b } = hue(mixOklch(COLORS.green, "#52525b", 0.45));
    expect(g).toBeGreaterThan(b);
    expect(g).toBeGreaterThan(r);
  });
  it("pins the team colors at the contract thresholds", () => {
    expect(scoreColor(0.5)).toBe(COLORS.yellow);
    expect(scoreColor(0.75)).toBe(COLORS.green);
    expect(ramp(SCORE_STOPS, -1)).toBe(SCORE_STOPS[0][1]);
  });
});
