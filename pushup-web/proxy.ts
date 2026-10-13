import type { NextRequest } from "next/server";
import { ADMIN_REALM } from "@/lib/admin";
import { USER_REALM } from "@/lib/me";

/**
 * Session refresh only (not authorization), for the admin console and the competitor /me area: when the access-token
 * cookie is missing or about to expire and a refresh token exists, rotate the session and forward the fresh cookies to
 * both the browser and this request, so Server Components (which cannot set cookies) see a valid token. Every page,
 * action and route still verifies the token itself (admin: Supabase Auth + allowlist; /me: the dispatcher).
 * Shared logic: lib/auth-session.ts.
 */
export async function proxy(req: NextRequest) {
  const realm = req.nextUrl.pathname.startsWith("/admin") ? ADMIN_REALM : USER_REALM;
  return realm.refreshSession(req);
}

export const config = {
  matcher: ["/admin/:path*", "/me/:path*", "/login/:path*"],
};
