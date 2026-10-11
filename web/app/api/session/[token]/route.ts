import { getSessionView } from "@/lib/session-view";

// The session view JSON (team contract). 404 for an unknown token.
export async function GET(_req: Request, ctx: RouteContext<"/api/session/[token]">) {
  const { token } = await ctx.params;
  const view = await getSessionView(token);
  if (!view) return Response.json({ error: "not found" }, { status: 404 });
  return Response.json(view, { headers: { "Cache-Control": "private, no-store" } });
}
