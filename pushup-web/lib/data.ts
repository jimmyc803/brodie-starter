import "server-only";
import {
  mapCompetition,
  mapLeaderboardRow,
  mapLineStatus,
  mapPowerHour,
} from "./mappers";
import type { CompetitionPublic, LeaderboardRow, LineStatus, PowerHour } from "./types";

/** GET a PostgREST view with the anon key. Returns [] if env is missing or the request fails. */
async function fetchView(path: string): Promise<Record<string, unknown>[]> {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !key) return [];
  try {
    const res = await fetch(`${url}/rest/v1/${path}`, {
      headers: { apikey: key, Authorization: `Bearer ${key}` },
      cache: "no-store",
    });
    if (!res.ok) return [];
    const body: unknown = await res.json();
    return Array.isArray(body) ? (body as Record<string, unknown>[]) : [];
  } catch {
    return [];
  }
}

export async function getLeaderboard(limit = 100): Promise<LeaderboardRow[]> {
  const rows = await fetchView(
    `leaderboard_public?select=*&order=rank.asc&limit=${Math.floor(limit)}`,
  );
  return rows.map(mapLeaderboardRow);
}

export async function getLineStatus(): Promise<LineStatus | null> {
  const rows = await fetchView("line_status_public?select=*&limit=1");
  return rows[0] ? mapLineStatus(rows[0]) : null;
}

/** Today's (or the next upcoming) power hour: the most recent rows by date. */
export async function getPowerHour(): Promise<PowerHour | null> {
  const rows = await fetchView("power_hour_public?select=*&order=date_et.desc&limit=1");
  return rows[0] ? mapPowerHour(rows[0]) : null;
}

export async function getCompetition(): Promise<CompetitionPublic | null> {
  const rows = await fetchView("competition_public?select=*&limit=1");
  return rows[0] ? mapCompetition(rows[0]) : null;
}
