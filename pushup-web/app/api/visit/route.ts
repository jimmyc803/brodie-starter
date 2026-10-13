import { NextResponse, type NextRequest } from "next/server";
import { isSameOriginRequest, parseVisit } from "@/lib/attribution";
import { serviceRpc } from "@/lib/supabase-server";

const MAX_BODY = 1024;
const headers = { "Cache-Control": "no-store" };

/**
 * First-party visit counter (components/visit-beacon.tsx). Stores kind, path, link tags and referrer domain only:
 * never the IP address, user agent, cookies or any identifier. Same-origin requests only.
 */
export async function POST(req: NextRequest) {
  if (!isSameOriginRequest(req.headers)) return new NextResponse(null, { status: 403, headers });
  const text = await req.text();
  if (text.length > MAX_BODY) return new NextResponse(null, { status: 413, headers });
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return new NextResponse(null, { status: 400, headers });
  }
  const visit = parseVisit(raw);
  if (!visit) return new NextResponse(null, { status: 400, headers });
  try {
    await serviceRpc("ch_site_visit", {
      p_kind: visit.kind,
      p_path: visit.path,
      p_source: visit.src,
      p_ref_code: visit.ref,
      p_referrer_host: visit.referrer_host,
      p_now: new Date().toISOString(),
    });
  } catch (e) {
    console.error("[visit] record failed", e instanceof Error ? e.message : e);
    return new NextResponse(null, { status: 503, headers });
  }
  return new NextResponse(null, { status: 204, headers });
}
