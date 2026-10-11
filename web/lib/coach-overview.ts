import type { CoachView } from "@/lib/coach-view";
import type { SessionView } from "@/lib/contract";
import { faultyReps } from "@/lib/contract";
import { sortSummaries, summarizeClient, type ClientSummary } from "@/lib/coach-status";
import { flaggedSets, sessionStats } from "@/lib/recap";

// Numbers for the coach Overview page, all derived from the sessions already loaded for the dashboard. Pure (pass `now`).
// Days are bucketed in the coach's time zone (the hackathon runs on US Eastern).
export const COACH_TZ = "America/New_York";
const DAY_MS = 24 * 60 * 60 * 1000;

export function dayKey(t: number, tz = COACH_TZ): string {
  return new Date(t).toLocaleDateString("en-CA", { timeZone: tz }); // YYYY-MM-DD
}

function cleanReps(v: SessionView) {
  let clean = 0, done = 0;
  for (const ex of v.exercises)
    for (const s of ex.sets) {
      done += s.completed_reps;
      clean += Math.max(0, s.completed_reps - faultyReps(s));
    }
  return { clean, done };
}

export type RecentItem = { clientId: string; clientName: string; token: string; title: string; at: number; detail: string; tone: "review" | "good" | "empty" };
export type DayPoint = { key: string; label: string; clean: number | null; sessions: number };

export type CoachOverview = {
  now: number; // the moment these numbers were computed
  summaries: ClientSummary[];
  activeClients: number; // trained in the last 7 days
  sessionsThisWeek: number;
  cleanThisWeek: number | null; // share of counted reps with no flags, last 7 days
  completionThisWeek: number | null; // reps counted / reps planned, last 7 days
  needReview: number;
  bestForm: { name: string; clean: number } | null;
  days: DayPoint[]; // last 7 days, oldest first
  calendar: Record<string, number>; // YYYY-MM-DD -> sessions with reps
  today: RecentItem[];
  recent: RecentItem[];
};

export function coachOverview(view: CoachView, now = Date.now()): CoachOverview {
  const summaries = sortSummaries(view.clients.map((c) => summarizeClient(c, now)));
  const all = view.clients.flatMap((c) => c.sessions.map((s) => ({ c, s, at: Date.parse(s.session.started_at) })));
  const real = all.filter((x) => Number.isFinite(x.at) && sessionStats(x.s).completed > 0);
  const week = real.filter((x) => now - x.at <= 7 * DAY_MS);

  let clean = 0, done = 0, planned = 0;
  const perClient = new Map<string, { name: string; clean: number; done: number }>();
  for (const x of week) {
    const r = cleanReps(x.s);
    const st = sessionStats(x.s);
    clean += r.clean; done += r.done; planned += st.planned;
    const p = perClient.get(x.c.id) ?? { name: x.c.name, clean: 0, done: 0 };
    p.clean += r.clean; p.done += r.done;
    perClient.set(x.c.id, p);
  }
  const best = [...perClient.values()].filter((p) => p.done > 0).sort((a, b) => b.clean / b.done - a.clean / a.done)[0];

  const days: DayPoint[] = [];
  for (let i = 6; i >= 0; i--) {
    const t = now - i * DAY_MS;
    const key = dayKey(t);
    const onDay = real.filter((x) => dayKey(x.at) === key);
    const r = onDay.reduce((a, x) => { const c = cleanReps(x.s); return { clean: a.clean + c.clean, done: a.done + c.done }; }, { clean: 0, done: 0 });
    days.push({
      key,
      label: new Date(t).toLocaleDateString("en-US", { weekday: "short", timeZone: COACH_TZ }).charAt(0),
      clean: r.done ? r.clean / r.done : null,
      sessions: onDay.length,
    });
  }

  const calendar: Record<string, number> = {};
  for (const x of real) calendar[dayKey(x.at)] = (calendar[dayKey(x.at)] ?? 0) + 1;

  const item = (x: (typeof all)[number]): RecentItem => {
    const st = sessionStats(x.s);
    const flagged = flaggedSets(x.s).length;
    const pct = st.cleanRate === null ? "" : ` · ${Math.round(st.cleanRate * 100)}% clean`;
    return {
      clientId: x.c.id,
      clientName: x.c.name,
      token: x.s.session.share_token,
      title: x.s.day?.title ?? "Workout",
      at: x.at,
      detail: st.completed === 0 ? "No reps counted" : flagged ? `${flagged} ${flagged === 1 ? "set" : "sets"} to review${pct}` : `All sets solid${pct}`,
      tone: st.completed === 0 ? "empty" : flagged ? "review" : "good",
    };
  };
  const byNewest = [...real].sort((a, b) => b.at - a.at);

  return {
    now,
    summaries,
    activeClients: summaries.filter((s) => s.status !== "inactive").length,
    sessionsThisWeek: week.length,
    cleanThisWeek: done ? clean / done : null,
    completionThisWeek: planned ? Math.min(1, done / planned) : null,
    needReview: summaries.filter((s) => s.status === "review").length,
    bestForm: best ? { name: best.name, clean: best.clean / best.done } : null,
    days,
    calendar,
    today: byNewest.filter((x) => dayKey(x.at) === dayKey(now)).map(item),
    recent: byNewest.slice(0, 6).map(item),
  };
}
