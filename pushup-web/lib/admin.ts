import "server-only";
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";
import { cache } from "react";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import {
  SupabaseError,
  authGetUserEmail,
  serviceInsert,
  serviceSelect,
  type AuthSession,
  type FetchLike,
} from "./supabase-server";

// ------------------------------------------------------------------ session cookies

export const ACCESS_COOKIE = "brodie_admin_at";
export const REFRESH_COOKIE = "brodie_admin_rt";
const REFRESH_MAX_AGE_S = 60 * 60 * 24 * 7;

export function cookieOptions(maxAge: number) {
  return {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax" as const,
    path: "/admin",
    maxAge,
  };
}

export function sessionCookies(s: AuthSession, nowS = Math.floor(Date.now() / 1000)) {
  return [
    { name: ACCESS_COOKIE, value: s.accessToken, options: cookieOptions(Math.max(60, s.expiresAt - nowS)) },
    { name: REFRESH_COOKIE, value: s.refreshToken, options: cookieOptions(REFRESH_MAX_AGE_S) },
  ];
}

// ------------------------------------------------------------------ login nonce (binds a login to the browser that asked)

export const LOGIN_NONCE_COOKIE = "brodie_admin_login";
export const LOGIN_NONCE_TTL_S = 15 * 60;

/** HMAC key derived from a server-only secret; rotating the service key invalidates pending logins (fine). */
function nonceKey(): Buffer {
  const k = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!k) throw new SupabaseError("SUPABASE_SERVICE_ROLE_KEY is not set", 500, "config");
  return createHmac("sha256", k).update("brodie-admin-login-nonce-v1").digest();
}

function signNonce(payload: string): string {
  return createHmac("sha256", nonceKey()).update(payload).digest("base64url");
}

/**
 * Cookie set when a sign-in code is requested: base64url({e: email, n: random nonce, x: expiry}).HMAC.
 * Only a browser that requested the code for that email can complete the sign-in (blocks login CSRF).
 */
export function issueLoginNonce(email: string, nowS = Math.floor(Date.now() / 1000)) {
  const payload = Buffer.from(
    JSON.stringify({ e: email.trim().toLowerCase(), n: randomBytes(32).toString("base64url"), x: nowS + LOGIN_NONCE_TTL_S }),
  ).toString("base64url");
  return {
    name: LOGIN_NONCE_COOKIE,
    value: `${payload}.${signNonce(payload)}`,
    options: cookieOptions(LOGIN_NONCE_TTL_S),
  };
}

/** Email bound by a valid, unexpired login-nonce cookie, or null (missing, tampered, expired). */
export function loginNonceEmail(value: string | undefined, nowS = Math.floor(Date.now() / 1000)): string | null {
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
export function loginNonceMatches(value: string | undefined, email: string, nowS?: number): boolean {
  const bound = loginNonceEmail(value, nowS);
  return bound !== null && bound === email.trim().toLowerCase();
}

// ------------------------------------------------------------------ input validation

/** User-facing validation failure. Its message is safe to show in the UI. */
export class AdminInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AdminInputError";
  }
}

function str(v: unknown): string {
  return typeof v === "string" ? v : "";
}

export const REASON_MIN = 3;
export const REASON_MAX = 500;

/** Every mutating admin action requires a human reason; it is written to audit_log. */
export function requireReason(v: unknown): string {
  const r = str(v).replace(/\s+/g, " ").trim();
  if (r.length < REASON_MIN) throw new AdminInputError(`Reason is required (at least ${REASON_MIN} characters).`);
  if (r.length > REASON_MAX) throw new AdminInputError(`Reason is too long (max ${REASON_MAX} characters).`);
  return r;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseUuid(v: unknown, label = "User id"): string {
  const s = str(v).trim();
  if (!UUID_RE.test(s)) throw new AdminInputError(`${label} must be a UUID.`);
  return s.toLowerCase();
}

export function parsePoints(v: unknown): number {
  const s = str(v).trim();
  if (!/^[+-]?\d{1,6}$/.test(s)) throw new AdminInputError("Points must be a whole number.");
  const n = Number.parseInt(s, 10);
  if (n === 0) throw new AdminInputError("Points must be non-zero.");
  if (Math.abs(n) > 100_000) throw new AdminInputError("Points adjustment is out of range (max ±100000).");
  return n;
}

export function parseQueueId(v: unknown): number {
  const s = str(v).trim();
  if (!/^\d{1,15}$/.test(s) || Number(s) <= 0) throw new AdminInputError("Queue id must be a positive integer.");
  return Number(s);
}

export function parseCallId(v: unknown): string {
  const s = str(v).trim();
  if (!s || s.length > 200) throw new AdminInputError("Call id is required.");
  return s;
}

export function parseConfigKey(v: unknown): string {
  const s = str(v).trim();
  if (!/^[a-z][a-z0-9_]{0,63}$/.test(s)) throw new AdminInputError("Invalid config key.");
  return s;
}

export function parseJsonValue(v: unknown, label = "Value"): unknown {
  const s = str(v).trim();
  if (!s) throw new AdminInputError(`${label} is required (JSON).`);
  try {
    return JSON.parse(s) as unknown;
  } catch {
    throw new AdminInputError(`${label} is not valid JSON.`);
  }
}

export function parseOptionalJsonObject(v: unknown, label: string): Record<string, unknown> | undefined {
  if (!str(v).trim()) return undefined;
  const parsed = parseJsonValue(v, label);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new AdminInputError(`${label} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

export function parseText(v: unknown, label: string, max: number): string {
  const s = str(v).trim();
  if (!s) throw new AdminInputError(`${label} is required.`);
  if (s.length > max) throw new AdminInputError(`${label} is too long (max ${max} characters).`);
  return s;
}

export function parseEmail(v: unknown): string {
  const s = str(v).trim().toLowerCase();
  if (s.length > 254 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s)) throw new AdminInputError("Enter a valid email.");
  return s;
}

// ------------------------------------------------------------------ allowlist guard

export type AdminCheck =
  | { status: "ok"; email: string }
  | { status: "unauthenticated" }
  | { status: "forbidden"; email: string };

/** Exact (case-insensitive) membership in admin_allowlist. Reads the whole (tiny) table so LIKE wildcards never apply. */
export async function isAllowlisted(email: string, fetchImpl: FetchLike = fetch): Promise<boolean> {
  const target = email.trim().toLowerCase();
  if (!target) return false;
  const rows = await serviceSelect<{ email: string }>("admin_allowlist?select=email", fetchImpl);
  return rows.some((r) => typeof r.email === "string" && r.email.trim().toLowerCase() === target);
}

/**
 * Server-side admin check: the access token is validated by Supabase Auth (never decoded locally), then the email
 * must be in admin_allowlist. Network/config errors propagate (fail closed).
 */
export async function checkAdmin(accessToken: string | undefined, fetchImpl: FetchLike = fetch): Promise<AdminCheck> {
  if (!accessToken) return { status: "unauthenticated" };
  const email = await authGetUserEmail(accessToken, fetchImpl);
  if (!email) return { status: "unauthenticated" };
  return (await isAllowlisted(email, fetchImpl)) ? { status: "ok", email } : { status: "forbidden", email };
}

/** Per-request memoized check (layout + page share one Supabase round trip during a render). */
const currentCheck = cache(async (): Promise<AdminCheck> => {
  const store = await cookies();
  return checkAdmin(store.get(ACCESS_COOKIE)?.value);
});

/** For admin pages: redirect to login when not signed in, or to the forbidden notice when not allowlisted. */
export async function requireAdmin(): Promise<{ email: string }> {
  const res = await currentCheck();
  if (res.status === "unauthenticated") redirect("/admin/login");
  if (res.status === "forbidden") redirect("/admin/login?error=forbidden");
  return { email: res.email };
}

// ------------------------------------------------------------------ action plumbing

export type ActionResult = {
  ok: boolean;
  /** HTTP-like status for callers/tests: 200 ok, 400 bad input, 401/403 auth, 502 upstream, 500 internal. */
  status: number;
  message?: string;
  error?: string;
  data?: unknown;
};

export const IDLE: ActionResult = { ok: false, status: 0 };

const RPC_ERRORS: Record<string, string> = {
  reason_required: "Reason is required.",
  actor_required: "Actor is required.",
  points_required: "Points must be non-zero.",
  value_required: "Value is required.",
};

function upstreamMessage(e: SupabaseError | DispatcherError): string {
  const known = RPC_ERRORS[e.message];
  return known ?? `${e instanceof DispatcherError ? "Dispatcher" : "Database"} error (${e.status}): ${e.message}`;
}

/**
 * Wrap a server action body: re-verify the session + allowlist on every call, then map errors to a UI-safe result.
 * Unexpected errors are logged server-side and reported generically (never swallowed silently).
 */
export async function runAdminAction(
  fn: (admin: { email: string }) => Promise<Omit<ActionResult, "status"> & { status?: number }>,
  check: () => Promise<AdminCheck> = currentCheck,
): Promise<ActionResult> {
  let auth: AdminCheck;
  try {
    auth = await check();
  } catch (e) {
    console.error("[admin] auth check failed", e);
    return { ok: false, status: 503, error: "Could not verify admin session." };
  }
  if (auth.status === "unauthenticated") return { ok: false, status: 401, error: "Not signed in." };
  if (auth.status === "forbidden") return { ok: false, status: 403, error: "Forbidden: not on the admin allowlist." };
  try {
    const r = await fn({ email: auth.email });
    return { status: r.ok ? 200 : 400, ...r };
  } catch (e) {
    if (e instanceof AdminInputError) return { ok: false, status: 400, error: e.message };
    if (e instanceof SupabaseError || e instanceof DispatcherError) {
      console.error("[admin] upstream error", e.status, e.message);
      return { ok: false, status: e.status >= 500 ? 502 : 400, error: upstreamMessage(e) };
    }
    console.error("[admin] action failed", e);
    return { ok: false, status: 500, error: "Internal error; see server logs." };
  }
}

/** Interpret an RPC jsonb result of the shape {ok, reason?}. */
export function rpcOutcome(res: unknown, successMessage: string): Omit<ActionResult, "status"> {
  const r = (res ?? {}) as Record<string, unknown>;
  if (r.ok === true) return { ok: true, message: successMessage, data: res };
  return { ok: false, error: `Rejected: ${typeof r.reason === "string" ? r.reason : "unknown"}`, data: res };
}

export async function writeAudit(
  entry: { actor: string; action: string; target?: string | null; before?: unknown; after?: unknown; reason: string },
  fetchImpl: FetchLike = fetch,
): Promise<void> {
  await serviceInsert(
    "audit_log",
    {
      actor: entry.actor,
      action: entry.action,
      target: entry.target ?? null,
      before: entry.before ?? null,
      after: entry.after ?? null,
      reason: entry.reason,
    },
    fetchImpl,
  );
}

// ------------------------------------------------------------------ dispatcher admin endpoints

export class DispatcherError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "DispatcherError";
  }
}

function dispatcherBase(): { url: string; token: string } {
  const url = process.env.DISPATCHER_URL;
  const token = process.env.DISPATCHER_TOKEN;
  if (!url || !token) throw new DispatcherError("DISPATCHER_URL / DISPATCHER_TOKEN not set", 500);
  return { url: url.replace(/\/+$/, ""), token };
}

/** Call a dispatcher endpoint as the verified admin (X-Brodie-Token + X-Admin-Email per CONTRACTS §C4). */
export async function dispatcherRequest<T = unknown>(
  method: "GET" | "POST",
  path: string,
  opts: { email?: string; body?: unknown; reason?: string; timeoutMs?: number } = {},
  fetchImpl: FetchLike = fetch,
): Promise<T> {
  const { url, token } = dispatcherBase();
  const headers: Record<string, string> = { "X-Brodie-Token": token, Accept: "application/json" };
  if (opts.email) headers["X-Admin-Email"] = opts.email;
  if (opts.reason) headers["X-Admin-Reason"] = encodeURIComponent(opts.reason);
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetchImpl(`${url}${path}`, {
      method,
      headers,
      body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
      cache: "no-store",
      signal: AbortSignal.timeout(opts.timeoutMs ?? 30_000),
    });
  } catch (e) {
    throw new DispatcherError(e instanceof Error ? e.message : "request failed", 504);
  }
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text) as unknown;
    } catch {
      body = text;
    }
  }
  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? JSON.stringify((body as { detail: unknown }).detail) : "";
    throw new DispatcherError(detail || (typeof body === "string" && body ? body.slice(0, 300) : `HTTP ${res.status}`), res.status);
  }
  return body as T;
}

// ------------------------------------------------------------------ time (America/New_York day logic)

const ET = "America/New_York";

/** YYYY-MM-DD of the ET calendar day containing `ms`. */
export function etDate(ms: number): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: ET, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    new Date(ms),
  );
}

function etHour(ms: number): number {
  return Number(
    new Intl.DateTimeFormat("en-US", { timeZone: ET, hour: "2-digit", hourCycle: "h23" }).format(new Date(ms)),
  );
}

/** UTC instant of 00:00 ET on `date` (YYYY-MM-DD). ET is UTC-4 or UTC-5; midnight never falls in a DST gap. */
export function etMidnightUtc(date: string): Date {
  const [y, m, d] = date.split("-").map(Number);
  for (const off of [4, 5]) {
    const ms = Date.UTC(y, m - 1, d, off);
    if (etHour(ms) === 0 && etDate(ms) === date) return new Date(ms);
  }
  throw new Error(`cannot resolve ET midnight for ${date}`);
}

/** [start, end) UTC bounds of the ET day before the one containing `nowMs`. */
export function etYesterday(nowMs: number): { date: string; start: Date; end: Date } {
  const today = etDate(nowMs);
  const end = etMidnightUtc(today);
  const date = etDate(end.getTime() - 1);
  return { date, start: etMidnightUtc(date), end };
}
