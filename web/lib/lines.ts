import "server-only";

import { hasSupabase } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// FaceTime lines (db/migrations/20261012_call_lines.sql): the client reserves a free line, then FaceTimes it; the worker on
// that line matches the call to the reservation.
export const CLAIM_TTL_S = 180;

export type LineClaim =
  | { ok: true; handle: string; facetime: string; expiresAt: string }
  | { ok: false; nextFreeAt: string | null };

// True when at least one line is set up: the client page offers FaceTime instead of the in-browser call.
export async function linesEnabled(): Promise<boolean> {
  if (!hasSupabase()) return false;
  const { count, error } = await supabaseServer().from("call_lines").select("id", { count: "exact", head: true }).eq("enabled", true);
  return !error && (count ?? 0) > 0;
}

// facetime:<number or Apple ID> opens a FaceTime video call on iPhone and Mac.
export function facetimeUrl(handle: string): string {
  const h = handle.trim();
  return `facetime:${h.includes("@") ? h : h.replace(/[^\d+]/g, "")}`;
}

export async function claimLine(clientId: string): Promise<LineClaim> {
  const { data, error } = await supabaseServer().rpc("claim_line", { p_client: clientId, p_ttl_s: CLAIM_TTL_S });
  if (error) throw new Error(`claim_line failed: ${error.message}`);
  const row = (Array.isArray(data) ? data[0] : data) as
    | { line_id: string | null; facetime_handle: string | null; expires_at: string | null; next_free_at: string | null }
    | undefined;
  if (!row?.line_id || !row.facetime_handle || !row.expires_at) return { ok: false, nextFreeAt: row?.next_free_at ?? null };
  return { ok: true, handle: row.facetime_handle, facetime: facetimeUrl(row.facetime_handle), expiresAt: row.expires_at };
}
