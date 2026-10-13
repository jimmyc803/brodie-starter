import "server-only";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { NextResponse, type NextRequest } from "next/server";
import {
  SupabaseError,
  authLogout,
  authRefresh,
  authVerifyOtp,
  isDeadSessionError,
  type AuthSession,
} from "./supabase-server";

/**
 * Shared Supabase email-OTP session plumbing for every signed-in area of the site (admin console, competitor /me).
 * Each area is a "realm" with its own cookie names, cookie path and nonce HMAC context, so a session or a pending
 * login from one realm can never be replayed in another.
 *
 * - Sessions live only in httpOnly cookies set by the server (no token is ever readable by browser JS).
 * - Login CSRF: requesting a code sets an HMAC-signed nonce cookie bound to the email; a code or magic link only
 *   completes in the browser holding it, and only if the verified session's email matches.
 * - Magic links: GET never spends the token (link scanners prefetch); a same-origin POST does.
 * - Refresh (proxy): rotates near-expiry sessions; drops cookies only on definitively dead refresh tokens.
 */

export type RealmConfig = {
  accessCookie: string;
  refreshCookie: string;
  nonceCookie: string;
  /** Cookie path; every page, action and route handler of the realm must live under it. */
  path: string;
  /** Domain-separation string for the login-nonce HMAC key. */
  nonceContext: string;
  /** Log prefix, e.g. "admin". */
  label: string;
};

export type CookieOptions = {
  httpOnly: true;
  secure: boolean;
  sameSite: "lax";
  path: string;
  maxAge: number;
};

export type CookieSpec = { name: string; value: string; options: CookieOptions };

export type SignInResult =
  | { ok: true; session: AuthSession }
  | { ok: false; status: number; error: string };

export const LOGIN_NONCE_TTL_S = 15 * 60;
const REFRESH_MAX_AGE_S = 60 * 60 * 24 * 7;
const REFRESH_SKEW_S = 60;
const TOKEN_RE = /^[A-Za-z0-9_-]{8,256}$/;

/** Unverified read of the JWT `exp` claim, used only to decide whether to refresh. */
export function tokenExp(jwt: string): number | null {
  const part = jwt.split(".")[1];
  if (!part) return null;
  try {
    const json = JSON.parse(Buffer.from(part, "base64url").toString("utf8")) as { exp?: unknown };
    return typeof json.exp === "number" ? json.exp : null;
  } catch {
    return null;
  }
}

/** Same-origin check: Origin must match this host; without Origin, require Sec-Fetch-Site: same-origin. */
export function sameOrigin(req: NextRequest): boolean {
  const origin = req.headers.get("origin");
  if (origin) return origin === req.nextUrl.origin;
  return req.headers.get("sec-fetch-site") === "same-origin";
}

function linkType(v: unknown): "email" | "magiclink" {
  return v === "magiclink" ? "magiclink" : "email";
}

const PAGE_HEADERS = {
  "Content-Type": "text/html; charset=utf-8",
  "Cache-Control": "no-store",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
};

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

export function createAuthRealm(cfg: RealmConfig) {
  function cookieOptions(maxAge: number): CookieOptions {
    return { httpOnly: true, secure: process.env.NODE_ENV === "production", sameSite: "lax", path: cfg.path, maxAge };
  }

  function sessionCookies(s: AuthSession, nowS = Math.floor(Date.now() / 1000)): CookieSpec[] {
    return [
      { name: cfg.accessCookie, value: s.accessToken, options: cookieOptions(Math.max(60, s.expiresAt - nowS)) },
      { name: cfg.refreshCookie, value: s.refreshToken, options: cookieOptions(REFRESH_MAX_AGE_S) },
    ];
  }

  function clearedCookies(): CookieSpec[] {
    return [
      { name: cfg.accessCookie, value: "", options: cookieOptions(0) },
      { name: cfg.refreshCookie, value: "", options: cookieOptions(0) },
    ];
  }

  /** HMAC key derived from a server-only secret; rotating the service key invalidates pending logins (fine). */
  function nonceKey(): Buffer {
    const k = process.env.SUPABASE_SERVICE_ROLE_KEY;
    if (!k) throw new SupabaseError("SUPABASE_SERVICE_ROLE_KEY is not set", 500, "config");
    return createHmac("sha256", k).update(cfg.nonceContext).digest();
  }

  function signNonce(payload: string): string {
    return createHmac("sha256", nonceKey()).update(payload).digest("base64url");
  }

  /**
   * Cookie set when a sign-in code is requested: base64url({e: email, n: random nonce, x: expiry}).HMAC.
   * Only a browser that requested the code for that email can complete the sign-in (blocks login CSRF).
   */
  function issueLoginNonce(email: string, nowS = Math.floor(Date.now() / 1000)): CookieSpec {
    const payload = Buffer.from(
      JSON.stringify({ e: email.trim().toLowerCase(), n: randomBytes(32).toString("base64url"), x: nowS + LOGIN_NONCE_TTL_S }),
    ).toString("base64url");
    return { name: cfg.nonceCookie, value: `${payload}.${signNonce(payload)}`, options: cookieOptions(LOGIN_NONCE_TTL_S) };
  }

  /** Email bound by a valid, unexpired login-nonce cookie, or null (missing, tampered, expired). */
  function loginNonceEmail(value: string | undefined, nowS = Math.floor(Date.now() / 1000)): string | null {
    if (!value) return null;
    const [payload, sig, extra] = value.split(".");
    if (!payload || !sig || extra !== undefined) return null;
    const want = Buffer.from(signNonce(payload));
    const got = Buffer.from(sig);
    if (want.length !== got.length || !timingSafeEqual(want, got)) return null;
    try {
      const p = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as { e?: unknown; n?: unknown; x?: unknown };
      if (typeof p.e !== "string" || typeof p.n !== "string" || typeof p.x !== "number" || p.x <= nowS) return null;
      return p.e;
    } catch {
      return null;
    }
  }

  /** True iff the nonce cookie is valid and bound to `email` (case-insensitive). */
  function loginNonceMatches(value: string | undefined, email: string, nowS?: number): boolean {
    const bound = loginNonceEmail(value, nowS);
    return bound !== null && bound === email.trim().toLowerCase();
  }

  async function logoutQuietly(accessToken: string): Promise<void> {
    await authLogout(accessToken).catch((e) => console.error(`[${cfg.label}] logout failed`, e));
  }

  /**
   * Complete a 6-digit-code sign-in. The nonce is checked BEFORE the code is spent, so a rejected attempt does not
   * burn it; a verified session whose email differs from the requested one is logged out (fail closed).
   * Authorization (allowlists etc.) is the caller's job.
   */
  async function signInWithCode(email: string, code: string, nonceValue: string | undefined): Promise<SignInResult> {
    if (!loginNonceMatches(nonceValue, email)) {
      return {
        ok: false,
        status: 403,
        error: "Sign-in must be completed in the browser that requested the code (within 15 min). Request a new code.",
      };
    }
    let session: AuthSession;
    try {
      session = await authVerifyOtp({ email, token: code });
    } catch (e) {
      console.error(`[${cfg.label}] verify failed`, e instanceof SupabaseError ? `${e.status} ${e.message}` : e);
      return { ok: false, status: 401, error: "Code is invalid or expired." };
    }
    if (!session.email || session.email !== email.trim().toLowerCase()) {
      await logoutQuietly(session.accessToken);
      return { ok: false, status: 403, error: "Forbidden: sign-in email could not be verified." };
    }
    return { ok: true, session };
  }

  /** Proxy step: refresh a missing/near-expiry access token and forward fresh cookies to the browser AND this request. */
  async function refreshSession(req: NextRequest): Promise<NextResponse> {
    const refreshToken = req.cookies.get(cfg.refreshCookie)?.value;
    if (!refreshToken) return NextResponse.next();
    const access = req.cookies.get(cfg.accessCookie)?.value;
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
      if (isDeadSessionError(e)) {
        // Refresh token definitively invalid/revoked: drop the session so the page redirects to login.
        req.cookies.delete(cfg.accessCookie);
        req.cookies.delete(cfg.refreshCookie);
        const res = NextResponse.next({ request: { headers: req.headers } });
        for (const c of clearedCookies()) res.cookies.set(c.name, c.value, c.options);
        return res;
      }
      // Rate limit, concurrent-refresh race, 5xx or network: keep cookies; the page's own check decides access.
      console.error(`[${cfg.label}] session refresh failed`, e instanceof Error ? e.message : e);
      return NextResponse.next();
    }
  }

  /**
   * Magic-link landing route ({GET, POST}). GET renders a button that POSTs the token back; POST requires a
   * same-origin request AND this realm's login-nonce cookie bound to the token's email, then `authorize`.
   */
  function confirmRoute(opts: {
    action: string;
    loginPath: string;
    successPath: string;
    heading: string;
    authorize?: (email: string) => Promise<"ok" | "forbidden">;
  }) {
    const fail = (req: NextRequest, code: "link" | "forbidden") =>
      // 303: the browser follows with GET after a POST.
      NextResponse.redirect(new URL(`${opts.loginPath}?error=${code}`, req.nextUrl.origin), 303);

    async function GET(req: NextRequest) {
      const tokenHash = req.nextUrl.searchParams.get("token_hash") ?? "";
      if (!TOKEN_RE.test(tokenHash)) return fail(req, "link");
      const type = linkType(req.nextUrl.searchParams.get("type"));
      // tokenHash and type are restricted to [A-Za-z0-9_-], so they are safe to interpolate into HTML attributes.
      const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>${escapeHtml(opts.heading)}</title></head>
<body style="margin:0;min-height:100vh;display:grid;place-items:center;background:#0a0a0b;color:#f5f5f4;font-family:system-ui,sans-serif">
<form method="post" action="${escapeHtml(opts.action)}" style="padding:24px;border:1px solid rgba(255,255,255,.12);border-radius:12px;background:#151517;max-width:22rem">
<h1 style="margin:0 0 8px;font:700 22px Impact,'Arial Narrow Bold',sans-serif;text-transform:uppercase;color:#d4ff3a">${escapeHtml(opts.heading)}</h1>
<p style="margin:0 0 16px;font-size:14px;color:#b4b4b0">Finish signing in from the same browser where you requested the code.</p>
<input type="hidden" name="token_hash" value="${tokenHash}"><input type="hidden" name="type" value="${type}">
<button type="submit" style="border:0;border-radius:6px;padding:8px 14px;background:#d4ff3a;color:#0a0b05;font-weight:700;cursor:pointer">Confirm sign-in</button>
</form></body></html>`;
      return new Response(html, { status: 200, headers: PAGE_HEADERS });
    }

    async function POST(req: NextRequest) {
      if (!sameOrigin(req)) return fail(req, "link");
      let fd: FormData;
      try {
        fd = await req.formData();
      } catch {
        return fail(req, "link");
      }
      const tokenHash = fd.get("token_hash");
      if (typeof tokenHash !== "string" || !TOKEN_RE.test(tokenHash)) return fail(req, "link");
      const boundEmail = loginNonceEmail(req.cookies.get(cfg.nonceCookie)?.value);
      // No valid nonce: this browser did not request the code. Reject without spending the token.
      if (!boundEmail) return fail(req, "link");

      let session: AuthSession;
      try {
        session = await authVerifyOtp({ tokenHash, type: linkType(fd.get("type")) });
      } catch (e) {
        console.error(`[${cfg.label}] magic link verify failed`, e instanceof Error ? e.message : e);
        return fail(req, "link");
      }
      if (!session.email || session.email !== boundEmail) {
        await logoutQuietly(session.accessToken);
        return fail(req, "link");
      }
      if (opts.authorize) {
        let verdict: "ok" | "forbidden";
        try {
          verdict = await opts.authorize(session.email);
        } catch (e) {
          console.error(`[${cfg.label}] authorization check failed`, e);
          await logoutQuietly(session.accessToken);
          return fail(req, "link");
        }
        if (verdict !== "ok") {
          await logoutQuietly(session.accessToken);
          return fail(req, "forbidden");
        }
      }
      const res = NextResponse.redirect(new URL(opts.successPath, req.nextUrl.origin), 303);
      for (const c of sessionCookies(session)) res.cookies.set(c.name, c.value, c.options);
      res.cookies.set(cfg.nonceCookie, "", cookieOptions(0));
      return res;
    }

    return { GET, POST };
  }

  return {
    config: cfg,
    cookieOptions,
    sessionCookies,
    clearedCookies,
    issueLoginNonce,
    loginNonceEmail,
    loginNonceMatches,
    logoutQuietly,
    signInWithCode,
    refreshSession,
    confirmRoute,
  };
}

export type AuthRealm = ReturnType<typeof createAuthRealm>;

/** Absolute magic-link landing URL from the configured site origin (never from the request Host header). */
export function siteRedirect(path: string): string | undefined {
  const site = process.env.NEXT_PUBLIC_SITE_URL;
  if (!site) return undefined;
  try {
    return new URL(path, site).toString();
  } catch {
    return undefined;
  }
}
