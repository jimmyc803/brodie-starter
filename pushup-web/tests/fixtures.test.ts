import { describe, expect, it } from "vitest";
import { findPii } from "../scripts/pii-lib.mjs";
import { fixtureCompetition, fixtureLeaderboard, fixtureLineStatus, fixturePowerHour } from "@/lib/fixtures";
import { powerHourStatus } from "@/lib/format";

describe("fixtures", () => {
  it("has 60 ranked users with non-increasing points", () => {
    const rows = fixtureLeaderboard();
    expect(rows).toHaveLength(60);
    rows.forEach((r, i) => {
      expect(r.rank).toBe(i + 1);
      if (i > 0) expect(r.points).toBeLessThanOrEqual(rows[i - 1].points);
      expect(r.avatarLevel).toBeGreaterThanOrEqual(1);
      expect(r.avatarLevel).toBeLessThanOrEqual(10);
    });
    expect(new Set(rows.map((r) => r.publicId)).size).toBe(60);
  });
  it("line is in a call with 4 queued and power hour is live", () => {
    const now = Date.parse("2026-10-14T18:00:00Z");
    expect(fixtureLineStatus(now)).toMatchObject({ stateSummary: "in_call", queueLength: 4 });
    expect(powerHourStatus(fixturePowerHour(now), now).kind).toBe("live");
  });
  it("carries no PII", () => {
    const blob = JSON.stringify([fixtureLeaderboard(), fixtureCompetition(false)]);
    expect(findPii(blob)).toEqual([]);
  });
  it("frozen toggle", () => {
    expect(fixtureCompetition(true).frozen).toBe(true);
  });
});
