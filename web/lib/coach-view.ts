import "server-only";

import type { SessionView } from "@/lib/contract";
import {
  assembleView,
  hasSupabase,
  sampleSessionView,
  SAMPLE_COACH_TOKEN,
  type SessionRow,
} from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// Coach dashboard data for /c/[token]: the coach, their clients, and each client's sessions as full session views
// (newest first). Without Supabase env vars it serves the sample coach (Tristan) with the sample session.
export type CoachView = {
  coach: { name: string };
  clients: CoachClient[];
};
// next: the program day the client loads on their next call (their active assignment), if any.
export type CoachClient = { id: string; name: string; sessions: SessionView[]; next: string | null };

const TOKEN_RE = /^[A-Za-z0-9_-]{4,80}$/;
const SESSIONS_PER_CLIENT = 10;

export async function getCoachView(token: string): Promise<CoachView | null> {
  if (!TOKEN_RE.test(token)) return null;
  const isSample = token === "demo" || token === SAMPLE_COACH_TOKEN;
  const sample = (): CoachView => {
    const view = sampleSessionView();
    return { coach: view.coach, clients: [{ id: "sample-client", name: view.client.name, sessions: [view], next: view.day?.title ?? null }] };
  };
  if (!hasSupabase()) return isSample ? sample() : null;

  // "demo" opens the seeded demo coach (Tristan) with his real sessions; the sample is the fallback if he is not seeded.
  const db = supabaseServer();
  const lookup = token === "demo" ? SAMPLE_COACH_TOKEN : token;
  const { data: coach, error } = await db.from("coaches").select("id, name").eq("share_token", lookup).maybeSingle();
  if (error) throw new Error(`coaches lookup failed: ${error.message}`);
  if (!coach) return isSample ? sample() : null;

  const { data: clients, error: cErr } = await db
    .from("clients")
    .select("id, name")
    .eq("coach_id", coach.id)
    .order("created_at", { ascending: true });
  if (cErr) throw new Error(`clients lookup failed: ${cErr.message}`);

  const out = await Promise.all(
    (clients ?? []).map(async (c) => {
      const [{ data: active }, { data: rows, error: sErr }] = await Promise.all([
        db
          .from("assignments")
          .select("program_days(title, day_number)")
          .eq("client_id", c.id)
          .eq("active", true)
          .order("assigned_at", { ascending: false })
          .limit(1),
        db
        .from("sessions")
        .select("id, started_at, ended_at, share_token, program_days(title, day_number, exercises)")
        .eq("client_id", c.id)
        .order("started_at", { ascending: false })
          .limit(SESSIONS_PER_CLIENT),
      ]);
      if (sErr) throw new Error(`sessions lookup failed: ${sErr.message}`);
      const sessions = await Promise.all(
        (rows ?? []).map((r) =>
          assembleView({
            ...(r as unknown as Omit<SessionRow, "clients">),
            clients: { name: c.name, coaches: { name: coach.name } },
          }),
        ),
      );
      const day = (active?.[0] as { program_days?: { title?: string; day_number?: number } | null } | undefined)?.program_days;
      const next = day?.title ? (day.title.startsWith("Day") ? day.title : `Day ${day.day_number}: ${day.title}`) : null;
      return { id: c.id as string, name: c.name as string, sessions, next };
    }),
  );
  return { coach: { name: coach.name }, clients: out };
}
