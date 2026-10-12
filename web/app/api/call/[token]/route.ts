import { NextResponse } from "next/server";

import { clientIdForToken } from "@/lib/client-view";
import { livekitConfigured, mintCallPass } from "@/lib/livekit";

// POST /api/call/<clients.share_token>: a one-hour pass into a fresh room for this client's workout with Brodie.
export async function POST(_req: Request, ctx: RouteContext<"/api/call/[token]">) {
  const { token } = await ctx.params;
  if (!livekitConfigured()) return NextResponse.json({ error: "Calls are not set up yet." }, { status: 503 });
  const clientId = await clientIdForToken(token);
  if (!clientId) return NextResponse.json({ error: "This workout link is not valid." }, { status: 404 });
  const pass = await mintCallPass(clientId);
  return NextResponse.json(pass, { headers: { "Cache-Control": "no-store" } });
}
