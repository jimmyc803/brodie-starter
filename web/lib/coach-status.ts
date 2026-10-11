import type { SessionView } from "@/lib/contract";
import { flaggedSets, sessionStats } from "@/lib/recap";

// Where a client stands for the coach's triage list. Pure, so the dashboard and tests share it.
export type ClientStatus = "review" | "on_track" | "inactive";

export const INACTIVE_DAYS = 7;
const DAY_MS = 24 * 60 * 60 * 1000;

export type ClientSummary = {
  id: string;
  name: string;
  status: ClientStatus;
  detail: string; // one line under the name: "Today · 4 sets flagged"
  thisWeek: number; // sessions in the last 7 days
  lastAt: number | null; // ms, newest session
};

export function relativeDay(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  const days = Math.floor((startOfDay(now) - startOfDay(t)) / DAY_MS);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return new Date(t).toLocaleDateString("en-US", { weekday: "short" });
  return new Date(t).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function startOfDay(t: number): number {
  const d = new Date(t);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function summarizeClient(c: { id: string; name: string; sessions: SessionView[] }, now = Date.now()): ClientSummary {
  const latest = c.sessions[0];
  const lastAt = latest ? Date.parse(latest.session.started_at) : null;
  const thisWeek = c.sessions.filter((s) => now - Date.parse(s.session.started_at) <= INACTIVE_DAYS * DAY_MS).length;
  if (!latest || lastAt === null || !Number.isFinite(lastAt))
    return { id: c.id, name: c.name, status: "inactive", detail: "No sessions yet", thisWeek, lastAt: null };
  const idleDays = Math.floor((now - lastAt) / DAY_MS);
  if (idleDays >= INACTIVE_DAYS)
    return { id: c.id, name: c.name, status: "inactive", detail: `No session in ${idleDays} days`, thisWeek, lastAt };
  const when = relativeDay(latest.session.started_at, now);
  const flagged = flaggedSets(latest).length;
  if (flagged > 0)
    return { id: c.id, name: c.name, status: "review", detail: `${when} · ${flagged} ${flagged === 1 ? "set" : "sets"} to review`, thisWeek, lastAt };
  const st = sessionStats(latest);
  if (st.completed === 0 || st.endedEarly || st.completed < st.planned)
    return {
      id: c.id, name: c.name, status: "review",
      detail: `${when} · ${st.completed === 0 ? "No reps counted" : "Incomplete session"}`,
      thisWeek, lastAt,
    };
  const clean = st.cleanRate === null ? "" : ` · ${Math.round(st.cleanRate * 100)}% clean`;
  return { id: c.id, name: c.name, status: "on_track", detail: `${when}${clean}`, thisWeek, lastAt };
}

const ORDER: Record<ClientStatus, number> = { review: 0, on_track: 1, inactive: 2 };

// Needs review first, then on track, then inactive; newest session first inside each group.
export function sortSummaries(list: ClientSummary[]): ClientSummary[] {
  return [...list].sort((a, b) => ORDER[a.status] - ORDER[b.status] || (b.lastAt ?? 0) - (a.lastAt ?? 0) || a.name.localeCompare(b.name));
}
