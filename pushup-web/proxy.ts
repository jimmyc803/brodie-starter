import { NextResponse, type NextRequest } from "next/server";
import { ACCESS_COOKIE, REFRESH_COOKIE, cookieOptions, sessionCookies } from "@/lib/admin";
import { SupabaseError, authRefresh } from "@/lib/supabase-server";

/**
 * Admin session refresh only (not authorization): when the access-token cookie is missing or about to expire and a
 * refresh token exists, rotate the session and forward the fresh cookies to both the browser and this request, so
 * Server Components (which cannot set cookies) see a valid token. Every page/action still verifies the token with
 * Supabase Auth and checks admin_allowlist itself.
 */

const REFRESH_SKEW_S = 60;

/** Unverified read of the JWT `exp` claim, used only to decide whether to refresh. */
function tokenExp(jwt: string): number | null {
  const part = jwt.split(".")[1];
  if (!part) return null;
  try {
    const json = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { exp?: unknown };
    return typeof json.exp === "number" ? json.exp : null;
  } catch {
    return null;
  }
}

export async function proxy(req: NextRequest) {
  const refreshToken = req.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) return NextResponse.next();
  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  const exp = access ? tokenExp(access) : null;
  if (access && exp !== null && exp - Math.floor(Date.now() / 1000) > REFRESH_SKEW_S) return NextResponse.next();

  try {
    const session = await authRefresh(refreshToken);
    const cookies = sessionCookies(session);
    for (const c of cookies) req.cookies.set(c.name, c.value);
    const res = NextResponse.next({ request: { headers: req.headers } });
    for (const c of cookies) res.cookies.set(c.name, c.value, c.options);
    return res;
  } catch (e) {
    if (e instanceof SupabaseError && e.status >= 400 && e.status < 500) {
      // Refresh token revoked/expired/reused: drop the session so the page redirects to login.
      req.cookies.delete(ACCESS_COOKIE);
      req.cookies.delete(REFRESH_COOKIE);
      const res = NextResponse.next({ request: { headers: req.headers } });
      res.cookies.set(ACCESS_COOKIE, "", cookieOptions(0));
      res.cookies.set(REFRESH_COOKIE, "", cookieOptions(0));
      return res;
    }
    // Transient (network/5xx): keep cookies; the page's own check decides access.
    console.error("[admin] session refresh failed", e instanceof Error ? e.message : e);
    return NextResponse.next();
  }
}

export const config = {
  matcher: ["/admin/:path*"],
};
