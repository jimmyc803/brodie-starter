import { NextResponse, type NextRequest } from "next/server";
import { isAllowlisted, sessionCookies } from "@/lib/admin";
import { authLogout, authVerifyOtp } from "@/lib/supabase-server";

/**
 * Magic-link landing: configure the Supabase email template link as
 *   {{ .SiteURL }}/admin/auth/confirm?token_hash={{ .TokenHash }}&type=email
 * Verifies the one-time token server-side, enforces the allowlist, then sets httpOnly session cookies.
 */
export async function GET(req: NextRequest) {
  const url = req.nextUrl;
  const tokenHash = url.searchParams.get("token_hash") ?? "";
  const typeParam = url.searchParams.get("type");
  const type = typeParam === "magiclink" ? "magiclink" : "email";
  const fail = (code: string) => NextResponse.redirect(new URL(`/admin/login?error=${code}`, url.origin));

  if (!/^[A-Za-z0-9_-]{8,256}$/.test(tokenHash)) return fail("link");
  let session;
  try {
    session = await authVerifyOtp({ tokenHash, type });
  } catch (e) {
    console.error("[admin] magic link verify failed", e instanceof Error ? e.message : e);
    return fail("link");
  }
  let allowed = false;
  try {
    allowed = !!session.email && (await isAllowlisted(session.email));
  } catch (e) {
    console.error("[admin] allowlist check failed", e);
    return fail("link");
  }
  if (!allowed) {
    await authLogout(session.accessToken).catch((e) => console.error("[admin] logout failed", e));
    return fail("forbidden");
  }
  const res = NextResponse.redirect(new URL("/admin", url.origin));
  for (const c of sessionCookies(session)) res.cookies.set(c.name, c.value, c.options);
  return res;
}
