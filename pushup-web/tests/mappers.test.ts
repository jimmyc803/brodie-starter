import { describe, expect, it } from "vitest";
import { filterByName, mapCompetition, mapLeaderboardRow, mapLineStatus, mapPowerHour, prizePool, ufcFighterCopy } from "@/lib/mappers";

describe("mappers", () => {
  it("maps leaderboard rows and never carries handles", () => {
    const r = mapLeaderboardRow({
      rank: 1,
      public_id: "abc",
      display_name: "Ana",
      points: "42",
      valid_reps: 30,
      streak: 2,
      avatar_level: 99,
      badges: ["streak", 5],
      reached_at: "2026-10-12T00:00:00Z",
      handle: "+15551234567",
    });
    expect(r).toEqual({
      rank: 1,
      publicId: "abc",
      displayName: "Ana",
      points: 42,
      validReps: 30,
      streak: 2,
      avatarLevel: 10,
      badges: ["streak"],
      reachedAt: "2026-10-12T00:00:00Z",
    });
    expect(JSON.stringify(r)).not.toContain("1555");
  });
  it("defaults bad data", () => {
    const r = mapLeaderboardRow({});
    expect(r.avatarLevel).toBe(1);
    expect(r.points).toBe(0);
  });
  it("maps line status with unknown state to closed", () => {
    expect(mapLineStatus({ state_summary: "weird", queue_length: 2, lines_active: 1, eta_cycle_s: 200 }).stateSummary).toBe(
      "closed",
    );
    expect(mapLineStatus({ state_summary: "idle", eta_cycle_s: null }).etaCycleS).toBeNull();
  });
  it("maps power hour and competition", () => {
    expect(mapPowerHour({ date_et: "d", starts_at: "s", ends_at: "e" })).toEqual({ dateEt: "d", startsAt: "s", endsAt: "e" });
    const c = mapCompetition({ window_end: "x", frozen: true, brodie_number: "+1" });
    expect(c).not.toHaveProperty("rafflePrize");
    expect(c.frozen).toBe(true);
    expect(c.ufcFighter).toBeNull();
    expect(c.firstPrize).toBe("$100");
    expect(c.drawingPrize).toBe("$100");
  });
  it("maps the drawing prize alongside the top-scorer prize", () => {
    expect(mapCompetition({ first_prize: "$500", drawing_prize: "$500" })).toMatchObject({
      firstPrize: "$500",
      drawingPrize: "$500",
    });
  });
  it("totals the two cash prizes for the headline, and never invents a total", () => {
    expect(prizePool("$500", "$500")).toBe("$1,000");
    expect(prizePool("$1,000", "$250")).toBe("$1,250");
    // Free-text config: anything unparseable falls back to the top-scorer prize rather than a wrong sum.
    expect(prizePool("$500", "a group call")).toBe("$500");
    expect(prizePool(null, null)).toBe("$500");
  });
  it("falls back to generic UFC copy until a fighter is set", () => {
    expect(ufcFighterCopy(null)).toBe("a UFC fighter");
    expect(ufcFighterCopy("  ")).toBe("a UFC fighter");
    expect(ufcFighterCopy("Max Holloway")).toBe("Max Holloway");
    expect(mapCompetition({ ufc_fighter: "Max Holloway", first_prize: "$250" })).toMatchObject({
      ufcFighter: "Max Holloway",
      firstPrize: "$250",
    });
  });
  it("filters by name case-insensitively", () => {
    const rows = [{ displayName: "Ana" }, { displayName: "Bob" }];
    expect(filterByName(rows, " an ")).toEqual([{ displayName: "Ana" }]);
    expect(filterByName(rows, "")).toHaveLength(2);
  });
});
