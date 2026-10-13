"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { USER_REALM, currentAccessToken, errorMessage, webJoinEnabled, webPost } from "@/lib/me";
import { joinReasonMessage, queueReasonMessage, type MeActionState } from "@/lib/me-view";

// Public POST endpoints. Identity is ONLY the signed-in user's own access token, forwarded to the dispatcher, which
// verifies it and maps it to their competitor record; no user id is accepted from the form.

async function run(
  path: "/web/join" | "/web/queue" | "/web/opt",
  body: Record<string, unknown>,
  ok: (reason: string | null) => string,
  fail: (reason: string | null) => string,
  isOk: (r: { ok: boolean; reason: string | null }) => boolean = (r) => r.ok,
): Promise<MeActionState> {
  if (!webJoinEnabled()) return { ok: false, status: 404, error: "Web sign-up isn't open right now." };
  const token = await currentAccessToken();
  if (!token) return { ok: false, status: 401, error: "Your session expired. Sign in again." };
  try {
    const r = await webPost(token, path, body);
    return isOk(r)
      ? { ok: true, status: 200, message: ok(r.reason), me: r.me }
      : { ok: false, status: 400, error: fail(r.reason), me: r.me };
  } catch (e) {
    console.error("[me] action failed", path, e instanceof Error ? e.message : e);
    return { ok: false, status: 502, error: errorMessage(e) };
  }
}

export async function joinChallenge(_prev: MeActionState, fd: FormData): Promise<MeActionState> {
  const str = (k: string) => (typeof fd.get(k) === "string" ? String(fd.get(k)).slice(0, 254) : "");
  return run(
    "/web/join",
    {
      display_name: str("display_name").trim().slice(0, 40),
      handle: str("handle").trim(),
      age_ok: fd.get("age_ok") === "on",
      rules_ok: fd.get("rules_ok") === "on",
    },
    (reason) => (reason === "already_registered" ? "You're already in." : "You're in. Welcome to the board."),
    joinReasonMessage,
  );
}

export async function queueAction(_prev: MeActionState, fd: FormData): Promise<MeActionState> {
  const action = fd.get("action") === "leave" ? "leave" : "join";
  return run(
    "/web/queue",
    { action },
    (reason) =>
      action === "leave"
        ? reason === "left"
          ? "You left the line."
          : "You weren't in line."
        : reason === "already"
          ? "You're already in line."
          : "You're in line.",
    queueReasonMessage,
  );
}

export async function setTexts(_prev: MeActionState, fd: FormData): Promise<MeActionState> {
  const optedOut = fd.get("opted_out") === "1";
  return run(
    "/web/opt",
    { opted_out: optedOut },
    () => (optedOut ? "Stopped. No more texts, and you left the line." : "Texts back on."),
    () => "Couldn't update your text settings.",
  );
}

export async function signOutUser(): Promise<void> {
  const store = await cookies();
  const at = store.get(USER_REALM.config.accessCookie)?.value;
  if (at) await USER_REALM.logoutQuietly(at);
  for (const c of USER_REALM.clearedCookies()) store.set(c.name, c.value, c.options);
  redirect("/login");
}
