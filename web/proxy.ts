import { NextResponse, type NextRequest } from "next/server";

import { SAMPLE_COACH_TOKEN, SAMPLE_SESSION_TOKEN, hasSupabase } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// Unknown recap (/r) and coach dashboard (/c) links get a real 404 status. Both pages stream (Cache Components), so a notFound() inside it can
// only produce a soft 404 (status 200 + noindex); this one cheap lookup runs before the response starts.
export const config = { matcher: ["/r/:token", "/c/:token"] };

const TOKEN_RE = /^[A-Za-z0-9_-]{4,80}$/;

async function sessionExists(token: string): Promise<boolean> {
  if (!TOKEN_RE.test(token)) return false;
  if (token === "demo" || token === SAMPLE_SESSION_TOKEN) return true; // the sample session always works
  if (!hasSupabase()) return false;
  const { data, error } = await supabaseServer().from("sessions").select("id").eq("share_token", token).maybeSingle();
  if (error) return true; // let the page surface the real error
  return Boolean(data);
}

// Mirrors lib/coach-view.ts: without Supabase env vars only "demo" and the sample coach token exist.
async function coachExists(token: string): Promise<boolean> {
  if (!TOKEN_RE.test(token)) return false;
  if (token === "demo" || token === SAMPLE_COACH_TOKEN) return true; // the demo coach always works
  if (!hasSupabase()) return false;
  const { data, error } = await supabaseServer().from("coaches").select("id").eq("share_token", token).maybeSingle();
  if (error) return true; // let the page surface the real error
  return Boolean(data);
}

export async function proxy(req: NextRequest) {
  const [, kind, raw] = req.nextUrl.pathname.split("/");
  const token = decodeURIComponent(raw ?? "");
  const exists = kind === "c" ? await coachExists(token) : await sessionExists(token);
  if (exists) return NextResponse.next();
  return NextResponse.rewrite(new URL("/_not-found", req.url), { status: 404 });
}
