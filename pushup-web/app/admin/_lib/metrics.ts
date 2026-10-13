/**
 * Pure shaping for /admin/metrics (no network, no env): turns the sparse ch_admin_metrics payload into filled, labelled
 * series and derived ratios. Day buckets are ET calendar days ("YYYY-MM-DD"); hour buckets are hour starts (ISO).
 */

export type RawMetrics = {
  generated_at: string;
  include_team: boolean;
  days: number;
  today: string;
  kpis: {
    joined: number;
    joined_today: number;
    called_users: number;
    scored_users: number;
    calls_connected: number;
    calls_accepted: number;
    calls_counted: number;
    valid_reps: number;
    dau_today: number;
    opted_out: number;
    banned: number;
    team_accounts: number;
    pending_joins: number;
  };
  signups_before: number;
  signups_daily: { day: string; n: number }[];
  signups_hourly: { hour: string; n: number }[];
  calls_daily: { day: string; connected: number; accepted: number; valid_reps: number }[];
  calls_hourly: { hour: string; n: number }[];
  visits_daily: { day: string; landings: number; join_taps: number }[];
  funnel: { visits: number; join_taps: number; join_started: number; joined: number; called: number; scored: number };
  virality: {
    referred: number;
    active_referrers: number;
    sources: { source: string; n: number }[];
    visit_sources: { source: string; n: number }[];
    top_referrers: { user_id: string; display_name: string | null; referred: number; referred_called: number }[];
    max_depth: number;
    second_gen: number;
  };
};

export type Point = { key: string; label: string; value: number };
export type DualPoint = Point & { value2: number };
export type ShareRow = { label: string; value: number; share: number };
export type FunnelStep = { label: string; value: number; ofFirst: number | null; ofPrev: number | null };

export type MetricsView = {
  includeTeam: boolean;
  teamAccounts: number;
  generatedAt: string;
  kpis: {
    joined: number;
    joinedToday: number;
    calledUsers: number;
    scoredUsers: number;
    callsConnected: number;
    callsAccepted: number;
    callsCounted: number;
    validReps: number;
    joinToCall: number | null;
    dauToday: number;
    optedOut: number;
    banned: number;
    pendingJoins: number;
  };
  signupsDaily: Point[];
  signupsCumulative: Point[];
  signupsHourly: Point[];
  callsDaily: DualPoint[]; // value = connected, value2 = accepted
  callsHourly: Point[];
  repsDaily: Point[];
  visitsDaily: DualPoint[]; // value = landings, value2 = join taps
  funnel: FunnelStep[];
  virality: {
    referred: number;
    referredShare: number | null;
    kFactor: number | null;
    activeReferrers: number;
    maxDepth: number;
    secondGen: number;
    sources: ShareRow[];
    visitSources: ShareRow[];
    topReferrers: { userId: string; name: string; referred: number; referredCalled: number }[];
  };
};

const MIN_DAYS = 7;
const HOURS = 48;

const num = (v: unknown): number => (typeof v === "number" && Number.isFinite(v) ? v : Number(v) || 0);

/** a / b, or null when b is 0 (shown as "-" rather than a misleading 0%). */
export function ratio(a: number, b: number): number | null {
  return b > 0 ? a / b : null;
}

export function formatPct(r: number | null, digits = 0): string {
  return r == null ? "-" : `${(r * 100).toFixed(digits)}%`;
}

/** "YYYY-MM-DD" + n days (calendar arithmetic, no time zone involved). */
export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Inclusive list of calendar days from `from` to `to` (empty when from > to). */
export function dayRange(from: string, to: string): string[] {
  const out: string[] = [];
  for (let d = from; d <= to && out.length < 400; d = addDays(d, 1)) out.push(d);
  return out;
}

const dayFmt = new Intl.DateTimeFormat("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
const hourFmt = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", hour: "numeric" });
const hourDayFmt = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  weekday: "short",
  hour: "numeric",
});

export function dayLabel(day: string): string {
  return dayFmt.format(new Date(`${day}T00:00:00Z`));
}

/** ET hour label, e.g. "3 PM"; midnight gets the weekday so day changes are visible ("Wed 12 AM"). */
export function hourLabel(ms: number): string {
  const h = hourFmt.format(new Date(ms));
  return h.startsWith("12 AM") ? hourDayFmt.format(new Date(ms)) : h;
}

/**
 * The visible day window: from the first day with any data (but at least MIN_DAYS back, and never more than the RPC's
 * window) through today.
 */
export function windowDays(raw: Pick<RawMetrics, "today" | "days" | "signups_daily" | "calls_daily" | "visits_daily">): string[] {
  const earliestAllowed = addDays(raw.today, -(Math.max(1, num(raw.days)) - 1));
  const minFloor = addDays(raw.today, -(MIN_DAYS - 1));
  const seen = [...raw.signups_daily, ...raw.calls_daily, ...raw.visits_daily]
    .map((r) => r.day)
    .filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d))
    .sort();
  let from = seen.length && seen[0] < minFloor ? seen[0] : minFloor;
  if (from < earliestAllowed) from = earliestAllowed;
  return dayRange(from, raw.today);
}

/** Hour starts (ms) for the last HOURS hours, oldest first, ending with the hour containing nowMs. */
export function hourRange(nowMs: number, hours = HOURS): number[] {
  const end = Math.floor(nowMs / 3_600_000) * 3_600_000;
  return Array.from({ length: hours }, (_, i) => end - (hours - 1 - i) * 3_600_000);
}

function byDay<T extends { day: string }>(rows: T[]): Map<string, T> {
  return new Map(rows.map((r) => [r.day, r]));
}

function byHour(rows: { hour: string; n: number }[]): Map<number, number> {
  const m = new Map<number, number>();
  for (const r of rows) {
    const t = Date.parse(r.hour);
    if (!Number.isNaN(t)) m.set(t, (m.get(t) ?? 0) + num(r.n));
  }
  return m;
}

/** Running total starting from `base` (signups before the window). */
export function cumulative(points: Point[], base: number): Point[] {
  let total = base;
  return points.map((p) => ({ ...p, value: (total += p.value) }));
}

export function shares(rows: { source: string; n: number }[], labels: Record<string, string> = {}): ShareRow[] {
  const total = rows.reduce((s, r) => s + num(r.n), 0);
  return rows
    .map((r) => ({ label: labels[r.source] ?? r.source, value: num(r.n), share: total > 0 ? num(r.n) / total : 0 }))
    .sort((a, b) => b.value - a.value || a.label.localeCompare(b.label));
}

export function funnelSteps(steps: [string, number][]): FunnelStep[] {
  const first = steps[0]?.[1] ?? 0;
  return steps.map(([label, value], i) => ({
    label,
    value,
    ofFirst: i === 0 ? null : ratio(value, first),
    ofPrev: i === 0 ? null : ratio(value, steps[i - 1][1]),
  }));
}

const SOURCE_LABELS: Record<string, string> = {
  direct: "Direct / untagged",
  referral: "Friend invite",
  web: "Web sign-up",
};

export function shapeMetrics(raw: RawMetrics, nowMs: number): MetricsView {
  const k = raw.kpis;
  const days = windowDays(raw);
  const su = byDay(raw.signups_daily);
  const ca = byDay(raw.calls_daily);
  const vi = byDay(raw.visits_daily);
  const signupsDaily = days.map((d) => ({ key: d, label: dayLabel(d), value: num(su.get(d)?.n) }));
  // Signups that happened inside the RPC window but before the visible window still belong in the running total.
  const hidden = raw.signups_daily.filter((r) => r.day < days[0]).reduce((s, r) => s + num(r.n), 0);
  const hours = hourRange(nowMs);
  const sh = byHour(raw.signups_hourly);
  const ch = byHour(raw.calls_hourly);
  const f = raw.funnel;
  const v = raw.virality;
  const joined = num(k.joined);

  return {
    includeTeam: Boolean(raw.include_team),
    teamAccounts: num(k.team_accounts),
    generatedAt: raw.generated_at,
    kpis: {
      joined,
      joinedToday: num(k.joined_today),
      calledUsers: num(k.called_users),
      scoredUsers: num(k.scored_users),
      callsConnected: num(k.calls_connected),
      callsAccepted: num(k.calls_accepted),
      callsCounted: num(k.calls_counted),
      validReps: num(k.valid_reps),
      joinToCall: ratio(num(k.called_users), joined),
      dauToday: num(k.dau_today),
      optedOut: num(k.opted_out),
      banned: num(k.banned),
      pendingJoins: num(k.pending_joins),
    },
    signupsDaily,
    signupsCumulative: cumulative(signupsDaily, num(raw.signups_before) + hidden),
    signupsHourly: hours.map((t) => ({ key: String(t), label: hourLabel(t), value: sh.get(t) ?? 0 })),
    callsDaily: days.map((d) => ({
      key: d,
      label: dayLabel(d),
      value: num(ca.get(d)?.connected),
      value2: num(ca.get(d)?.accepted),
    })),
    callsHourly: hours.map((t) => ({ key: String(t), label: hourLabel(t), value: ch.get(t) ?? 0 })),
    repsDaily: days.map((d) => ({ key: d, label: dayLabel(d), value: num(ca.get(d)?.valid_reps) })),
    visitsDaily: days.map((d) => ({
      key: d,
      label: dayLabel(d),
      value: num(vi.get(d)?.landings),
      value2: num(vi.get(d)?.join_taps),
    })),
    funnel: funnelSteps([
      ["Site visits", num(f.visits)],
      ["Tapped Text JOIN", num(f.join_taps)],
      ["Texted JOIN", num(f.join_started)],
      ["Joined (YES)", num(f.joined)],
      ["Called the line", num(f.called)],
      ["Scored a rep", num(f.scored)],
    ]),
    virality: {
      referred: num(v.referred),
      referredShare: ratio(num(v.referred), joined),
      // Referred signups per participant: above 1 means every player brings in more than one new player.
      kFactor: ratio(num(v.referred), joined),
      activeReferrers: num(v.active_referrers),
      maxDepth: num(v.max_depth),
      secondGen: num(v.second_gen),
      sources: shares(v.sources ?? [], SOURCE_LABELS),
      visitSources: shares(v.visit_sources ?? [], { ...SOURCE_LABELS, direct: "Direct / unknown" }),
      topReferrers: (v.top_referrers ?? []).map((r) => ({
        userId: r.user_id,
        name: r.display_name ?? "(no name)",
        referred: num(r.referred),
        referredCalled: num(r.referred_called),
      })),
    },
  };
}

// ------------------------------------------------------------------ retention (ch_admin_retention)

type RawDay = { eligible: boolean; complete: boolean; called: number; active: number };

export type RawRetention = {
  generated_at: string;
  include_team: boolean;
  today: string;
  cohorts: { day: string; n: number; returned: number; d1: RawDay; d3: RawDay; d7: RawDay }[];
  callers_daily: { day: string; first_time: number; returning: number }[];
  calls_per_user: { calls: number; users: number }[];
  streaks: { streak: number; users: number }[];
  qualified_days: { days: number; users: number }[];
  engaged_not_calling: { n: number; users: { user_id: string; display_name: string | null; last_text_at: string }[] };
};

/** A count out of a base, always shown with its n so tiny cohorts can't masquerade as big percentages. */
export type Frac = { num: number; den: number; pct: number | null };
export type RetentionCell =
  | { state: "na" } // join day + k is still in the future
  | { state: "partial" | "done"; called: Frac; active: Frac }; // partial: that ET day is today (still running)

export type CohortRow = {
  key: string;
  label: string;
  n: number;
  returned: Frac;
  d1: RetentionCell;
  d3: RetentionCell;
  d7: RetentionCell;
};

export type RetentionView = {
  cohorts: CohortRow[];
  /** Cohorts whose day k is complete, pooled (sum of returners / sum of those cohorts' sizes). */
  pooled: { d1: Frac; d3: Frac; d7: Frac; returned: Frac };
  callersDaily: DualPoint[]; // value = all callers that day, value2 = returning callers (first-time stacked on top)
  callsPerUser: ShareRow[];
  streaks: ShareRow[];
  qualifiedDays: ShareRow[];
  engaged: { n: number; users: { userId: string; name: string; lastTextAt: string }[] };
};

/** Below this many people a percentage is still shown, but flagged as anecdotal. */
export const SMALL_N = 5;

export function frac(numerator: number, den: number): Frac {
  return { num: numerator, den, pct: ratio(numerator, den) };
}

/** "50% (1/2)", or "-" when there is nobody to measure. */
export function formatFrac(f: Frac): string {
  return f.den > 0 ? `${formatPct(f.pct)} (${Math.round(f.num)}/${Math.round(f.den)})` : "-";
}

function cell(raw: RawDay | undefined, size: number): RetentionCell {
  if (!raw || !raw.eligible) return { state: "na" };
  return {
    state: raw.complete ? "done" : "partial",
    called: frac(num(raw.called), size),
    active: frac(num(raw.active), size),
  };
}

/** Bucket a {value -> users} histogram into labelled ranges; [label, lo, hi] inclusive, hi null = open-ended. */
export function bucketize(rows: { value: number; users: number }[], buckets: [string, number, number | null][]): ShareRow[] {
  const total = rows.reduce((s, r) => s + num(r.users), 0);
  return buckets.map(([label, lo, hi]) => {
    const value = rows
      .filter((r) => num(r.value) >= lo && (hi == null || num(r.value) <= hi))
      .reduce((s, r) => s + num(r.users), 0);
    return { label, value, share: total > 0 ? value / total : 0 };
  });
}

const CALL_BUCKETS: [string, number, number | null][] = [
  ["0 calls", 0, 0],
  ["1 call", 1, 1],
  ["2 calls", 2, 2],
  ["3-5 calls", 3, 5],
  ["6-10 calls", 6, 10],
  ["11+ calls", 11, null],
];
const DAY_BUCKETS: [string, number, number | null][] = [
  ["0 days", 0, 0],
  ["1 day", 1, 1],
  ...[2, 3, 4, 5, 6].map((d): [string, number, number] => [`${d} days`, d, d]),
  ["7+ days", 7, null],
];

export function shapeRetention(raw: RawRetention): RetentionView {
  const rawCohorts = raw.cohorts ?? [];
  const cohorts: CohortRow[] = rawCohorts.map((c) => {
    const size = num(c.n);
    return {
      key: c.day,
      label: dayLabel(c.day),
      n: size,
      returned: frac(num(c.returned), size),
      d1: cell(c.d1, size),
      d3: cell(c.d3, size),
      d7: cell(c.d7, size),
    };
  });
  const pool = (k: "d1" | "d3" | "d7"): Frac => {
    const done = rawCohorts.filter((c) => c[k]?.eligible && c[k]?.complete);
    return frac(
      done.reduce((s, c) => s + num(c[k].called), 0),
      done.reduce((s, c) => s + num(c.n), 0),
    );
  };
  const callers = raw.callers_daily ?? [];
  const first = [...rawCohorts.map((c) => c.day), ...callers.map((c) => c.day)].sort()[0];
  const minFrom = addDays(raw.today, -(MIN_DAYS - 1));
  const days = dayRange(first && first < minFrom ? first : minFrom, raw.today);
  const byDayCallers = new Map(callers.map((r) => [r.day, r]));
  return {
    cohorts,
    pooled: {
      d1: pool("d1"),
      d3: pool("d3"),
      d7: pool("d7"),
      returned: frac(
        cohorts.reduce((s, c) => s + c.returned.num, 0),
        cohorts.reduce((s, c) => s + c.n, 0),
      ),
    },
    callersDaily: days.map((d) => {
      const r = byDayCallers.get(d);
      const returning = num(r?.returning);
      return { key: d, label: dayLabel(d), value: num(r?.first_time) + returning, value2: returning };
    }),
    callsPerUser: bucketize((raw.calls_per_user ?? []).map((r) => ({ value: r.calls, users: r.users })), CALL_BUCKETS),
    streaks: bucketize((raw.streaks ?? []).map((r) => ({ value: r.streak, users: r.users })), DAY_BUCKETS),
    qualifiedDays: bucketize((raw.qualified_days ?? []).map((r) => ({ value: r.days, users: r.users })), DAY_BUCKETS),
    engaged: {
      n: num(raw.engaged_not_calling?.n),
      users: (raw.engaged_not_calling?.users ?? []).map((u) => ({
        userId: u.user_id,
        name: u.display_name ?? "(no name)",
        lastTextAt: u.last_text_at,
      })),
    },
  };
}
