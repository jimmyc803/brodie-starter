import { describe, expect, it } from "vitest";

import { OneEuroFilter, smoothTrack } from "@/lib/rep-review/one-euro";
import { sampleJoints } from "@/lib/rep-review/pose";
import type { PoseTrack } from "@/lib/rep-review/pose-types";

const row = (t: number, x: number, y: number, v = 1) => {
  const r = [t];
  for (let i = 0; i < 33; i++) r.push(x, y, v);
  return r;
};
const track = (frames: number[][]): PoseTrack => ({ v: 1, fps: 30, w: 100, h: 100, duration: 1, frames });
const variance = (xs: number[]) => {
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  return xs.reduce((a, b) => a + (b - m) ** 2, 0) / xs.length;
};

describe("one euro", () => {
  it("keeps a constant input constant", () => {
    const f = new OneEuroFilter();
    for (let i = 0; i < 50; i++) expect(f.filter(0.5, i / 30)).toBeCloseTo(0.5, 10);
  });

  it("reduces variance of noisy input", () => {
    let seed = 1;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647 - 0.5) * 0.1;
    const raw: number[] = [];
    const out: number[] = [];
    const f = new OneEuroFilter();
    for (let i = 0; i < 300; i++) {
      const x = 0.5 + rnd();
      raw.push(x);
      out.push(f.filter(x, i / 30));
    }
    expect(variance(out)).toBeLessThan(variance(raw) * 0.5);
  });

  it("holds the previous value for low-visibility samples", () => {
    const t = track([row(0, 0.2, 0.2), row(0.1, 0.9, 0.9, 0.1)]);
    const s = smoothTrack(t);
    expect(s.frames[1][1]).toBeCloseTo(s.frames[0][1], 10);
  });
});

describe("sampleJoints", () => {
  const t = track([row(0, 0, 0), row(1, 1, 0.5)]);

  it("interpolates linearly", () => {
    const j = sampleJoints(t, 0.5)!;
    expect(j).toHaveLength(99);
    expect(j[0]).toBeCloseTo(0.5);
    expect(j[1]).toBeCloseTo(0.25);
    expect(j[2]).toBeCloseTo(1);
  });

  it("returns null outside the range and for empty tracks", () => {
    expect(sampleJoints(t, 1.3)).toBeNull();
    expect(sampleJoints(t, -0.3)).toBeNull();
    expect(sampleJoints(track([]), 0)).toBeNull();
    expect(sampleJoints(t, 1.2)).not.toBeNull();
  });
});
