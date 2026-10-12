import { describe, expect, it } from "vitest";
import {
  formatCountdown,
  formatEta,
  formatEtDeadline,
  formatLineStatus,
  isFinal,
  powerHourStatus,
  smsLink,
} from "@/lib/format";

describe("formatCountdown", () => {
  it("formats h:mm:ss and days, clamps negatives", () => {
    expect(formatCountdown(3_723_000)).toBe("1:02:03");
    expect(formatCountdown(90_000_000)).toBe("1d 1:00:00");
    expect(formatCountdown(-5)).toBe("0:00:00");
  });
});

describe("formatEta", () => {
  it("returns null when unknown or empty", () => {
    expect(formatEta(0, 200)).toBeNull();
    expect(formatEta(3, null)).toBeNull();
  });
  it("gives ranges", () => {
    expect(formatEta(1, 60)).toBe("~1-2 min");
    expect(formatEta(4, 200)).toBe("~10-17 min");
    expect(formatEta(10, 300)).toBe("~50 min");
  });
});

describe("formatLineStatus", () => {
  it("matches the spec example shape", () => {
    const s = formatLineStatus({
      stateSummary: "in_call",
      queueLength: 4,
      linesActive: 1,
      etaCycleS: 300,
      updatedAt: null,
    });
    expect(s).toBe("In a call · 4 in line · ~15-25 min");
  });
  it("handles null and closed", () => {
    expect(formatLineStatus(null)).toMatch(/unavailable/);
    expect(
      formatLineStatus({ stateSummary: "closed", queueLength: 0, linesActive: 0, etaCycleS: null, updatedAt: null }),
    ).toBe("Line closed");
  });
});

describe("powerHourStatus", () => {
  const ph = { dateEt: "2026-10-13", startsAt: "2026-10-13T16:00:00Z", endsAt: "2026-10-13T17:00:00Z" };
  const t = Date.parse(ph.startsAt);
  it("covers all phases", () => {
    expect(powerHourStatus(null, t)).toEqual({ kind: "none" });
    expect(powerHourStatus(ph, t - 1000)).toEqual({ kind: "upcoming", msUntil: 1000 });
    expect(powerHourStatus(ph, t)).toEqual({ kind: "live", msLeft: 3_600_000 });
    expect(powerHourStatus(ph, t + 3_600_000)).toEqual({ kind: "over" });
  });
});

describe("isFinal", () => {
  const end = "2026-10-18T23:59:59-04:00";
  it("is final when frozen or past the end", () => {
    expect(isFinal(true, end, 0)).toBe(true);
    expect(isFinal(false, end, Date.parse(end) - 1)).toBe(false);
    expect(isFinal(false, end, Date.parse(end))).toBe(true);
  });
});

describe("smsLink", () => {
  it("builds the sms link", () => {
    expect(smsLink("+15551234567")).toBe("sms:+15551234567&body=JOIN%20");
    expect(smsLink(null)).toBeNull();
  });
});

describe("formatEtDeadline", () => {
  it("formats the freeze instant in Eastern Time", () => {
    expect(formatEtDeadline("2026-10-19T03:59:59.000Z")).toBe("Sun Oct 18 · 11:59 PM ET");
  });
  it("returns null for missing or bad input", () => {
    expect(formatEtDeadline(null)).toBeNull();
    expect(formatEtDeadline("nope")).toBeNull();
  });
});
