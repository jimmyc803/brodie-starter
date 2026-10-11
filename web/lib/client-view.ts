import "server-only";

import { hasSupabase } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// What a client sees on their personal link /go/<clients.share_token>: who they train with, today's day, their recent recaps.
export type ClientRecap = { token: string; startedAt: string; completed: number; planned: number };
export type ClientHome = { id: string; name: string; coachName: string; next: string | null; recaps: ClientRecap[] };

export const CLIENT_TOKEN_RE = /^[A-Za-z0-9_-]{16,80}$/;

export async function getClientHome(token: string): Promise<ClientHome | null> {
  if (!CLIENT_TOKEN_RE.test(token) || !hasSupabase()) return null;
  const db = supabaseServer();
  const { data: client, error } = await db.from("clients").select("id, name, coaches(name)").eq("share_token", token).maybeSingle();
  if (error) throw new Error(`client lookup failed: ${error.message}`);
  if (!client) return null;
  const [{ data: active }, { data: sessions }] = await Promise.all([
    db.from("assignments").select("program_days(title, day_number)").eq("client_id", client.id).eq("active", true).order("assigned_at", { ascending: false }).limit(1),
    db.from("sessions").select("share_token, started_at, sets(completed_reps, planned_reps)").eq("client_id", client.id).order("started_at", { ascending: false }).limit(8),
  ]);
  const day = (active?.[0] as { program_days?: { title?: string; day_number?: number } | null } | undefined)?.program_days;
  const coach = client.coaches as unknown as { name?: string } | null;
  return {
    id: client.id as string,
    name: client.name as string,
    coachName: coach?.name ?? "your coach",
    next: day?.title ?? null,
    recaps: (sessions ?? [])
      .map((s) => {
        const sets = (s.sets ?? []) as { completed_reps: number; planned_reps: number }[];
        return {
          token: s.share_token as string,
          startedAt: s.started_at as string,
          completed: sets.reduce((n, x) => n + x.completed_reps, 0),
          planned: sets.reduce((n, x) => n + x.planned_reps, 0),
        };
      })
      .filter((r) => r.completed > 0),
  };
}

// The client's id for minting a call, or null for an unknown link.
export async function clientIdForToken(token: string): Promise<string | null> {
  if (!CLIENT_TOKEN_RE.test(token) || !hasSupabase()) return null;
  const { data, error } = await supabaseServer().from("clients").select("id").eq("share_token", token).maybeSingle();
  if (error) throw new Error(`client lookup failed: ${error.message}`);
  return (data?.id as string | undefined) ?? null;
}
