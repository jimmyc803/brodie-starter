import "server-only";

import sample from "@/lib/generated/sample_session.json";
import {
  exerciseName,
  type ExerciseView,
  type MuscleScore,
  type SessionView,
} from "@/lib/contract";
import { supabaseServer } from "@/lib/supabase/server";

// Session view for /r/[token], /api/session/[token] and the recap image. Reads Supabase with the service role key;
// with no Supabase env vars it serves the sample session (db/fixtures/sample_session.json), but only for its own token
// or "demo", so a random link still 404s.
const SAMPLE = sample as unknown as SessionView & { coach: { share_token: string } };
export const SAMPLE_SESSION_TOKEN = SAMPLE.session.share_token;
export const SAMPLE_COACH_TOKEN = SAMPLE.coach.share_token;

export const hasSupabase = () => Boolean(process.env.SUPABASE_URL && process.env.SUPABASE_SERVICE_ROLE_KEY);

// Share tokens are 32 URL-safe chars; the demo tokens are longer. Reject anything else before touching the db.
const TOKEN_RE = /^[A-Za-z0-9_-]{4,80}$/;

export function sampleSessionView(): SessionView {
  return structuredClone(SAMPLE);
}

export async function getSessionView(token: string): Promise<SessionView | null> {
  if (!TOKEN_RE.test(token)) return null;
  if (!hasSupabase()) return token === SAMPLE_SESSION_TOKEN || token === "demo" ? sampleSessionView() : null;

  const db = supabaseServer();
  const { data: s, error } = await db
    .from("sessions")
    .select("id, started_at, ended_at, share_token, program_day_id, clients(name, coaches(name)), program_days(title, day_number, exercises)")
    .eq("share_token", token)
    .maybeSingle();
  if (error) throw new Error(`sessions lookup failed: ${error.message}`);
  if (!s) return token === "demo" || token === SAMPLE_SESSION_TOKEN ? sampleSessionView() : null;
  return assembleView(s as unknown as SessionRow);
}

export type SessionRow = {
  id: string;
  started_at: string;
  ended_at: string | null;
  share_token: string;
  clients: { name: string; coaches: { name: string } | null } | null;
  program_days: { title: string; day_number: number; exercises: { exercise_key: string | null; name?: string }[] } | null;
};

export async function assembleView(s: SessionRow): Promise<SessionView> {
  const db = supabaseServer();
  const [setsRes, musclesRes] = await Promise.all([
    db
      .from("sets")
      .select("exercise_key, set_number, planned_reps, completed_reps, started_at, ended_at, reps(rep_number, t, faults)")
      .eq("session_id", s.id),
    db.from("muscle_scores").select("muscle, score, color, coverage").eq("session_id", s.id),
  ]);
  if (setsRes.error) throw new Error(`sets lookup failed: ${setsRes.error.message}`);
  if (musclesRes.error) throw new Error(`muscle_scores lookup failed: ${musclesRes.error.message}`);

  // Group sets by exercise, in the day's order (then any extras in the order they appear).
  const dayItems = s.program_days?.exercises ?? [];
  const order = new Map<string, number>();
  dayItems.forEach((it, i) => it.exercise_key && !order.has(it.exercise_key) && order.set(it.exercise_key, i));
  const byKey = new Map<string, ExerciseView>();
  for (const row of setsRes.data ?? []) {
    const key = row.exercise_key as string;
    let ex = byKey.get(key);
    if (!ex) {
      const item = dayItems.find((it) => it.exercise_key === key);
      ex = { exercise_key: key, name: item?.name || exerciseName(key), planned_sets: 0, planned_reps: 0, sets: [] };
      byKey.set(key, ex);
    }
    const reps = ((row.reps as { rep_number: number; t: number; faults: string[] | null }[]) ?? [])
      .map((r) => ({ rep_number: r.rep_number, t: r.t, faults: r.faults ?? [] }))
      .sort((a, b) => a.rep_number - b.rep_number);
    ex.sets.push({
      set_number: row.set_number,
      planned_reps: row.planned_reps,
      completed_reps: row.completed_reps,
      started_at: row.started_at,
      ended_at: row.ended_at,
      reps,
    });
  }
  const exercises = [...byKey.values()]
    .map((ex) => {
      ex.sets.sort((a, b) => a.set_number - b.set_number);
      ex.planned_sets = ex.sets.length;
      ex.planned_reps = ex.sets[0]?.planned_reps ?? 0;
      return ex;
    })
    .sort((a, b) => (order.get(a.exercise_key) ?? 99) - (order.get(b.exercise_key) ?? 99));

  return {
    session: { id: s.id, started_at: s.started_at, ended_at: s.ended_at, share_token: s.share_token },
    client: { name: s.clients?.name ?? "Client" },
    coach: { name: s.clients?.coaches?.name ?? "Coach" },
    day: s.program_days ? { title: s.program_days.title, day_number: s.program_days.day_number } : null,
    exercises,
    muscles: (musclesRes.data ?? []) as MuscleScore[],
  };
}
