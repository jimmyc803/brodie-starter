import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createMaxWaitDebounce } from "@/lib/throttle";
import { etDate, pickPowerHour } from "@/lib/format";
import { ilikePattern } from "@/lib/mappers";

describe("createMaxWaitDebounce", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("coalesces bursts into one trailing call after 500ms", () => {
    const fn = vi.fn();
    const d = createMaxWaitDebounce(fn, 500, 1000);
    d.trigger();
    vi.advanceTimersByTime(300);
    d.trigger();
    vi.advanceTimersByTime(499);
    expect(fn).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("never delays more than maxWait under a continuous stream", () => {
    const fn = vi.fn();
    const d = createMaxWaitDebounce(fn, 500, 1000);
    for (let i = 0; i < 20; i++) {
      d.trigger();
      vi.advanceTimersByTime(200);
    }
    expect(fn.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it("cancel drops the pending call", () => {
    const fn = vi.fn();
    const d = createMaxWaitDebounce(fn);
    d.trigger();
    d.cancel();
    vi.advanceTimersByTime(5000);
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("pickPowerHour", () => {
  const mk = (dateEt: string, h: number) => ({
    dateEt,
    startsAt: `${dateEt}T${String(h).padStart(2, "0")}:00:00-04:00`,
    endsAt: `${dateEt}T${String(h + 1).padStart(2, "0")}:00:00-04:00`,
  });
  const rows = [mk("2026-10-12", 13), mk("2026-10-13", 15)];

  it("computes the ET date", () => {
    expect(etDate(Date.parse("2026-10-13T01:00:00Z"))).toBe("2026-10-12");
  });
  it("prefers today's row even if already past", () => {
    const now = Date.parse("2026-10-12T20:00:00-04:00");
    expect(pickPowerHour(rows, now)?.dateEt).toBe("2026-10-12");
  });
  it("falls back to the nearest upcoming row", () => {
    const now = Date.parse("2026-10-11T12:00:00-04:00");
    expect(pickPowerHour(rows, now)?.dateEt).toBe("2026-10-12");
    expect(pickPowerHour([rows[1]], Date.parse("2026-10-12T09:00:00-04:00"))?.dateEt).toBe("2026-10-13");
  });
  it("returns null when nothing today or upcoming", () => {
    expect(pickPowerHour([rows[0]], Date.parse("2026-10-14T12:00:00-04:00"))).toBeNull();
  });
});

describe("ilikePattern", () => {
  it("escapes wildcards", () => {
    expect(ilikePattern(" a_b%c ")).toBe("%a\\_b\\%c%");
  });
});
