import { NextResponse } from "next/server";
import { currentAccessToken, fetchMe, webJoinEnabled } from "@/lib/me";

/** Polled by /me every 3 s (and on every realtime pulse): the signed-in user's own status, never cached. */
export async function GET() {
  const headers = { "Cache-Control": "no-store" };
  if (!webJoinEnabled()) return NextResponse.json({ error: "disabled" }, { status: 404, headers });
  const res = await fetchMe(await currentAccessToken());
  if (res.status === "unauthenticated") return NextResponse.json({ error: "unauthenticated" }, { status: 401, headers });
  if (res.status === "error") return NextResponse.json({ error: res.message }, { status: 502, headers });
  return NextResponse.json(res.me, { headers });
}
