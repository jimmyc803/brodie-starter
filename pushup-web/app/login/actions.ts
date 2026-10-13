"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { siteRedirect } from "@/lib/auth-session";
import { USER_REALM, parseLoginEmail, webJoinEnabled } from "@/lib/me";
import type { MeActionState } from "@/lib/me-view";
import { SupabaseError, authSendOtp } from "@/lib/supabase-server";

// Public POST endpoints (Next server actions carry their own Origin check). Same flow as the admin console, shared
// via lib/auth-session.ts, but any email may sign up: the account only becomes a competitor after /me's join form.

const DISABLED: MeActionState = { ok: false, status: 404, error: "Web sign-in isn't open right now." };

export async function sendCode(_prev: MeActionState, fd: FormData): Promise<MeActionState & { email?: string }> {
  if (!webJoinEnabled()) return DISABLED;
  const email = parseLoginEmail(fd.get("email"));
  if (!email) return { ok: false, status: 400, error: "Enter a valid email." };
  // Bind the pending sign-in to this browser + email before anything is sent.
  const nonce = USER_REALM.issueLoginNonce(email);
  (await cookies()).set(nonce.name, nonce.value, nonce.options);
  try {
    await authSendOtp(email, undefined, siteRedirect("/login/confirm"));
  } catch (e) {
    console.error("[me] send code failed", e instanceof SupabaseError ? `${e.status} ${e.message}` : e);
    if (e instanceof SupabaseError && e.status === 429) {
      return { ok: false, status: 429, error: "Too many codes requested. Wait a minute and try again.", email };
    }
    return { ok: false, status: 502, error: "Couldn't send the code. Try again in a moment.", email };
  }
  return { ok: true, status: 200, message: `Code sent to ${email}. Check your inbox (and spam).`, email };
}

export async function verifyCode(_prev: MeActionState, fd: FormData): Promise<MeActionState> {
  if (!webJoinEnabled()) return DISABLED;
  const email = parseLoginEmail(fd.get("email"));
  const code = String(fd.get("code") ?? "").replace(/\s+/g, "");
  if (!email) return { ok: false, status: 400, error: "Enter a valid email." };
  if (!/^\d{6,10}$/.test(code)) return { ok: false, status: 400, error: "Enter the numeric code from the email." };
  const store = await cookies();
  const signIn = await USER_REALM.signInWithCode(email, code, store.get(USER_REALM.config.nonceCookie)?.value);
  if (!signIn.ok) return { ok: false, status: signIn.status, error: signIn.error };
  for (const c of USER_REALM.sessionCookies(signIn.session)) store.set(c.name, c.value, c.options);
  store.set(USER_REALM.config.nonceCookie, "", USER_REALM.cookieOptions(0));
  redirect("/me");
}
