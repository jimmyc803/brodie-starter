import { describe, expect, it } from "vitest";
import { EMPTY_TRACKER, expireDeltas, latestDeltaVersion, trackRanks } from "@/lib/rank-tracker";

const snap = (...ids: string[]) => ids.map((publicId, i) => ({ publicId, rank: i + 1 }));

describe("trackRanks", () => {
  it("records the first snapshot without arrows", () => {
    const s = trackRanks(EMPTY_TRACKER, snap("a", "b", "c", "d"));
    expect(s.deltas).toEqual({});
    expect(s.ranks).toEqual({ a: 1, b: 2, c: 3, d: 4 });
  });

  it("keeps the arrow by publicId when an athlete crosses from the list (4) onto the podium (3)", () => {
    let s = trackRanks(EMPTY_TRACKER, snap("a", "b", "c", "d"));
    s = trackRanks(s, snap("a", "b", "d", "c"));
    expect(s.deltas.d?.delta).toBe(1);
    expect(s.deltas.c?.delta).toBe(-1);
    // A later refresh with no movement (new array identity, same ranks) must not drop the arrows.
    s = trackRanks(s, snap("a", "b", "d", "c"));
    expect(s.deltas.d?.delta).toBe(1);
    expect(s.deltas.c?.delta).toBe(-1);
  });

  it("replaces an older arrow when the athlete moves again", () => {
    let s = trackRanks(EMPTY_TRACKER, snap("a", "b", "c", "d"));
    s = trackRanks(s, snap("a", "b", "d", "c"));
    s = trackRanks(s, snap("d", "a", "b", "c"));
    expect(s.deltas.d?.delta).toBe(2);
    expect(s.deltas.d?.version).toBe(s.version);
  });

  it("drops athletes who leave the snapshot", () => {
    let s = trackRanks(EMPTY_TRACKER, snap("a", "b", "c"));
    s = trackRanks(s, snap("b", "a"));
    expect(s.ranks).toEqual({ b: 1, a: 2 });
    expect(Object.keys(s.deltas).sort()).toEqual(["a", "b"]);
  });
});

describe("expireDeltas", () => {
  it("removes arrows at or before the version and keeps newer ones", () => {
    let s = trackRanks(EMPTY_TRACKER, snap("a", "b", "c", "d"));
    s = trackRanks(s, snap("b", "a", "c", "d"));
    const v1 = s.version;
    s = trackRanks(s, snap("b", "a", "d", "c"));
    expect(latestDeltaVersion(s)).toBe(s.version);
    s = expireDeltas(s, v1);
    expect(Object.keys(s.deltas).sort()).toEqual(["c", "d"]);
    s = expireDeltas(s, s.version);
    expect(s.deltas).toEqual({});
    expect(latestDeltaVersion(s)).toBeNull();
  });
  it("returns the same object when nothing expires", () => {
    const s = trackRanks(EMPTY_TRACKER, snap("a"));
    expect(expireDeltas(s, 99)).toBe(s);
  });
});
