import { ImageResponse } from "next/og";

import { CARD_HEIGHT, CARD_WIDTH, RecapCardImage } from "@/lib/recap-image/card";
import { recapCard } from "@/lib/recap-image/model";
import { getSessionView } from "@/lib/session-view";

// The recap card PNG (1080 x 1920) for a session share token: FaceTime video, iMessage image and link preview.
// Rendered per request (dynamic [token] param, no generateStaticParams). 404 for an unknown token.
const NO_STORE = { "Cache-Control": "private, no-store" };

export async function GET(_req: Request, ctx: RouteContext<"/api/recap-image/[token]">) {
  const { token } = await ctx.params;
  try {
    const view = await getSessionView(token);
    if (!view) return Response.json({ error: "not found" }, { status: 404, headers: NO_STORE });
    const res = new ImageResponse(<RecapCardImage card={recapCard(view)} />, {
      width: CARD_WIDTH,
      height: CARD_HEIGHT,
      headers: NO_STORE,
    });
    // ImageResponse renders lazily inside its stream; buffer it so render errors become a clean 500.
    const png = await res.arrayBuffer();
    return new Response(png, {
      headers: { "Content-Type": "image/png", "Content-Length": String(png.byteLength), ...NO_STORE },
    });
  } catch (e) {
    console.error("recap-image failed:", e instanceof Error ? e.message : e);
    return Response.json({ error: "internal error" }, { status: 500, headers: NO_STORE });
  }
}
