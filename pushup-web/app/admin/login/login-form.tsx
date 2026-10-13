"use client";

import { useActionState } from "react";
import { sendLoginCode, signInWithPassword, verifyLoginCode } from "../actions";
import { INITIAL, Result, btnCls, inputCls } from "../_components/forms";

export function LoginForm() {
  const [sent, sendAction, sending] = useActionState(sendLoginCode, INITIAL);
  const [verified, verifyAction, verifying] = useActionState(verifyLoginCode, INITIAL);
  const [pw, pwAction, pwPending] = useActionState(signInWithPassword, INITIAL);
  const sentEmail =
    sent.ok && sent.data && typeof (sent.data as { email?: unknown }).email === "string"
      ? (sent.data as { email: string }).email
      : null;

  return (
    <div className="space-y-4">
      <form action={pwAction} className="space-y-2">
        <label className="block text-xs font-bold uppercase tracking-widest text-ink-2" htmlFor="admin-pw-email">
          Email
        </label>
        <input id="admin-pw-email" name="email" type="email" autoComplete="username" required className={inputCls} />
        <label className="block text-xs font-bold uppercase tracking-widest text-ink-2" htmlFor="admin-password">
          Password
        </label>
        <input
          id="admin-password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={inputCls}
        />
        <button type="submit" className={btnCls} disabled={pwPending}>
          {pwPending ? "Signing in..." : "Sign in"}
        </button>
        <Result state={pw} />
      </form>

      <details className="space-y-4 border-t border-hairline pt-4 text-xs text-ink-2" open={!!sentEmail}>
        <summary className="cursor-pointer font-semibold">No password? Sign in with an emailed code</summary>
        <form action={sendAction} className="mt-3 space-y-2">
          <label className="block text-xs font-bold uppercase tracking-widest text-ink-2" htmlFor="admin-email">
            Email
          </label>
          <input
            id="admin-email"
            name="email"
            type="email"
            autoComplete="email"
            required
            defaultValue={sentEmail ?? ""}
            className={inputCls}
          />
          <button type="submit" className={btnCls} disabled={sending}>
            {sending ? "Sending..." : sentEmail ? "Resend code" : "Email me a code"}
          </button>
          <Result state={sent} />
        </form>

        {sentEmail && (
          <form action={verifyAction} className="space-y-2 border-t border-hairline pt-4">
            <input type="hidden" name="email" value={sentEmail} />
            <label className="block text-xs font-bold uppercase tracking-widest text-ink-2" htmlFor="admin-code">
              Code from the email
            </label>
            <input
              id="admin-code"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              pattern="[0-9 ]{6,12}"
              className={`${inputCls} font-mono tracking-widest`}
            />
            <button type="submit" className={btnCls} disabled={verifying}>
              {verifying ? "Verifying..." : "Sign in"}
            </button>
            <Result state={verified} />
          </form>
        )}
      </details>
    </div>
  );
}
