import { existsSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// ---- Next/server-only shims: the modules under test are real; only framework I/O is faked.
vi.mock("server-only", () => ({}));
const cookieJar = new Map<string, string>();
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => (cookieJar.has(name) ? { name, value: cookieJar.get(name) } : undefined),
    set: (name: string, value: string) => void cookieJar.set(name, value),
  }),
}));
vi.mock("next/navigation", () => ({
  redirect: (url: string) => {
    throw new Error(`REDIRECT:${url}`);
  },
}));
vi.mock("next/cache", () => ({ refresh: vi.fn() }));

import {
  ACCESS_COOKIE,
  AdminInputError,
  checkAdmin,
  etYesterday,
  isAllowlisted,
  parsePoints,
  requireAdmin,
  requireReason,
} from "@/lib/admin";
import {
  drawRaffle,
  removeQueueEntry,
  sendBroadcast,
  sendLoginCode,
  setBan,
  setConfigValue,
} from "@/app/admin/actions";

// ---- fake Supabase + dispatcher
const SUPA = "https://proj.supabase.test";
const DISP = "https://dispatcher.test";
const ALLOW = ["Boss@Example.com"];
const TOKENS: Record<string, string> = { "tok-boss": "boss@example.com", "tok-rando": "rando@example.com" };

type Call = { url: string; method: string; headers: Record<string, string>; body: unknown };
let calls: Call[] = [];

function fakeFetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const url = String(input);
  const headers = Object.fromEntries(Object.entries((init?.headers ?? {}) as Record<string, string>));
  const body = typeof init?.body === "string" ? (JSON.parse(init.body) as unknown) : undefined;
  calls.push({ url, method: init?.method ?? "GET", headers, body });
  const json = (status: number, v: unknown) =>
    Promise.resolve(new Response(JSON.stringify(v), { status, headers: { "content-type": "application/json" } }));
  if (url === `${SUPA}/auth/v1/user`) {
    const tok = headers.Authorization?.replace("Bearer ", "") ?? "";
    return TOKENS[tok] ? json(200, { email: TOKENS[tok] }) : json(401, { msg: "invalid JWT" });
  }
  if (url.startsWith(`${SUPA}/rest/v1/admin_allowlist`)) {
    expect(headers.apikey).toBe("service-key-test");
    return json(200, ALLOW.map((email) => ({ email })));
  }
  if (url.startsWith(`${SUPA}/rest/v1/rpc/`)) {
    const b = body as Record<string, unknown>;
    if (!b.p_reason || !String(b.p_reason).trim()) return json(400, { code: "22023", message: "reason_required" });
    return json(200, { ok: true });
  }
  if (url === `${SUPA}/rest/v1/audit_log`) return Promise.resolve(new Response(null, { status: 201 }));
  if (url === `${SUPA}/auth/v1/otp`) return json(200, {});
  if (url.startsWith(DISP)) {
    if (headers["X-Brodie-Token"] !== "disp-token") return json(401, { detail: "bad token" });
    return json(200, { eligible_count: 12, winner: { display_name: "Ana" }, recipients: 3, preview: "hi" });
  }
  return json(404, { message: `unexpected ${url}` });
}

const rpcCalls = () => calls.filter((c) => c.url.includes("/rest/v1/rpc/"));
const dispatcherCalls = () => calls.filter((c) => c.url.startsWith(DISP));

function form(fields: Record<string, string>): FormData {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  return fd;
}

const PREV = { ok: false, status: 0 };
const USER = "11111111-2222-3333-4444-555555555555";

beforeEach(() => {
  calls = [];
  cookieJar.clear();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", SUPA);
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "anon-key-test");
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "service-key-test");
  vi.stubEnv("DISPATCHER_URL", DISP);
  vi.stubEnv("DISPATCHER_TOKEN", "disp-token");
  vi.stubGlobal("fetch", vi.fn(fakeFetch));
});
afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("allowlist guard", () => {
  it("classifies sessions server-side", async () => {
    expect(await checkAdmin(undefined)).toEqual({ status: "unauthenticated" });
    expect(await checkAdmin("forged.jwt.value")).toEqual({ status: "unauthenticated" });
    expect(await checkAdmin("tok-rando")).toEqual({ status: "forbidden", email: "rando@example.com" });
    expect(await checkAdmin("tok-boss")).toEqual({ status: "ok", email: "boss@example.com" });
  });

  it("matches the allowlist exactly (case-insensitive, no wildcards)", async () => {
    expect(await isAllowlisted("BOSS@example.com")).toBe(true);
    expect(await isAllowlisted("b_ss@example.com")).toBe(false);
    expect(await isAllowlisted("%")).toBe(false);
    expect(await isAllowlisted("")).toBe(false);
  });

  it("requireAdmin redirects unauthenticated and non-allowlisted users", async () => {
    await expect(requireAdmin()).rejects.toThrow("REDIRECT:/admin/login");
    cookieJar.set(ACCESS_COOKIE, "tok-rando");
    await expect(requireAdmin()).rejects.toThrow("REDIRECT:/admin/login?error=forbidden");
    cookieJar.set(ACCESS_COOKIE, "tok-boss");
    await expect(requireAdmin()).resolves.toEqual({ email: "boss@example.com" });
  });

  it("server actions return 401/403 and never touch RPCs for non-admins", async () => {
    const fd = form({ user_id: USER, ban: "1", reason: "cheating on camera" });
    expect(await setBan(PREV, fd)).toMatchObject({ ok: false, status: 401 });
    cookieJar.set(ACCESS_COOKIE, "tok-rando");
    expect(await setBan(PREV, fd)).toMatchObject({ ok: false, status: 403 });
    expect(await removeQueueEntry(PREV, form({ queue_id: "5", reason: "spam entry" }))).toMatchObject({ status: 403 });
    expect(await drawRaffle(PREV, form({ seed: "42", reason: "final draw", confirm: "yes" }))).toMatchObject({
      status: 403,
    });
    expect(rpcCalls()).toHaveLength(0);
    expect(dispatcherCalls()).toHaveLength(0);
    expect(calls.some((c) => c.url.includes("/audit_log"))).toBe(false);
  });

  it("allowlisted admin mutates with actor = verified session email", async () => {
    cookieJar.set(ACCESS_COOKIE, "tok-boss");
    const res = await setBan(PREV, form({ user_id: USER, ban: "1", reason: "  cheating   on camera " }));
    expect(res).toMatchObject({ ok: true, status: 200 });
    expect(rpcCalls()).toHaveLength(1);
    expect(rpcCalls()[0].url).toBe(`${SUPA}/rest/v1/rpc/ch_admin_ban`);
    expect(rpcCalls()[0].body).toEqual({ p_user_id: USER, p_reason: "cheating on camera", p_actor: "boss@example.com" });
  });

  it("login never reveals allowlist membership and only emails allowlisted addresses", async () => {
    const a = await sendLoginCode(PREV, form({ email: "rando@example.com" }));
    const b = await sendLoginCode(PREV, form({ email: "boss@example.com" }));
    expect(a.message).toBe(b.message);
    const otp = calls.filter((c) => c.url.endsWith("/auth/v1/otp"));
    expect(otp).toHaveLength(1);
    expect(otp[0].body).toMatchObject({ email: "boss@example.com" });
  });
});

describe("reason validation", () => {
  it("requireReason trims, collapses and enforces bounds", () => {
    expect(requireReason("  dup   entry ")).toBe("dup entry");
    for (const bad of [undefined, null, "", "   ", "ab", 42, "x".repeat(501)]) {
      expect(() => requireReason(bad)).toThrow(AdminInputError);
    }
  });

  it("every mutating action rejects a missing reason before any RPC/dispatcher call", async () => {
    cookieJar.set(ACCESS_COOKIE, "tok-boss");
    const cases = [
      () => setBan(PREV, form({ user_id: USER, ban: "1", reason: " " })),
      () => removeQueueEntry(PREV, form({ queue_id: "7" })),
      () => setConfigValue(PREV, form({ key: "daily_call_cap", value: "6", reason: "" })),
      () => sendBroadcast(PREV, form({ body: "hello", confirm: "yes", reason: "" })),
      () => drawRaffle(PREV, form({ seed: "42", confirm: "yes", reason: "no" })),
    ];
    for (const run of cases) {
      const r = await run();
      expect(r.ok).toBe(false);
      expect(r.status).toBe(400);
      expect(r.error).toMatch(/Reason is required/);
    }
    expect(rpcCalls()).toHaveLength(0);
    expect(dispatcherCalls()).toHaveLength(0);
  });

  it("validates other inputs", async () => {
    cookieJar.set(ACCESS_COOKIE, "tok-boss");
    expect(() => parsePoints("0")).toThrow(AdminInputError);
    expect(() => parsePoints("1.5")).toThrow(AdminInputError);
    expect(parsePoints("-25")).toBe(-25);
    const badJson = await setConfigValue(PREV, form({ key: "daily_call_cap", value: "{nope", reason: "raise cap" }));
    expect(badJson).toMatchObject({ status: 400, error: "Value is not valid JSON." });
    const noConfirm = await sendBroadcast(PREV, form({ body: "hello", reason: "launch note" }));
    expect(noConfirm).toMatchObject({ status: 400 });
    expect(rpcCalls()).toHaveLength(0);
    expect(dispatcherCalls()).toHaveLength(0);
  });

  it("dispatcher mutations are audited before the call and carry the admin email", async () => {
    cookieJar.set(ACCESS_COOKIE, "tok-boss");
    const r = await drawRaffle(PREV, form({ seed: "2026-10-19", reason: "final draw", confirm: "yes" }));
    expect(r).toMatchObject({ ok: true, status: 200 });
    const idx = (pred: (c: Call) => boolean) => calls.findIndex(pred);
    const firstAudit = idx((c) => c.url.endsWith("/audit_log"));
    const disp = idx((c) => c.url === `${DISP}/admin/raffle`);
    expect(firstAudit).toBeGreaterThan(-1);
    expect(firstAudit).toBeLessThan(disp);
    expect(calls[disp].headers["X-Admin-Email"]).toBe("boss@example.com");
    expect(calls[disp].body).toEqual({ seed: "2026-10-19" });
    expect(calls.filter((c) => c.url.endsWith("/audit_log"))).toHaveLength(2);
    expect(calls[firstAudit].body).toMatchObject({ actor: "boss@example.com", action: "admin_raffle", reason: "final draw" });
  });
});

describe("ET day helpers", () => {
  it("yesterday across DST end (Nov 2 2026)", () => {
    const y = etYesterday(Date.parse("2026-11-02T12:00:00Z"));
    expect(y.date).toBe("2026-11-01");
    expect(y.start.toISOString()).toBe("2026-11-01T04:00:00.000Z");
    expect(y.end.toISOString()).toBe("2026-11-02T05:00:00.000Z");
  });
});

// ---- client bundle must never contain the service key (name or value pattern)
const ROOT = join(import.meta.dirname, "..");
const SECRET_PATTERNS = [
  /SUPABASE_SERVICE_ROLE_KEY/,
  /service_role/,
  /c2VydmljZV9yb2xl/, // base64("service_role"), as embedded in a service-role JWT payload
  /sb_secret_[A-Za-z0-9_-]{10,}/,
  /DISPATCHER_TOKEN/,
];

function scanDir(dir: string): string[] {
  const hits: string[] = [];
  const walk = (d: string) => {
    for (const name of readdirSync(d)) {
      const p = join(d, name);
      if (statSync(p).isDirectory()) walk(p);
      else if (/\.(js|mjs|cjs|json|html|css|map|txt)$/.test(name)) {
        const text = readFileSync(p, "utf8");
        for (const re of SECRET_PATTERNS) if (re.test(text)) hits.push(`${p}: ${re}`);
      }
    }
  };
  walk(dir);
  return hits;
}

describe("service key never reaches the browser", () => {
  it("scanner detects key names and values", () => {
    const d = mkdtempSync(join(tmpdir(), "bundle-"));
    mkdirSync(join(d, "chunks"));
    writeFileSync(join(d, "chunks", "ok.js"), "console.log('anon only')");
    expect(scanDir(d)).toEqual([]);
    writeFileSync(join(d, "chunks", "bad.js"), 'const k="eyJhbGciOi.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.x"');
    expect(scanDir(d)).toHaveLength(1);
  });

  it("source: service key / dispatcher token only read in server-only modules, never NEXT_PUBLIC", () => {
    const files: string[] = [];
    const walk = (d: string) => {
      for (const name of readdirSync(d)) {
        if (["node_modules", ".next", "tests"].includes(name)) continue;
        const p = join(d, name);
        if (statSync(p).isDirectory()) walk(p);
        else if (/\.(ts|tsx|mjs|js)$/.test(name)) files.push(p);
      }
    };
    walk(ROOT);
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      expect(src, f).not.toMatch(/NEXT_PUBLIC_[A-Z_]*(SERVICE|SECRET|DISPATCHER)/);
      if (/process\.env\.(SUPABASE_SERVICE_ROLE_KEY|DISPATCHER_TOKEN)/.test(src)) {
        expect(src.startsWith('import "server-only";'), `${f} must import server-only`).toBe(true);
      }
      if (/^["']use client["']/.test(src)) {
        // Client components may only import types from server modules.
        expect(src, f).not.toMatch(/^import (?!type )[^;]*from "@\/lib\/(admin|supabase-server)"/m);
      }
    }
  });

  const STATIC = join(ROOT, ".next", "static");
  it.skipIf(!existsSync(STATIC))("built .next/static contains no service key name or value (run after `next build`)", () => {
    expect(scanDir(STATIC)).toEqual([]);
  });
});
