import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Next/server-only shims: the modules under test are real; only framework I/O is faked.
vi.mock("server-only", () => ({}));
const cookieJar = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (cookieJar.has(name) ? { name, value: cookieJar.get(name) } : undefined),
    set: (name: string, value: string, opts?: { maxAge?: number }) =>
      void (opts?.maxAge === 0 ? cookieJar.delete(name) : cookieJar.set(name, value)),
  }),
}));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
  notFound: () => {
    throw new Error("NOT_FOUND");
  },
}));
vi.mock("next/cache", () => ({ refresh: vi.fn() }));

import { NextRequest } from "next/server";
import { ADMIN_REALM } from "@/lib/admin";
import { USER_REALM, fetchMe } from "@/lib/me";
import {
  claimSecondsLeft,
  facetimeLink,
  formatClock,
  formatEtaRange,
  mePhase,
  type RegisteredMe,
} from "@/lib/me-view";
import { sendCode, verifyCode } from "@/app/login/actions";
import { POST as confirmPost } from "@/app/login/confirm/route";
import { joinChallenge, queueAction, setTexts, signOutUser } from "@/app/me/actions";
import { GET as statusGet } from "@/app/me/status/route";
import { proxy } from "@/proxy";

const SUPA = "https://proj.supabase.test";
const DISP = "https://dispatcher.test";
const AT = USER_REALM.config.accessCookie;
const RT = USER_REALM.config.refreshCookie;
const NONCE = USER_REALM.config.nonceCookie;

type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };
let calls: Call[] = [];
let refreshReply: { status: number; body: unknown } = { status: 200, body: {} };

const ME: RegisteredMe = {
  registered: true,
  email: "ana@example.com",
  display_name: "Ana_W",
  handle: "+15550100001",
  points: 42,
  points_today: 12,
  valid_reps: 40,
  rank: 3,
  total_users: 20,
  calls_today: 1,
  calls_left: 4,
  daily_call_cap: 5,
  streak: 2,
  avatar_level: 2,
  opted_out: false,
  banned: false,
  queue: { status: "waiting", position: 2, eta: { lo_min: 5, hi_min: 10 } },
  claim: null,
  in_call: false,
  line_open: false,
  brodie_number: "+1 (555) 000-1111",
  started: true,
  frozen: false,
};

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const headers = Object.fromEntries(Object.entries((init?.headers ?? {}) as Record<string, string>));
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  calls.push({ url, method: init?.method ?? "GET", headers, body });
  const json = (status: number, v: unknown) =>
    Promise.resolve(new Response(JSON.stringify(v), { status, headers: { "content-type": "application/json" } }));
  if (url.startsWith(`${SUPA}/auth/v1/otp`)) return json(200, {});
  if (url === `${SUPA}/auth/v1/verify`) {
    const b = body as Record<string, string>;
    const email = b.token_hash === "hash-ana-00001" ? "ana@example.com" : b.token === "123456" ? b.email : undefined;
    if (!email) return json(403, { error_code: "otp_expired", msg: "Token has expired or is invalid" });
    return json(200, { access_token: "user-at", refresh_token: "user-rt", expires_in: 3600, user: { id: "u1", email } });
  }
  if (url.startsWith(`${SUPA}/auth/v1/logout`)) return Promise.resolve(new Response(null, { status: 204 }));
  if (url === `${SUPA}/auth/v1/token?grant_type=refresh_token`) return json(refreshReply.status, refreshReply.body);
  if (url.startsWith(DISP)) {
    if ("X-Brodie-Token" in headers) return json(500, { detail: "dispatcher token must never be sent on /web" });
    if (headers.Authorization !== "Bearer user-at") return json(401, { detail: "invalid token" });
    if (url === `${DISP}/web/me`) return json(200, ME);
    if (url === `${DISP}/web/queue`) return json(200, { ok: true, reason: "ok", me: ME });
    if (url === `${DISP}/web/opt`) return json(200, { ok: true, reason: "ok", me: { ...ME, opted_out: true } });
    if (url === `${DISP}/web/join`) return json(200, { ok: false, reason: "handle_taken", me: { registered: false, email: "ana@example.com" } });
  }
  return json(404, { message: `unexpected ${url}` });
}

const dispCalls = () => calls.filter((c) => c.url.startsWith(DISP));
const verifyCalls = () => calls.filter((c) => c.url.endsWith("/auth/v1/verify"));

function form(fields: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}
const PREV = { ok: false, status: 0 };

beforeEach(() => {
  calls = [];
  cookieJar.clear();
  refreshReply = { status: 200, body: {} };
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", SUPA);
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key-test");
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "service-key-test");
  vi.stubEnv("NEXT_PUBLIC_SITE_URL", "https://site.test");
  vi.stubEnv("DISPATCHER_URL", DISP);
  vi.stubEnv("DISPATCHER_TOKEN", "disp-token");
  vi.stubEnv("NEXT_PUBLIC_WEB_JOIN", "1");
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("user auth realm (shared with admin)", () => {
  it("has its own cookies and nonce key: admin and user logins never cross", () => {
    expect(new Set([AT, RT, NONCE, ...Object.values(ADMIN_REALM.config).slice(0, 3)]).size).toBe(6);
    expect(USER_REALM.cookieOptions(60)).toMatchObject({ httpOnly: true, sameSite: "lax", path: "/" });
    expect(ADMIN_REALM.cookieOptions(60).path).toBe("/admin");
    const userNonce = USER_REALM.issueLoginNonce("ana@example.com").value;
    const adminNonce = ADMIN_REALM.issueLoginNonce("ana@example.com").value;
    expect(USER_REALM.loginNonceMatches(userNonce, "ana@example.com")).toBe(true);
    expect(USER_REALM.loginNonceMatches(adminNonce, "ana@example.com")).toBe(false);
    expect(ADMIN_REALM.loginNonceMatches(userNonce, "ana@example.com")).toBe(false);
  });

  it("send code binds the browser, sends with the /login/confirm redirect, any email may sign up", async () => {
    const r = await sendCode(PREV, form({ email: "Ana@Example.com" }));
    expect(r).toMatchObject({ ok: true, email: "ana@example.com" });
    expect(cookieJar.has(NONCE)).toBe(true);
    const otp = calls.find((c) => c.url.includes("/auth/v1/otp"))!;
    expect(otp.url).toBe(`${SUPA}/auth/v1/otp?redirect_to=${encodeURIComponent("https://site.test/login/confirm")}`);
    expect(otp.body).toMatchObject({ email: "ana@example.com", create_user: true });
  });

  it("code sign-in requires this browser's nonce (not spent otherwise) and sets user-realm cookies", async () => {
    const fd = () => form({ email: "ana@example.com", code: "123456" });
    expect(await verifyCode(PREV, fd())).toMatchObject({ ok: false, status: 403 });
    cookieJar.set(NONCE, ADMIN_REALM.issueLoginNonce("ana@example.com").value); // admin nonce is not accepted
    expect(await verifyCode(PREV, fd())).toMatchObject({ ok: false, status: 403 });
    expect(verifyCalls()).toHaveLength(0);
    await sendCode(PREV, form({ email: "ana@example.com" }));
    await expect(verifyCode(PREV, fd())).rejects.toThrow("REDIRECT:/me");
    expect(cookieJar.get(AT)).toBe("user-at");
    expect(cookieJar.get(RT)).toBe("user-rt");
    expect(cookieJar.has(NONCE)).toBe(false);
    expect(cookieJar.has(ADMIN_REALM.config.accessCookie)).toBe(false);
  });

  it("magic-link POST: cross-origin or nonce-less requests set no session; same browser lands on /me", async () => {
    const ORIGIN = "https://site.test";
    const req = (nonce?: string, origin = ORIGIN) =>
      new NextRequest(`${ORIGIN}/login/confirm`, {
        method: "POST",
        headers: {
          "content-type": "application/x-www-form-urlencoded",
          origin,
          ...(nonce ? { cookie: `${NONCE}=${nonce}` } : {}),
        },
        body: "token_hash=hash-ana-00001&type=email",
      });
    for (const r of [req(), req(USER_REALM.issueLoginNonce("ana@example.com").value, "https://evil.test")]) {
      const res = await confirmPost(r);
      expect(res.headers.get("location")).toBe(`${ORIGIN}/login?error=link`);
      expect(res.cookies.get(AT)).toBeUndefined();
    }
    expect(verifyCalls()).toHaveLength(0);
    const res = await confirmPost(req(USER_REALM.issueLoginNonce("ana@example.com").value));
    expect(res.headers.get("location")).toBe(`${ORIGIN}/me`);
    expect(res.cookies.get(AT)?.value).toBe("user-at");
  });

  it("proxy refreshes /me with user-realm cookies and /admin with admin cookies", async () => {
    refreshReply = { status: 200, body: { access_token: "at-2", refresh_token: "rt-2", expires_in: 3600 } };
    const me = await proxy(new NextRequest("https://site.test/me/status", { headers: { cookie: `${RT}=rt-old` } }));
    expect(me.cookies.get(AT)?.value).toBe("at-2");
    expect(me.cookies.get(ADMIN_REALM.config.accessCookie)).toBeUndefined();
    const admin = await proxy(
      new NextRequest("https://site.test/admin", { headers: { cookie: `${ADMIN_REALM.config.refreshCookie}=rt-old` } }),
    );
    expect(admin.cookies.get(ADMIN_REALM.config.accessCookie)?.value).toBe("at-2");
    expect(admin.cookies.get(AT)).toBeUndefined();
  });

  it("sign out revokes the session and clears cookies", async () => {
    cookieJar.set(AT, "user-at");
    cookieJar.set(RT, "user-rt");
    await expect(signOutUser()).rejects.toThrow("REDIRECT:/login");
    expect(cookieJar.has(AT) || cookieJar.has(RT)).toBe(false);
    expect(calls.some((c) => c.url.includes("/auth/v1/logout"))).toBe(true);
  });
});

describe("/me talks to the dispatcher only as the signed-in user", () => {
  it("forwards the user's own bearer token, never the dispatcher token or a user id", async () => {
    cookieJar.set(AT, "user-at");
    expect(await fetchMe("user-at")).toEqual({ status: "ok", me: ME });
    const q = await queueAction(PREV, form({ action: "join", user_id: "someone-else" }));
    expect(q).toMatchObject({ ok: true, me: ME });
    const o = await setTexts(PREV, form({ opted_out: "1", user_id: "someone-else" }));
    expect(o.me).toMatchObject({ opted_out: true });
    const j = await joinChallenge(PREV, form({ display_name: " Ana_W ", handle: "555-010-0001", age_ok: "on", rules_ok: "on" }));
    expect(j).toMatchObject({ ok: false, error: expect.stringMatching(/already linked/) });
    expect(dispCalls().map((c) => c.body)).toEqual([
      undefined,
      { action: "join" },
      { opted_out: true },
      { display_name: "Ana_W", handle: "555-010-0001", age_ok: true, rules_ok: true },
    ]);
    for (const c of dispCalls()) {
      expect(c.headers.Authorization).toBe("Bearer user-at");
      expect(c.headers["X-Brodie-Token"]).toBeUndefined();
    }
  });

  it("no session or an expired token means unauthenticated, with no dispatcher mutation", async () => {
    expect(await fetchMe(undefined)).toEqual({ status: "unauthenticated" });
    expect(await fetchMe("stale")).toEqual({ status: "unauthenticated" });
    expect(await queueAction(PREV, form({ action: "join" }))).toMatchObject({ ok: false, status: 401 });
    const res = await statusGet();
    expect(res.status).toBe(401);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("status route returns the caller's snapshot uncached", async () => {
    cookieJar.set(AT, "user-at");
    const res = await statusGet();
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual(ME);
    expect(res.headers.get("cache-control")).toBe("no-store");
  });

  it("everything is off unless NEXT_PUBLIC_WEB_JOIN=1", async () => {
    vi.stubEnv("NEXT_PUBLIC_WEB_JOIN", "");
    cookieJar.set(AT, "user-at");
    expect((await statusGet()).status).toBe(404);
    expect(await sendCode(PREV, form({ email: "ana@example.com" }))).toMatchObject({ ok: false, status: 404 });
    expect(await queueAction(PREV, form({ action: "join" }))).toMatchObject({ ok: false, status: 404 });
    expect(calls).toHaveLength(0);
  });
});

describe("me view helpers", () => {
  it("picks one hero phase in priority order", () => {
    expect(mePhase(ME)).toBe("waiting");
    expect(mePhase({ ...ME, claim: { line_id: "line-1", claimed_until: "", seconds_left: 40 } })).toBe("up");
    expect(mePhase({ ...ME, in_call: true, queue: { status: null, position: null, eta: null } })).toBe("in_call");
    const idle = { ...ME, queue: { status: null, position: null, eta: null } } as RegisteredMe;
    expect(mePhase({ ...idle, line_open: true })).toBe("open");
    expect(mePhase({ ...idle, calls_left: 0 })).toBe("at_cap");
    expect(mePhase({ ...idle, frozen: true })).toBe("closed");
    expect(mePhase({ ...ME, banned: true })).toBe("banned");
    expect(mePhase(idle)).toBe("idle");
  });

  it("formats ETA, countdown and FaceTime link", () => {
    expect(formatEtaRange({ lo_min: 10, hi_min: 15 })).toBe("~10–15 min");
    expect(formatEtaRange({ lo_min: 0, hi_min: 5 })).toBe("any minute");
    expect(formatEtaRange(null)).toBeNull();
    expect(claimSecondsLeft(90, 1_000, 31_000)).toBe(60);
    expect(claimSecondsLeft(10, 0, 60_000)).toBe(0);
    expect(formatClock(75)).toBe("1:15");
    expect(facetimeLink("+1 (555) 000-1111")).toBe("facetime:+15550001111");
    expect(facetimeLink(null)).toBeNull();
    expect(facetimeLink("javascript:alert(1)")).toBeNull();
  });
});

// ---- bundle hygiene for the competitor area (same scan as the admin console)
const ROOT = join(import.meta.dirname, "..");
const ME_DIRS = [join(ROOT, "app", "me"), join(ROOT, "app", "login")];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

describe("no secrets reach the browser from /me or /login", () => {
  it("client components import only types from server modules; server modules are server-only", () => {
    const files = [...ME_DIRS.flatMap((d) => walk(d)), join(ROOT, "lib", "me.ts"), join(ROOT, "lib", "auth-session.ts"), join(ROOT, "lib", "dispatcher.ts"), join(ROOT, "lib", "me-view.ts")];
    for (const f of files.filter((x) => /\.(ts|tsx)$/.test(x))) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/NEXT_PUBLIC_[A-Z_]*(SERVICE|SECRET|DISPATCHER|JWT)/);
      expect(src, f).not.toMatch(/raffle/i); // raffle cancelled: never shown or read here
      if (/^["']use client["']/.test(src)) {
        expect(src, f).not.toMatch(/^import (?!type )[^;]*from "@\/lib\/(admin|supabase-server|me|auth-session|dispatcher)"/m);
        expect(src, f).not.toMatch(/process\.env\.(?!NEXT_PUBLIC_)/);
      }
    }
    for (const f of ["me.ts", "auth-session.ts", "dispatcher.ts"]) {
      expect(readFileSync(join(ROOT, "lib", f), "utf8").startsWith('import "server-only";'), f).toBe(true);
    }
    expect(readFileSync(join(ROOT, "lib", "me-view.ts"), "utf8")).not.toMatch(/process\.env/);
  });

  const STATIC = join(ROOT, ".next", "static");
  it.skipIf(!existsSync(STATIC))("built .next/static has no service key, dispatcher config or JWT secret (run after `next build`)", () => {
    const patterns = [/SUPABASE_SERVICE_ROLE_KEY/, /service_role/, /c2VydmljZV9yb2xl/, /sb_secret_[A-Za-z0-9_-]{10,}/,
      /DISPATCHER_TOKEN/, /DISPATCHER_URL/, /SUPABASE_JWT_SECRET/, /brodie-user-login-nonce/, /brodie-admin-login-nonce/];
    const hits: string[] = [];
    for (const f of walk(STATIC).filter((x) => /\.(js|mjs|cjs|json|html|css|map|txt)$/.test(x))) {
      const text = readFileSync(f, "utf8");
      for (const re of patterns) if (re.test(text)) hits.push(`${f}: ${re}`);
    }
    expect(hits).toEqual([]);
  });
});
