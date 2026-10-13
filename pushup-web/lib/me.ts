import "server-only";
import { cookies } from "next/headers";
import { createAuthRealm } from "./auth-session";
import { DispatcherError, dispatcherFetch } from "./dispatcher";
import { SupabaseError, type FetchLike } from "./supabase-server";
import type { Me, WebResult } from "./me-view";

/**
 * Competitor web login (MESSAGING_PROVIDER=web_only fallback, SPEC §3 row 2): Supabase email OTP, sessions in
 * httpOnly cookies of the "user" realm (shared code with the admin console, lib/auth-session.ts).
 *
 * The site never decides who a competitor is: it forwards the user's own access token to the dispatcher's /web/*
 * endpoints, which verify it and map `sub` -> competitor. No user id is ever sent from here, so one login cannot
 * read or change another competitor's record. The dispatcher URL stays server-side.
 */

export const USER_REALM = createAuthRealm({
  accessCookie: "brodie_at",
  refreshCookie: "brodie_rt",
  nonceCookie: "brodie_login",
  path: "/",
  nonceContext: "brodie-user-login-nonce-v1",
  label: "me",
});

/** The competitor web flow is opt-in per deployment (NEXT_PUBLIC_WEB_JOIN=1). */
export function webJoinEnabled(): boolean {
  return process.env.NEXT_PUBLIC_WEB_JOIN === "1";
}

export async function currentAccessToken(): Promise<string | undefined> {
  return (await cookies()).get(USER_REALM.config.accessCookie)?.value || undefined;
}

export type MeFetch =
  | { status: "ok"; me: Me }
  | { status: "unauthenticated" }
  | { status: "error"; message: string };

/** GET /web/me for the signed-in user. 401 from the dispatcher (expired/invalid token) = unauthenticated. */
export async function fetchMe(accessToken: string | undefined, fetchImpl: FetchLike = fetch): Promise<MeFetch> {
  if (!accessToken) return { status: "unauthenticated" };
  try {
    const me = await dispatcherFetch<Me>("GET", "/web/me", { headers: bearer(accessToken), timeoutMs: 8_000 }, fetchImpl);
    return { status: "ok", me };
  } catch (e) {
    if (e instanceof DispatcherError && e.status === 401) return { status: "unauthenticated" };
    console.error("[me] status fetch failed", e instanceof Error ? e.message : e);
    return { status: "error", message: errorMessage(e) };
  }
}

function bearer(token: string): Record<string, string> {
  return { Authorization: `Bearer ${token}` };
}

/** POST a /web/* mutation as the signed-in user. */
export async function webPost(
  accessToken: string,
  path: "/web/join" | "/web/queue" | "/web/opt",
  body: Record<string, unknown>,
  fetchImpl: FetchLike = fetch,
): Promise<WebResult> {
  return dispatcherFetch<WebResult>("POST", path, { headers: bearer(accessToken), body, timeoutMs: 10_000 }, fetchImpl);
}

export function errorMessage(e: unknown): string {
  if (e instanceof DispatcherError) {
    if (e.status === 401) return "Your session expired. Sign in again.";
    if (e.status === 429) return "Slow down a sec, then try again.";
    if (e.status === 404) return "Web sign-up isn't open right now.";
    if (e.status === 409) return "Finish signing up first.";
    return "Couldn't reach the line right now. Try again in a moment.";
  }
  if (e instanceof SupabaseError) return "Sign-in service unavailable. Try again in a moment.";
  return "Something went wrong. Try again.";
}

export function parseLoginEmail(v: unknown): string | null {
  const s = (typeof v === "string" ? v : "").trim().toLowerCase();
  return s.length <= 254 && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s) ? s : null;
}
