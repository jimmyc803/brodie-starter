import { NextResponse } from "next/server";

import { clientIdForToken } from "@/lib/client-view";
import { claimLine, linesEnabled } from "@/lib/lines";

// POST /api/line/<clients.share_token>: reserve a FaceTime line for this client's workout (or say when one frees up).
export async function POST(_req: Request, ctx: RouteContext<"/api/line/[token]">) {
  const { token } = await ctx.params;
  const clientId = await clientIdForToken(token);
  if (!clientId) return NextResponse.json({ error: "This workout link is not valid." }, { status: 404 });
  if (!(await linesEnabled())) return NextResponse.json({ error: "FaceTime lines are not set up yet." }, { status: 503 });
  const claim = await claimLine(clientId);
  return NextResponse.json(claim, { headers: { "Cache-Control": "no-store" } });
}
