import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { BarChart, Funnel, LineChart, ShareBars } from "../app/admin/_components/charts";
import {
  addDays,
  cumulative,
  dayRange,
  formatPct,
  funnelSteps,
  hourLabel,
  hourRange,
  ratio,
  shapeMetrics,
  shares,
  windowDays,
  type RawMetrics,
} from "../app/admin/_lib/metrics";

const NOW = Date.parse("2026-10-15T16:00:00Z"); // 12:00 ET

function raw(over: Partial<RawMetrics> = {}): RawMetrics {
  return {
    generated_at: "2026-10-15T16:00:00Z",
    include_team: false,
    days: 30,
    today: "2026-10-15",
    kpis: {
      joined: 0,
      joined_today: 0,
      called_users: 0,
      scored_users: 0,
      calls_connected: 0,
      calls_accepted: 0,
      calls_counted: 0,
      valid_reps: 0,
      dau_today: 0,
      opted_out: 0,
      banned: 0,
      team_accounts: 0,
      pending_joins: 0,
    },
    signups_before: 0,
    signups_daily: [],
    signups_hourly: [],
    calls_daily: [],
    calls_hourly: [],
    visits_daily: [],
    funnel: { visits: 0, join_taps: 0, join_started: 0, joined: 0, called: 0, scored: 0 },
    virality: { referred: 0, active_referrers: 0, sources: [], visit_sources: [], top_referrers: [], max_depth: 0, second_gen: 0 },
    ...over,
  };
}

describe("day / hour helpers", () => {
  it("does calendar arithmetic across month ends", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-11-01", -1)).toBe("2026-10-31");
    expect(dayRange("2026-10-30", "2026-11-02")).toEqual(["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]);
    expect(dayRange("2026-10-02", "2026-10-01")).toEqual([]);
  });

  it("shows at least 7 days, extends back to the first data day, never past the RPC window", () => {
    expect(windowDays(raw())).toHaveLength(7);
    expect(windowDays(raw())[0]).toBe("2026-10-09");
    const early = raw({ signups_daily: [{ day: "2026-10-01", n: 1 }] });
    expect(windowDays(early)[0]).toBe("2026-10-01");
    const tooEarly = raw({ days: 10, calls_daily: [{ day: "2026-09-01", connected: 1, accepted: 0, valid_reps: 0 }] });
    expect(windowDays(tooEarly)[0]).toBe("2026-10-06");
    expect(windowDays(tooEarly).at(-1)).toBe("2026-10-15");
  });

  it("builds 48 hourly buckets ending with the current hour and labels them in ET", () => {
    const hours = hourRange(NOW + 25 * 60_000);
    expect(hours).toHaveLength(48);
    expect(hours.at(-1)).toBe(NOW);
    expect(hours[0]).toBe(NOW - 47 * 3_600_000);
    expect(hourLabel(NOW)).toBe("12 PM");
    expect(hourLabel(Date.parse("2026-10-15T04:00:00Z"))).toBe("Thu 12 AM"); // ET midnight shows the weekday
  });

  it("ratios and percentages never divide by zero", () => {
    expect(ratio(1, 0)).toBeNull();
    expect(formatPct(null)).toBe("-");
    expect(formatPct(ratio(1, 3))).toBe("33%");
    expect(formatPct(0.256, 1)).toBe("25.6%");
  });
});

describe("shaping", () => {
  it("fills empty days and hours with zeros", () => {
    const m = shapeMetrics(raw(), NOW);
    expect(m.signupsDaily).toHaveLength(7);
    expect(m.signupsDaily.every((p) => p.value === 0)).toBe(true);
    expect(m.signupsHourly).toHaveLength(48);
    expect(m.kpis.joinToCall).toBeNull();
    expect(m.virality.kFactor).toBeNull();
    expect(m.funnel.map((s) => s.value)).toEqual([0, 0, 0, 0, 0, 0]);
    expect(m.funnel[1].ofPrev).toBeNull();
  });

  it("places sparse rows on the right buckets and accumulates from earlier signups", () => {
    const m = shapeMetrics(
      raw({
        kpis: { ...raw().kpis, joined: 12, called_users: 6, team_accounts: 2 },
        signups_before: 5,
        signups_daily: [
          { day: "2026-10-12", n: 3 },
          { day: "2026-10-15", n: 4 },
        ],
        signups_hourly: [{ hour: "2026-10-15T15:00:00+00:00", n: 2 }],
        calls_daily: [{ day: "2026-10-14", connected: 9, accepted: 7, valid_reps: 120 }],
        calls_hourly: [{ hour: "2026-10-15T16:00:00Z", n: 1 }],
        visits_daily: [{ day: "2026-10-15", landings: 40, join_taps: 11 }],
      }),
      NOW,
    );
    const byKey = Object.fromEntries(m.signupsDaily.map((p) => [p.key, p.value]));
    expect(byKey["2026-10-12"]).toBe(3);
    expect(byKey["2026-10-15"]).toBe(4);
    expect(m.signupsCumulative.at(-1)?.value).toBe(12);
    expect(m.signupsCumulative[0].value).toBe(5);
    expect(m.signupsHourly.at(-2)?.value).toBe(2);
    expect(m.callsHourly.at(-1)?.value).toBe(1);
    const oct14 = m.callsDaily.find((p) => p.key === "2026-10-14");
    expect(oct14).toMatchObject({ value: 9, value2: 7, label: "Oct 14" });
    expect(m.repsDaily.find((p) => p.key === "2026-10-14")?.value).toBe(120);
    expect(m.visitsDaily.at(-1)).toMatchObject({ value: 40, value2: 11 });
    expect(m.kpis.joinToCall).toBe(0.5);
    expect(m.teamAccounts).toBe(2);
  });

  it("derives virality ratios, friendly source labels and display-name-only referrers", () => {
    const m = shapeMetrics(
      raw({
        kpis: { ...raw().kpis, joined: 20 },
        virality: {
          referred: 5,
          active_referrers: 3,
          sources: [
            { source: "direct", n: 12 },
            { source: "referral", n: 5 },
            { source: "tiktok", n: 3 },
          ],
          visit_sources: [{ source: "direct", n: 2 }],
          top_referrers: [{ user_id: "u1", display_name: null, referred: 3, referred_called: 1 }],
          max_depth: 2,
          second_gen: 1,
        },
      }),
      NOW,
    );
    expect(m.virality.referredShare).toBe(0.25);
    expect(m.virality.kFactor).toBe(0.25);
    expect(m.virality.sources.map((s) => s.label)).toEqual(["Direct / untagged", "Friend invite", "tiktok"]);
    expect(m.virality.sources[0].share).toBeCloseTo(0.6);
    expect(m.virality.visitSources[0].label).toBe("Direct / unknown");
    expect(m.virality.topReferrers).toEqual([{ userId: "u1", name: "(no name)", referred: 3, referredCalled: 1 }]);
  });

  it("funnel and share helpers", () => {
    expect(funnelSteps([["a", 100], ["b", 40], ["c", 10]]).map((s) => [s.ofPrev, s.ofFirst])).toEqual([
      [null, null],
      [0.4, 0.4],
      [0.25, 0.1],
    ]);
    expect(shares([])).toEqual([]);
    expect(shares([{ source: "x", n: 0 }])[0].share).toBe(0);
    expect(cumulative([{ key: "a", label: "a", value: 2 }, { key: "b", label: "b", value: 3 }], 1).map((p) => p.value)).toEqual([3, 6]);
  });
});

describe("charts", () => {
  const html = (el: Parameters<typeof renderToStaticMarkup>[0]) => renderToStaticMarkup(el);

  it("render an explicit empty state with zero data", () => {
    const pts = [{ key: "a", label: "Oct 1", value: 0 }];
    expect(html(createElement(BarChart, { data: pts, label: "x" }))).toContain("No data yet");
    expect(html(createElement(LineChart, { data: pts, label: "x" }))).toContain("No data yet");
    expect(html(createElement(BarChart, { data: [], label: "x" }))).toContain("No data yet");
    expect(html(createElement(ShareBars, { rows: [] }))).toContain("No data yet");
  });

  it("render bars with tooltips and never NaN geometry", () => {
    const out = html(
      createElement(BarChart, {
        data: [
          { key: "a", label: "Oct 1", value: 4, value2: 1 },
          { key: "b", label: "Oct 2", value: 0, value2: 0 },
        ],
        label: "calls",
        unit: " connected",
        unit2: " accepted",
      }),
    );
    expect(out).toContain("<title>Oct 1: 4 connected, 1 accepted</title>");
    expect(out).not.toContain("NaN");
    expect(out).not.toContain("No data yet");
    const line = html(createElement(LineChart, { data: [{ key: "a", label: "Oct 1", value: 3 }], label: "x" }));
    expect(line).not.toContain("NaN");
    const funnel = html(
      createElement(Funnel, { steps: funnelSteps([["Visits", 0], ["Joined", 0]]) }),
    );
    expect(funnel).toContain("width:0%");
  });
});
