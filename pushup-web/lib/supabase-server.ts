import "server-only";

/**
 * Server-only Supabase access for the admin console.
 *
 * - Auth (GoTrue) calls use the public anon key; they are what @supabase/ssr does under the hood, done directly so the
 *   session lives only in httpOnly cookies set by the server (no token is ever readable by browser JS).
 * - Data calls use SUPABASE_SERVICE_ROLE_KEY, which must never be NEXT_PUBLIC_* and is only read here.
 *
 * Every function takes an optional `fetchImpl` so tests can stub the network.
 */

export type FetchLike = typeof fetch;

export class SupabaseError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "SupabaseError";
  }
}

export type AuthSession = {
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // epoch seconds
  email: string | null;
};

function supabaseUrl(): string {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  if (!url) throw new SupabaseError("NEXT_PUBLIC_SUPABASE_URL is not set", 500, "config");
  return url.replace(/\/+$/, "");
}

function anonKey(): string {
  const key = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!key) throw new SupabaseError("NEXT_PUBLIC_SUPABASE_ANON_KEY is not set", 500, "config");
  return key;
}

function serviceKey(): string {
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!key) throw new SupabaseError("SUPABASE_SERVICE_ROLE_KEY is not set", 500, "config");
  return key;
}

async function readJson(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function errorFrom(status: number, body: unknown): SupabaseError {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    const msg = [b.message, b.msg, b.error_description, b.error].find((v) => typeof v === "string") as
      | string
      | undefined;
    // GoTrue: {code: <http int>, error_code: "refresh_token_not_found", msg} or legacy {error: "invalid_grant", ...}.
    const code = [b.error_code, b.code, b.error].find((v) => typeof v === "string") as string | undefined;
    return new SupabaseError(msg ?? `HTTP ${status}`, status, code);
  }
  return new SupabaseError(typeof body === "string" && body ? body.slice(0, 300) : `HTTP ${status}`, status);
}

// ------------------------------------------------------------------ service-role data access

function serviceHeaders(extra?: Record<string, string>): Record<string, string> {
  const key = serviceKey();
  return { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json", ...extra };
}

/** POST /rest/v1/rpc/{fn} with the service role. Returns decoded jsonb. Throws SupabaseError on non-2xx. */
export async function serviceRpc<T = unknown>(
  fn: string,
  args: Record<string, unknown>,
  fetchImpl: FetchLike = fetch,
): Promise<T> {
  if (!/^[a-z_][a-z0-9_]*$/.test(fn)) throw new SupabaseError(`bad rpc name ${fn}`, 400);
  const res = await fetchImpl(`${supabaseUrl()}/rest/v1/rpc/${fn}`, {
    method: "POST",
    headers: serviceHeaders(),
    body: JSON.stringify(args),
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  return body as T;
}

/** GET /rest/v1/{pathAndQuery} with the service role. Caller is responsible for encoding query values. */
export async function serviceSelect<T = Record<string, unknown>>(
  pathAndQuery: string,
  fetchImpl: FetchLike = fetch,
): Promise<T[]> {
  const res = await fetchImpl(`${supabaseUrl()}/rest/v1/${pathAndQuery}`, {
    headers: serviceHeaders(),
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  return Array.isArray(body) ? (body as T[]) : [];
}

/** INSERT one row into a table with the service role. */
export async function serviceInsert(
  table: string,
  row: Record<string, unknown>,
  fetchImpl: FetchLike = fetch,
): Promise<void> {
  const res = await fetchImpl(`${supabaseUrl()}/rest/v1/${table}`, {
    method: "POST",
    headers: serviceHeaders({ Prefer: "return=minimal" }),
    body: JSON.stringify(row),
    cache: "no-store",
  });
  if (!res.ok) throw errorFrom(res.status, await readJson(res));
}

// ------------------------------------------------------------------ auth (GoTrue REST, anon key)

function authHeaders(accessToken?: string): Record<string, string> {
  const key = anonKey();
  return {
    apikey: key,
    Authorization: `Bearer ${accessToken ?? key}`,
    "Content-Type": "application/json",
  };
}

function toSession(body: unknown): AuthSession {
  const b = (body ?? {}) as Record<string, unknown>;
  const access = b.access_token;
  const refresh = b.refresh_token;
  if (typeof access !== "string" || typeof refresh !== "string") {
    throw new SupabaseError("auth response missing tokens", 502);
  }
  const now = Math.floor(Date.now() / 1000);
  const expiresAt =
    typeof b.expires_at === "number"
      ? b.expires_at
      : now + (typeof b.expires_in === "number" ? b.expires_in : 3600);
  const user = (b.user ?? {}) as Record<string, unknown>;
  return {
    accessToken: access,
    refreshToken: refresh,
    expiresAt,
    email: typeof user.email === "string" ? user.email.toLowerCase() : null,
  };
}

/**
 * Send an email OTP / magic link. create_user lets a first-time user (or newly allowlisted admin) sign in.
 * `redirectTo` becomes {{ .RedirectTo }} in the email template (must be in the project's allowed redirect URLs), so one
 * template serves every realm: `{{ .RedirectTo }}?token_hash={{ .TokenHash }}&type=email` plus the {{ .Token }} code.
 */
export async function authSendOtp(email: string, fetchImpl: FetchLike = fetch, redirectTo?: string): Promise<void> {
  const qs = redirectTo ? `?redirect_to=${encodeURIComponent(redirectTo)}` : "";
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/otp${qs}`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ email, create_user: true }),
    cache: "no-store",
  });
  if (!res.ok) throw errorFrom(res.status, await readJson(res));
}

/** Verify a 6-digit email code (`token` + `email`) or a magic-link `token_hash`. */
export async function authVerifyOtp(
  params: { email: string; token: string } | { tokenHash: string; type: "email" | "magiclink" },
  fetchImpl: FetchLike = fetch,
): Promise<AuthSession> {
  const payload =
    "tokenHash" in params
      ? { type: params.type, token_hash: params.tokenHash }
      : { type: "email", email: params.email, token: params.token };
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/verify`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  return toSession(body);
}

/** Email + password sign-in (no email is sent; passwords are set by scripts/set_admin_password.py). */
export async function authPasswordSignIn(email: string, password: string, fetchImpl: FetchLike = fetch): Promise<AuthSession> {
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/token?grant_type=password`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  return toSession(body);
}

export async function authRefresh(refreshToken: string, fetchImpl: FetchLike = fetch): Promise<AuthSession> {
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/token?grant_type=refresh_token`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ refresh_token: refreshToken }),
    cache: "no-store",
  });
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  return toSession(body);
}

/**
 * Validate an access token with Supabase Auth (server-side; signature + expiry + revocation are checked by GoTrue).
 * Returns the user's lowercased email, or null if the token is not valid.
 */
export async function authGetUserEmail(accessToken: string, fetchImpl: FetchLike = fetch): Promise<string | null> {
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/user`, {
    headers: authHeaders(accessToken),
    cache: "no-store",
  });
  if (res.status === 401 || res.status === 403) return null;
  const body = await readJson(res);
  if (!res.ok) throw errorFrom(res.status, body);
  const email = (body as Record<string, unknown> | null)?.email;
  return typeof email === "string" && email ? email.toLowerCase() : null;
}

export async function authLogout(accessToken: string, fetchImpl: FetchLike = fetch): Promise<void> {
  const res = await fetchImpl(`${supabaseUrl()}/auth/v1/logout?scope=local`, {
    method: "POST",
    headers: authHeaders(accessToken),
    cache: "no-store",
  });
  // 401/403/404: token already invalid, which is the desired end state.
  if (!res.ok && ![401, 403, 404].includes(res.status)) throw errorFrom(res.status, await readJson(res));
}

/** GoTrue error codes that mean the refresh token / session is definitively gone (not a race, limit or outage). */
const DEAD_SESSION_CODES = new Set(["refresh_token_not_found", "session_not_found", "session_expired", "invalid_grant"]);

/**
 * Whether a refresh failure means the stored session can never work again, so its cookies should be dropped.
 * 429, 5xx, network errors and "already used" (a concurrent refresh won the race) are NOT definitive.
 */
export function isDeadSessionError(e: unknown): boolean {
  if (!(e instanceof SupabaseError)) return false;
  if (e.status !== 400 && e.status !== 401) return false;
  if (!e.code || !DEAD_SESSION_CODES.has(e.code)) return false;
  return !/already used/i.test(e.message);
}
