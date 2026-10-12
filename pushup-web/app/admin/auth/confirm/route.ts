import { NextResponse, type NextRequest } from "next/server";
import { LOGIN_NONCE_COOKIE, cookieOptions, isAllowlisted, loginNonceEmail, sessionCookies } from "@/lib/admin";
import { authLogout, authVerifyOtp } from "@/lib/supabase-server";

/**
 * Magic-link landing: configure the Supabase email template link as
 *   {{ .SiteURL }}/admin/auth/confirm?token_hash={{ .TokenHash }}&type=email
 *
 * GET never spends the token (email link scanners prefetch links); it renders a button that POSTs it back.
 * POST requires a same-origin request AND the login-nonce cookie set by "Email me a code" in this browser, bound to
 * the same email the token belongs to (blocks login CSRF). Only then is the token verified and a session set.
 */

const TOKEN_RE = /^[A-Za-z0-9_-]{8,256}$/;

function linkType(v: unknown): "email" | "magiclink" {
  return v === "magiclink" ? "magiclink" : "email";
}

function fail(req: NextRequest, code: "link" | "forbidden") {
  // 303: the browser follows with GET after a POST.
  return NextResponse.redirect(new URL(`/admin/login?error=${code}`, req.nextUrl.origin), 303);
}

const PAGE_HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
};

export async function GET(req: NextRequest) {
  const tokenHash = req.nextUrl.searchParams.get("token_hash") ?? "";
  if (!TOKEN_RE.test(tokenHash)) return fail(req, "link");
  const type = linkType(req.nextUrl.searchParams.get("type"));
  // tokenHash and type are restricted to [A-Za-z0-9_-], so they are safe to interpolate into HTML attributes.
  const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>Confirm admin sign-in</title></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0b;color:#f5f5f4;font-family:system-ui,sans-serif">
<form method="post" action="/admin/auth/confirm" style="padding:24px;border:1px solid rgba(255,255,255,.12);border-radius:12px;background:#151517;max-width:22rem">
<h1 style="margin:0 0 8px;font:700 22px Impact,'Arial Narrow Bold',sans-serif;text-transform:uppercase;color:#d4ff3a">Admin sign-in</h1>
<p style="margin:0 0 16px;font-size:14px;color:#b4b4b0">Finish signing in from the same browser where you requested the code.</p>
<input type="hidden" name="token_hash" value="${tokenHash}"><input type="hidden" name="type" value="${type}">
<button type="submit" style="border:0;border-radius:6px;padding:8px 14px;background:#d4ff3a;color:#0a0a0b;font-weight:700;cursor:pointer">Confirm sign-in</button>
</form></body></html>`;
  return new Response(html, { status: 200, headers: PAGE_HEADERS });
}

/** Same-origin check: Origin must match this host; without Origin, require Sec-Fetch-Site: same-origin. */
function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (origin) return origin === req.nextUrl.origin;
  return req.headers.get("sec-fetch-site") === "same-origin";
}

export async function POST(req: NextRequest) {
  if (!sameOrigin(req)) return fail(req, "link");
  let fd: FormData;
  try {
    fd = await req.formData();
  } catch {
    return fail(req, "link");
  }
  const tokenHash = fd.get("token_hash");
  if (typeof tokenHash !== "string" || !TOKEN_RE.test(tokenHash)) return fail(req, "link");
  const boundEmail = loginNonceEmail(req.cookies.get(LOGIN_NONCE_COOKIE)?.value);
  // No valid nonce: this browser did not request the code. Reject without spending the token.
  if (!boundEmail) return fail(req, "link");

  let session;
  try {
    session = await authVerifyOtp({ tokenHash, type: linkType(fd.get("type")) });
  } catch (e) {
    console.error("[admin] magic link verify failed", e instanceof Error ? e.message : e);
    return fail(req, "link");
  }
  if (!session.email || session.email !== boundEmail) {
    await authLogout(session.accessToken).catch((e) => console.error("[admin] logout failed", e));
    return fail(req, "link");
  }
  let allowed: boolean;
  try {
    allowed = await isAllowlisted(session.email);
  } catch (e) {
    console.error("[admin] allowlist check failed", e);
    await authLogout(session.accessToken).catch((err) => console.error("[admin] logout failed", err));
    return fail(req, "link");
  }
  if (!allowed) {
    await authLogout(session.accessToken).catch((e) => console.error("[admin] logout failed", e));
    return fail(req, "forbidden");
  }
  const res = NextResponse.redirect(new URL("/admin", req.nextUrl.origin), 303);
  for (const c of sessionCookies(session)) res.cookies.set(c.name, c.value, c.options);
  res.cookies.set(LOGIN_NONCE_COOKIE, "", cookieOptions(0));
  return res;
}
