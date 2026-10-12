import "server-only";
import { headers } from "next/headers";

// The public origin for links we email out: SITE_URL when set (e.g. https://brodie-for-coaches.vercel.app), else this request's host.
export async function siteOrigin(): Promise<string> {
  const fixed = process.env.SITE_URL?.replace(/\/+$/, "");
  if (fixed) return fixed;
  const h = await headers();
  const host = h.get("x-forwarded-host") ?? h.get("host") ?? "brodie-for-coaches.vercel.app";
  const proto = h.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  return `${proto}://${host}`;
}

export const coachLink = (origin: string, token: string) => `${origin}/c/${encodeURIComponent(token)}`;
