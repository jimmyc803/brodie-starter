import { NextResponse, type NextRequest } from "next/server";

import { SAMPLE_SESSION_TOKEN, hasSupabase } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// Unknown recap links get a real 404 status. The recap page streams (Cache Components), so a notFound() inside it can
// only produce a soft 404 (status 200 + noindex); this one cheap lookup runs before the response starts.
export const config = { matcher: "/r/:token" };

const TOKEN_RE = /^[A-Za-z0-9_-]{4,80}$/;

async function sessionExists(token: string): Promise<boolean> {
  if (!TOKEN_RE.test(token)) return false;
  if (token === "demo") return true;
  if (!hasSupabase()) return token === SAMPLE_SESSION_TOKEN;
  const { data, error } = await supabaseServer().from("sessions").select("id").eq("share_token", token).maybeSingle();
  if (error) return true; // let the page surface the real error
  return Boolean(data);
}

export async function proxy(req: NextRequest) {
  const token = decodeURIComponent(req.nextUrl.pathname.split("/")[2] ?? "");
  if (await sessionExists(token)) return NextResponse.next();
  return NextResponse.rewrite(new URL("/_not-found", req.url), { status: 404 });
}
