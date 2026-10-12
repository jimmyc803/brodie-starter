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
    rafflePrize: str(r.raffle_prize, "TBD"),
    raffleMinValidReps: num(r.raffle_min_valid_reps, 100),
    brodieNumber: strOrNull(r.brodie_number),
    siteUrl: strOrNull(r.site_url),
  };
}

/** Case-insensitive display-name filter for the "find me" box. */
export function filterByName<T extends { displayName: string }>(rows: T[], q: string): T[] {
  const needle = q.trim().toLowerCase();
  if (!needle) return rows;
  return rows.filter((r) => r.displayName.toLowerCase().includes(needle));
}
