"use server";

import { cookies } from "next/headers";
import { refresh } from "next/cache";
import { redirect } from "next/navigation";
import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  AdminInputError,
  cookieOptions,
  dispatcherRequest,
  isAllowlisted,
  parseCallId,
  parseConfigKey,
  parseEmail,
  parseJsonValue,
  parseOptionalJsonObject,
  parsePoints,
  parseQueueId,
  parseText,
  parseUuid,
  requireReason,
  rpcOutcome,
  runAdminAction,
  sessionCookies,
  writeAudit,
  type ActionResult,
} from "@/lib/admin";
import { SupabaseError, authLogout, authSendOtp, authVerifyOtp, serviceRpc } from "@/lib/supabase-server";

// Every exported function here is a public POST endpoint. All admin mutations go through runAdminAction, which
// re-verifies the Supabase session and admin_allowlist membership server-side before touching anything.

type Prev = ActionResult;

function done(r: ActionResult): ActionResult {
  if (r.ok) refresh();
  return r;
}

// ------------------------------------------------------------------ login / logout

const SENT_MSG = "If this address is on the admin allowlist, a sign-in code was emailed. Codes are rate-limited.";

export async function sendLoginCode(_prev: Prev, fd: FormData): Promise<ActionResult> {
  let email: string;
  try {
    email = parseEmail(fd.get("email"));
  } catch (e) {
    return { ok: false, status: 400, error: e instanceof AdminInputError ? e.message : "Invalid email." };
  }
  try {
    // Only allowlisted addresses get an email (and an auth user); the response never reveals membership.
    if (await isAllowlisted(email)) await authSendOtp(email);
  } catch (e) {
    console.error("[admin] send code failed", e instanceof SupabaseError ? `${e.status} ${e.message}` : e);
  }
  return { ok: true, status: 200, message: SENT_MSG, data: { email } };
}

export async function verifyLoginCode(_prev: Prev, fd: FormData): Promise<ActionResult> {
  let email: string;
  let code: string;
  try {
    email = parseEmail(fd.get("email"));
    code = String(fd.get("code") ?? "").replace(/\s+/g, "");
    if (!/^\d{6,10}$/.test(code)) throw new AdminInputError("Enter the numeric code from the email.");
  } catch (e) {
    return { ok: false, status: 400, error: e instanceof AdminInputError ? e.message : "Invalid input." };
  }
  let session;
  try {
    session = await authVerifyOtp({ email, token: code });
  } catch (e) {
    console.error("[admin] verify failed", e instanceof SupabaseError ? `${e.status} ${e.message}` : e);
    return { ok: false, status: 401, error: "Code is invalid or expired.", data: { email } };
  }
  const sessionEmail = session.email ?? email;
  let allowed: boolean;
  try {
    allowed = await isAllowlisted(sessionEmail);
  } catch (e) {
    console.error("[admin] allowlist check failed", e);
    return { ok: false, status: 503, error: "Could not verify allowlist; try again.", data: { email } };
  }
  if (!allowed) {
    await authLogout(session.accessToken).catch((e) => console.error("[admin] logout failed", e));
    return { ok: false, status: 403, error: "Forbidden: not on the admin allowlist." };
  }
  const store = await cookies();
  for (const c of sessionCookies(session)) store.set(c.name, c.value, c.options);
  redirect("/admin");
}

export async function signOut(): Promise<void> {
  const store = await cookies();
  const at = store.get(ACCESS_COOKIE)?.value;
  if (at) await authLogout(at).catch((e) => console.error("[admin] logout failed", e));
  store.set(ACCESS_COOKIE, "", cookieOptions(0));
  store.set(REFRESH_COOKIE, "", cookieOptions(0));
  redirect("/admin/login");
}

// ------------------------------------------------------------------ queue / config

export async function removeQueueEntry(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const queueId = parseQueueId(fd.get("queue_id"));
      const reason = requireReason(fd.get("reason"));
      const res = await serviceRpc("ch_admin_queue_remove", { p_queue_id: queueId, p_reason: reason, p_actor: email });
      return rpcOutcome(res, `Removed queue entry ${queueId}.`);
    }),
  );
}

export async function setConfigValue(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const key = parseConfigKey(fd.get("key"));
      const value = parseJsonValue(fd.get("value"));
      const reason = requireReason(fd.get("reason"));
      const res = await serviceRpc("ch_config_set", { p_key: key, p_value: value, p_actor: email, p_reason: reason });
      return rpcOutcome(res, `Saved ${key}.`);
    }),
  );
}

// ------------------------------------------------------------------ users / scores / calls

export async function setBan(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const userId = parseUuid(fd.get("user_id"));
      const ban = fd.get("ban") === "1";
      const reason = requireReason(fd.get("reason"));
      const res = await serviceRpc(ban ? "ch_admin_ban" : "ch_admin_unban", {
        p_user_id: userId,
        p_reason: reason,
        p_actor: email,
      });
      return rpcOutcome(res, ban ? "User banned." : "User unbanned.");
    }),
  );
}

export async function adjustScore(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const userId = parseUuid(fd.get("user_id"));
      const points = parsePoints(fd.get("points"));
      const reason = requireReason(fd.get("reason"));
      const res = await serviceRpc<Record<string, unknown>>("ch_admin_adjust", {
        p_user_id: userId,
        p_points: points,
        p_reason: reason,
        p_actor: email,
      });
      return rpcOutcome(res, `Adjusted ${points > 0 ? "+" : ""}${points}; total now ${String(res?.points ?? "?")}.`);
    }),
  );
}

export async function setVoid(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const callId = parseCallId(fd.get("call_id"));
      const voidIt = fd.get("void") === "1";
      const reason = requireReason(fd.get("reason"));
      const res = await serviceRpc(voidIt ? "ch_admin_void_call" : "ch_admin_unvoid_call", {
        p_call_id: callId,
        p_reason: reason,
        p_actor: email,
      });
      return rpcOutcome(res, voidIt ? `Voided ${callId}.` : `Unvoided ${callId}.`);
    }),
  );
}

// ------------------------------------------------------------------ dispatcher-backed actions

/**
 * Dispatcher mutations are audited by the site as well: an intent row BEFORE the call (fail closed: no audit, no
 * action) and an outcome row after.
 */
async function auditedDispatch(
  email: string,
  action: string,
  target: string | null,
  reason: string,
  request: unknown,
  call: () => Promise<unknown>,
): Promise<unknown> {
  await writeAudit({ actor: email, action, target, before: null, after: { phase: "requested", request }, reason });
  let result: unknown;
  try {
    result = await call();
  } catch (e) {
    await writeAudit({
      actor: email,
      action,
      target,
      before: null,
      after: { phase: "failed", error: e instanceof Error ? e.message : String(e) },
      reason,
    }).catch((err) => console.error("[admin] audit (failure) write failed", err));
    throw e;
  }
  await writeAudit({ actor: email, action, target, before: null, after: { phase: "done", result }, reason });
  return result;
}

const BROADCAST_MAX = 1000;

export async function previewBroadcast(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return runAdminAction(async ({ email }) => {
    const body = parseText(fd.get("body"), "Message", BROADCAST_MAX);
    const res = await dispatcherRequest("POST", "/admin/broadcast", { email, body: { body, dry_run: true } });
    return { ok: true, message: "Preview ready. Review, then confirm to send.", data: { body, result: res } };
  });
}

export async function sendBroadcast(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const body = parseText(fd.get("body"), "Message", BROADCAST_MAX);
      const reason = requireReason(fd.get("reason"));
      if (fd.get("confirm") !== "yes") throw new AdminInputError("Tick the confirmation box to send.");
      const res = await auditedDispatch(email, "admin_broadcast", null, reason, { body }, () =>
        dispatcherRequest("POST", "/admin/broadcast", { email, reason, body: { body, dry_run: false } }),
      );
      return { ok: true, message: "Broadcast queued.", data: { body, result: res } };
    }),
  );
}

export async function rejudgeDryRun(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return runAdminAction(async ({ email }) => {
    const thresholds = parseOptionalJsonObject(fd.get("thresholds"), "Thresholds");
    const res = await dispatcherRequest("POST", "/admin/rejudge", {
      email,
      body: { ...(thresholds ? { thresholds } : {}), apply: false },
      timeoutMs: 120_000,
    });
    return { ok: true, message: "Dry run complete (nothing written).", data: { thresholds: typeof fd.get("thresholds") === "string" ? fd.get("thresholds") : "", result: res } };
  });
}

export async function rejudgeApply(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const thresholds = parseOptionalJsonObject(fd.get("thresholds"), "Thresholds");
      const reason = requireReason(fd.get("reason"));
      if (fd.get("confirm") !== "yes") throw new AdminInputError("Tick the confirmation box to apply.");
      const body = { ...(thresholds ? { thresholds } : {}), apply: true };
      const res = await auditedDispatch(email, "admin_rejudge", null, reason, body, () =>
        dispatcherRequest("POST", "/admin/rejudge", { email, reason, body, timeoutMs: 120_000 }),
      );
      return { ok: true, message: "Rejudge applied.", data: { result: res } };
    }),
  );
}

export async function drawRaffle(_prev: Prev, fd: FormData): Promise<ActionResult> {
  return done(
    await runAdminAction(async ({ email }) => {
      const seed = parseText(fd.get("seed"), "Seed", 200);
      const reason = requireReason(fd.get("reason"));
      if (fd.get("confirm") !== "yes") throw new AdminInputError("Tick the confirmation box to draw.");
      const res = await auditedDispatch(email, "admin_raffle", seed, reason, { seed }, () =>
        dispatcherRequest("POST", "/admin/raffle", { email, reason, body: { seed } }),
      );
      return { ok: true, message: "Raffle drawn and logged.", data: { seed, result: res } };
    }),
  );
}
