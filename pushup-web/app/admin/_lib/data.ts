import "server-only";
import { dispatcherRequest, etYesterday } from "@/lib/admin";
import { serviceRpc, serviceSelect } from "@/lib/supabase-server";
import type { RawMetrics } from "./metrics";

/** Page loaders for the admin console (service role; only call after requireAdmin()). */

export type Loaded<T> = { ok: true; data: T } | { ok: false; error: string };

/** Run a loader; failures are logged and returned so the page renders an explicit error box instead of crashing. */
export async function load<T>(label: string, fn: () => Promise<T>): Promise<Loaded<T>> {
  try {
    return { ok: true, data: await fn() };
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    console.error(`[admin] load ${label} failed`, msg);
    return { ok: false, error: `${label}: ${msg}` };
  }
}

const inList = (ids: string[]) => `(${ids.map((i) => encodeURIComponent(`"${i.replace(/"/g, "")}"`)).join(",")})`;

// ------------------------------------------------------------------ queue

export type QueueView = {
  lines: {
    line_id: string;
    state: string;
    user_id: string | null;
    call_id: string | null;
    claimed_until: string | null;
    offline_until: string | null;
    in_call_since: string | null;
  }[];
  queue: {
    queue_id: number;
    user_id: string;
    display_name: string | null;
    status: string;
    entered_at: string;
    calls_today: number;
    position: number | null;
  }[];
  avg_cycle_s: number | null;
};

export async function getQueueView(): Promise<QueueView> {
  const v = await serviceRpc<Partial<QueueView>>("ch_queue_view", { p_now: new Date().toISOString() });
  return { lines: v?.lines ?? [], queue: v?.queue ?? [], avg_cycle_s: v?.avg_cycle_s ?? null };
}

export async function displayNames(ids: string[]): Promise<Map<string, string>> {
  const uniq = [...new Set(ids.filter(Boolean))];
  if (!uniq.length) return new Map();
  const rows = await serviceSelect<{ id: string; display_name: string | null }>(
    `clients?select=id,display_name&id=in.${inList(uniq)}`,
  );
  return new Map(rows.map((r) => [r.id, r.display_name ?? "(no name)"]));
}

// ------------------------------------------------------------------ config

export async function getConfig(): Promise<Record<string, unknown>> {
  const c = await serviceRpc<Record<string, unknown> | null>("ch_config_get", {});
  return c ?? {};
}

// ------------------------------------------------------------------ users

export type AdminUser = {
  id: string;
  display_name: string | null;
  joined_at: string | null;
  banned_at: string | null;
  ban_reason: string | null;
  opted_out_at: string | null;
  is_team: boolean;
  points: number | null;
  rank: number | null;
};

/** Strip PostgREST/LIKE metacharacters from a free-text name search. */
export function sanitizeSearch(q: string): string {
  return q.replace(/[^\p{L}\p{N} _.'-]/gu, "").trim().slice(0, 64);
}

export async function searchUsers(q: string): Promise<AdminUser[]> {
  const term = sanitizeSearch(q);
  const base =
    "clients?select=id,display_name,joined_at,banned_at,ban_reason,opted_out_at,is_team&joined_at=not.is.null&limit=50";
  const byName = term
    ? serviceSelect<Omit<AdminUser, "points" | "rank">>(
        `${base}&display_name=ilike.${encodeURIComponent(`*${term}*`)}&order=display_name.asc`,
      )
    : serviceSelect<Omit<AdminUser, "points" | "rank">>(`${base}&order=joined_at.desc`);
  // Exact handle lookup (phone/email) so admins can find a texter by number.
  const handle = q.trim();
  const byHandle =
    handle && (handle.includes("@") || /^\+?\d{7,15}$/.test(handle))
      ? serviceRpc<{ user_id: string | null }>("ch_user_by_handle", { p_handle: handle })
      : Promise.resolve({ user_id: null });
  const [rows, h] = await Promise.all([byName, byHandle]);
  let all = rows;
  if (h?.user_id && !rows.some((r) => r.id === h.user_id)) {
    all = [
      ...(await serviceSelect<Omit<AdminUser, "points" | "rank">>(
        `clients?select=id,display_name,joined_at,banned_at,ban_reason,opted_out_at,is_team&id=eq.${encodeURIComponent(h.user_id)}`,
      )),
      ...rows,
    ];
  }
  const board = await serviceRpc<{ user_id: string; rank: number; points: number }[]>("ch_leaderboard", {
    p_limit: null,
    p_now: new Date().toISOString(),
  });
  const byId = new Map((board ?? []).map((b) => [b.user_id, b]));
  return all.map((u) => ({ ...u, points: byId.get(u.id)?.points ?? null, rank: byId.get(u.id)?.rank ?? null }));
}

// ------------------------------------------------------------------ metrics

/** Whole metrics page in one RPC (aggregated in Postgres; no per-user queries). */
export async function getMetrics(includeTeam: boolean, nowMs = Date.now()): Promise<RawMetrics> {
  return serviceRpc<RawMetrics>("ch_admin_metrics", {
    p_include_team: includeTeam,
    p_now: new Date(nowMs).toISOString(),
    p_days: 30,
  });
}

// ------------------------------------------------------------------ calls

export type AdminCall = {
  call_id: string;
  user_id: string | null;
  line_id: string | null;
  decision: string;
  void: boolean;
  counted_toward_cap: boolean;
  liveness_result: string | null;
  connected_at: string;
  ended_at: string | null;
  valid_reps: number;
  rejected_reps: number;
  points: number;
  display_name?: string;
  void_reason?: string | null;
  reject_reason?: string | null;
};

export async function recentCalls(filter: { callId?: string; userId?: string }): Promise<AdminCall[]> {
  let q =
    "ch_call_stats?select=call_id,user_id,line_id,decision,void,counted_toward_cap,liveness_result,connected_at,ended_at,valid_reps,rejected_reps,points&order=connected_at.desc&limit=50";
  if (filter.callId) q += `&call_id=eq.${encodeURIComponent(filter.callId)}`;
  if (filter.userId) q += `&user_id=eq.${encodeURIComponent(filter.userId)}`;
  const rows = await serviceSelect<AdminCall>(q);
  if (!rows.length) return rows;
  const [names, extra] = await Promise.all([
    displayNames(rows.map((r) => r.user_id ?? "")),
    serviceSelect<{ id: string; void_reason: string | null; reject_reason: string | null }>(
      `calls?select=id,void_reason,reject_reason&id=in.${inList(rows.map((r) => r.call_id))}`,
    ),
  ]);
  const ex = new Map(extra.map((e) => [e.id, e]));
  return rows.map((r) => ({
    ...r,
    display_name: r.user_id ? names.get(r.user_id) : undefined,
    void_reason: ex.get(r.call_id)?.void_reason ?? null,
    reject_reason: ex.get(r.call_id)?.reject_reason ?? null,
  }));
}

// ------------------------------------------------------------------ highlights

export type Highlights = {
  date: string;
  topScorers: { display_name: string; points: number; valid_reps: number; calls: number }[];
  bestCalls: { call_id: string; display_name: string; points: number; valid_reps: number; connected_at: string }[];
};

export async function getHighlights(nowMs = Date.now()): Promise<Highlights> {
  const { date } = etYesterday(nowMs);
  const [top, calls] = await Promise.all([
    serviceSelect<Highlights["topScorers"][number]>(
      `user_daily_public?select=display_name,points,valid_reps,calls&date_et=eq.${date}&order=points.desc,valid_reps.desc&limit=3`,
    ),
    serviceSelect<{ call_id: string; user_id: string; points: number; valid_reps: number; connected_at: string }>(
      `ch_call_stats?select=call_id,user_id,points,valid_reps,connected_at&date_et=eq.${date}&decision=eq.accept&void=is.false&order=points.desc,valid_reps.desc&limit=3`,
    ),
  ]);
  const names = await displayNames(calls.map((c) => c.user_id));
  return {
    date,
    topScorers: top,
    bestCalls: calls.map((c) => ({
      call_id: c.call_id,
      display_name: names.get(c.user_id) ?? "(unknown)",
      points: c.points,
      valid_reps: c.valid_reps,
      connected_at: c.connected_at,
    })),
  };
}

// ------------------------------------------------------------------ health

export type Heartbeat = { component: string; at: string; detail: unknown; stale: boolean };

export const HEARTBEAT_STALE_MS = 3 * 60_000;
export type FailedMessage = {
  id: number;
  template: string | null;
  status: string;
  attempts: number | null;
  last_error: string | null;
  created_at: string;
};

export async function getHeartbeats(nowMs = Date.now()): Promise<Heartbeat[]> {
  const rows = await serviceSelect<Omit<Heartbeat, "stale">>("heartbeats?select=component,at,detail&order=component.asc");
  return rows.map((r) => {
    const at = Date.parse(r.at);
    return { ...r, stale: Number.isNaN(at) || nowMs - at > HEARTBEAT_STALE_MS };
  });
}

export async function getFailedMessages(): Promise<FailedMessage[]> {
  // No handle/body columns: the console never needs recipients' phone numbers to triage failures.
  return serviceSelect<FailedMessage>(
    "messages?select=id,template,status,attempts,last_error,created_at&direction=eq.out&status=eq.failed&order=created_at.desc&limit=25",
  );
}

export async function getDispatcherHealth(email: string): Promise<Record<string, unknown>> {
  return dispatcherRequest<Record<string, unknown>>("GET", "/health", { email, timeoutMs: 5_000 });
}
