import { ImageResponse } from "next/og";
import { ResultCard } from "@/lib/card";
import { getResultCardModel } from "@/lib/data";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, { params }: { params: Promise<{ callId: string }> }) {
  const { callId } = await params;
  const model = await getResultCardModel(callId);
  if (!model) return new Response("Result not found", { status: 404 });
  return new ImageResponse(<ResultCard model={model} />, {
    width: 1080, height: 1350,
    headers: { "Cache-Control": "no-store" },
  });
}
