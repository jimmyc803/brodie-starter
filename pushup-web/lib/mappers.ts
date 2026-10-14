import type { CompetitionPublic, LeaderboardRow, LineStatus, LineSummary, PowerHour } from "./types";

type Raw = Record<string, unknown>;

const num = (v: unknown, d = 0): number => {
  const n = typeof v === "string" ? Number(v) : (v as number);
  return typeof n === "number" && Number.isFinite(n) ? n : d;
};
const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);

export function mapLeaderboardRow(r: Raw): LeaderboardRow {
  return {
    rank: num(r.rank),
    publicId: str(r.public_id),
    displayName: str(r.display_name),
    points: num(r.points),
    validReps: num(r.valid_reps),
    streak: num(r.streak),
    avatarLevel: Math.min(10, Math.max(1, num(r.avatar_level, 1))),
    badges: Array.isArray(r.badges) ? r.badges.filter((b): b is string => typeof b === "string") : [],
    reachedAt: strOrNull(r.reached_at),
  };
}

const SUMMARIES: LineSummary[] = ["idle", "in_call", "offline", "claimed", "closed"];

export function mapLineStatus(r: Raw): LineStatus {
  const s = str(r.state_summary) as LineSummary;
  return {
    stateSummary: SUMMARIES.includes(s) ? s : "closed",
    queueLength: num(r.queue_length),
    linesActive: num(r.lines_active),
    etaCycleS: r.eta_cycle_s == null ? null : num(r.eta_cycle_s),
    updatedAt: strOrNull(r.updated_at),
  };
}

export function mapPowerHour(r: Raw): PowerHour {
  return { dateEt: str(r.date_et), startsAt: str(r.starts_at), endsAt: str(r.ends_at) };
}

export function mapCompetition(r: Raw): CompetitionPublic {
  return {
    windowStart: str(r.window_start),
    windowEnd: str(r.window_end),
    frozen: r.frozen === true,
    ufcFighter: strOrNull(r.ufc_fighter),
    firstPrize: str(r.first_prize, "$100"),
    drawingPrize: str(r.drawing_prize, "$100"),
    brodieNumber: strOrNull(r.brodie_number),
    siteUrl: strOrNull(r.site_url),
  };
}

/** Top-3 prize copy: the configured fighter name, or a generic fallback while unset. */
export function ufcFighterCopy(name: string | null | undefined): string {
  const n = name?.trim();
  return n ? n : "a UFC fighter";
}

/**
 * Headline total of the two cash prizes, e.g. "$500" + "$500" -> "$1,000". Both are free-text config, so anything
 * that is not a plain dollar amount falls back to showing the top-scorer prize rather than inventing a total.
 */
export function prizePool(first: string | null | undefined, drawing: string | null | undefined): string {
  const amount = (s: string | null | undefined): number | null => {
    const m = s?.trim().match(/^\$([\d,]+)$/);
    if (!m) return null;
    const n = Number(m[1].replace(/,/g, ""));
    return Number.isFinite(n) ? n : null;
  };
  const a = amount(first);
  const b = amount(drawing);
  if (a === null || b === null) return (first ?? "").trim() || "$500";
  return `$${(a + b).toLocaleString("en-US")}`;
}

/** Case-insensitive display-name filter for the "find me" box. */
export function filterByName<T extends { displayName: string }>(rows: T[], q: string): T[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((r) => r.displayName.toLowerCase().includes(needle));
}

/** Escape a user string for a PostgREST ilike pattern (wildcards, backslash). */
export function ilikePattern(q: string): string {
  const esc = q.trim().replace(/[\\%_]/g, (c) => `\\${c}`);
  return `%${esc}%`;
}
