"use client";

import { useActionState } from "react";
import { ME_IDLE } from "@/lib/me-view";
import { sendCode, verifyCode } from "./actions";

export const fieldCls =
  "min-h-13 w-full rounded-[var(--radius-card)] border-2 border-ink bg-surface px-4 text-lg text-ink placeholder:text-ink-3 focus:bg-canvas focus:outline-none";
export const primaryCls =
  "inline-flex min-h-13 w-full items-center justify-center press rounded-[var(--radius-card)] border-2 border-ink bg-pink px-6 font-display text-xl uppercase tracking-wide text-ink transition-transform active:scale-[0.98] disabled:opacity-60";

export function LoginForm() {
  const [sent, sendAction, sending] = useActionState(sendCode, ME_IDLE);
  const [verified, verifyAction, verifying] = useActionState(verifyCode, ME_IDLE);
  const email = "email" in sent && typeof sent.email === "string" ? sent.email : "";
  const codeSent = sent.ok && email;

  return (
    <div className="space-y-5">
      <form action={sendAction} className="space-y-3">
        <label htmlFor="login-email" className="eyebrow block">
          Email
        </label>
        <input
          id="login-email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="email"
          autoCapitalize="none"
          required
          defaultValue={email}
          placeholder="you@example.com"
          className={fieldCls}
        />
        <button type="submit" disabled={sending} className={codeSent ? "min-h-11 text-sm font-semibold text-ink-2 underline underline-offset-4" : primaryCls}>
          {sending ? "Sending…" : codeSent ? "Resend code" : "Email me a code"}
        </button>
        <p role="status" aria-live="polite" className={`text-sm ${sent.ok ? "text-accent" : "text-bad"}`}>
          {sent.status ? (sent.ok ? sent.message : sent.error) : null}
        </p>
      </form>

      {codeSent ? (
        <form action={verifyAction} className="space-y-3 border-t border-hairline pt-5">
          <input type="hidden" name="email" value={email} />
          <label htmlFor="login-code" className="eyebrow block">
            6-digit code
          </label>
          <input
            id="login-code"
            name="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]{6,12}"
            required
            autoFocus
            className={`${fieldCls} text-center font-mono text-3xl tracking-[0.4em]`}
          />
          <button type="submit" disabled={verifying} className={primaryCls}>
            {verifying ? "Checking…" : "Sign in"}
          </button>
          <p role="status" aria-live="polite" className="text-sm text-bad">
            {verified.status && !verified.ok ? verified.error : null}
          </p>
        </form>
      ) : null}
    </div>
  );
}
