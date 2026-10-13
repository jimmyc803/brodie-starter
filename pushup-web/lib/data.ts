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
import { makeCardModel, mapCallResult, mapDaily, mapProfile, mapThresholds } from "./card";

const FIXTURE_THRESHOLDS = [0, 25, 60, 120, 200, 300, 450, 650, 900, 1200];

const fixtureCallId = "00000000-0000-4000-8000-000000000042";

function fixtureView(path: string): Record<string, unknown>[] {
  const [view, query] = path.split("?");
  const nextStart = new Date(Date.now() + 86_400_000);
  const fixtures: Record<string, Record<string, unknown>[]> = {
    user_public: [{ display_name: "FixtureAthlete", points: 130, valid_reps: 110, streak: 3,
      avatar_level: 4, rank: 6, best_call_points: 30, best_call_id: fixtureCallId }],
    user_daily_public: [
      { display_name: "FixtureAthlete", date_et: "2026-10-12", points: 40, valid_reps: 40, calls: 2 },
      { display_name: "FixtureAthlete", date_et: "2026-10-13", points: 60, valid_reps: 40, calls: 2 },
      { display_name: "FixtureAthlete", date_et: "2026-10-14", points: 30, valid_reps: 30, calls: 1 },
    ],
    call_result_public: [{ call_id: fixtureCallId, display_name: "FixtureAthlete",
      connected_at: "2026-10-14T18:00:00Z", valid_reps: 30, rejected_reps: 4, points: 30,
      reasons: { too_shallow: 3, no_lockout: 1 }, liveness_result: "pass", void: false,
      rank_before: 9, rank_after: 6, points_before: 100, total_points_after: 130,
      avatar_level_before: 3, avatar_level_after: 4 }],
    competition_public: [{ window_start: "2026-10-13T00:00:00Z", window_end: "2026-10-21T03:59:59Z",
      frozen: false, site_url: "https://brodie-pushups.vercel.app",
      avatar_level_thresholds: FIXTURE_THRESHOLDS }],
    power_hour_public: [{ date_et: nextStart.toISOString().slice(0, 10), starts_at: nextStart.toISOString(),
      ends_at: new Date(nextStart.getTime() + 3_600_000).toISOString() }],
  };
  const params = new URLSearchParams(query);
  return (fixtures[view] ?? []).filter((row) => {
    for (const key of ["display_name", "call_id"]) {
      const filter = params.get(key);
      if (filter?.startsWith("eq.") && String(row[key]) !== filter.slice(3)) return false;
    }
    return true;
  });
}

/** Design/QA mode: rich deterministic data, no network. PUSHUP_FIXTURE_FROZEN=1 shows the final state. */
const FIXTURES = process.env.PUSHUP_FIXTURES === "1";
const FIXTURE_FROZEN = process.env.PUSHUP_FIXTURE_FROZEN === "1";

/** GET a PostgREST view with the anon key. Returns [] if env is missing or the request fails. */
async function fetchView(path: string): Promise<Record<string, unknown>[]> {
  if (process.env.PUSHUP_FIXTURES === "1") return fixtureView(path);
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

export async function getCompetition(): Promise<(CompetitionPublic & { avatarLevelThresholds: number[] }) | null> {
  if (FIXTURES) return { ...fixtureCompetition(FIXTURE_FROZEN), avatarLevelThresholds: FIXTURE_THRESHOLDS };
  const rows = await fetchView("competition_public?select=*&limit=1");
  return rows[0] ? { ...mapCompetition(rows[0]), avatarLevelThresholds: mapThresholds(rows[0].avatar_level_thresholds) } : null;
}

function filteredView(view: string, column: string, value: string, extra: Record<string, string> = {}) {
  const query = new URLSearchParams(extra);
  return fetchView(`${view}?select=*&${column}=eq.${encodeURIComponent(String(value))}&${query}`);
}

export async function getProfile(name: string) {
  const rows = await filteredView("user_public", "display_name", name, { limit: "1" });
  return rows[0] ? mapProfile(rows[0]) : null;
}

export async function getUserDaily(name: string) {
  const rows = await filteredView("user_daily_public", "display_name", name, { order: "date_et.asc" });
  return rows.map(mapDaily);
}

export async function getCallResult(callId: string) {
  const rows = await filteredView("call_result_public", "call_id", callId, { limit: "1" });
  return rows[0] ? mapCallResult(rows[0]) : null;
}

export async function getNextPowerHour(): Promise<PowerHour | null> {
  const query = new URLSearchParams({ select: "*", starts_at: `gt.${new Date().toISOString()}`, order: "starts_at.asc", limit: "1" });
  const rows = await fetchView(`power_hour_public?${query}`);
  return rows[0] ? mapPowerHour(rows[0]) : null;
}

export async function getResultCardModel(callId: string) {
  const result = await getCallResult(callId);
  if (!result) return null;
  const [powerHour, competition] = await Promise.all([
    getNextPowerHour(), getCompetition(),
  ]);
  // call_result_public exposes no stable user key; display names may be shared.
  // Use the call's snapshots and leave profile-only streak data unavailable.
  return makeCardModel(result, null, powerHour, competition?.siteUrl);
}
