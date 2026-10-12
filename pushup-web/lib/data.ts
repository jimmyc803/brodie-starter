import "server-only";
import {
  mapCompetition,
  mapLeaderboardRow,
  mapLineStatus,
  mapPowerHour,
} from "./mappers";
import { pickPowerHour } from "./format";
import {
  fixtureCompetition,
  fixtureLeaderboard,
  fixtureLineStatus,
  fixturePowerHour,
} from "./fixtures";
import type { CompetitionPublic, LeaderboardRow, LineStatus, PowerHour } from "./types";

/** Design/QA mode: rich deterministic data, no network. PUSHUP_FIXTURE_FROZEN=1 shows the final state. */
const FIXTURES = process.env.PUSHUP_FIXTURES === "1";
const FIXTURE_FROZEN = process.env.PUSHUP_FIXTURE_FROZEN === "1";

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
  if (FIXTURES) return fixtureLeaderboard().slice(0, Math.floor(limit));
  const rows = await fetchView(
    `leaderboard_public?select=*&order=rank.asc&limit=${Math.floor(limit)}`,
  );
  return rows.map(mapLeaderboardRow);
}

export async function getLineStatus(): Promise<LineStatus | null> {
  if (FIXTURES) return fixtureLineStatus(Date.now());
  const rows = await fetchView("line_status_public?select=*&limit=1");
  return rows[0] ? mapLineStatus(rows[0]) : null;
}

/** Today's ET power hour, else the nearest upcoming one. */
export async function getPowerHour(): Promise<PowerHour | null> {
  const nowMs = Date.now();
  if (FIXTURES) return fixturePowerHour(nowMs);
  const from = new Date(nowMs - 2 * 86_400_000).toISOString().slice(0, 10);
  const rows = await fetchView(`power_hour_public?select=*&date_et=gte.${from}&order=date_et.asc&limit=14`);
  return pickPowerHour(rows.map(mapPowerHour), nowMs);
}

export async function getCompetition(): Promise<CompetitionPublic | null> {
  if (FIXTURES) return fixtureCompetition(FIXTURE_FROZEN);
  const rows = await fetchView("competition_public?select=*&limit=1");
  return rows[0] ? mapCompetition(rows[0]) : null;
}
