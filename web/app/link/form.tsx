"use client";

import { useActionState } from "react";

import { emailLinkAction, type LinkState } from "./actions";

export function LinkForm() {
  const [state, action, pending] = useActionState<LinkState, FormData>(emailLinkAction, { ok: false, message: "" });
  return (
    <form action={action} className="space-y-4">
      <div>
        <label htmlFor="email" className="text-sm font-medium text-ink">
          Email you applied with
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          maxLength={254}
          autoComplete="email"
          placeholder="you@example.com"
          className="mt-1.5 block w-full rounded-[10px] border border-line-strong bg-canvas px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:border-ink/40 focus:outline-none"
        />
      </div>
      <input type="text" name="website" tabIndex={-1} autoComplete="off" aria-hidden className="hidden" />
      <button
        disabled={pending}
        className="w-full rounded-[10px] bg-ink px-5 py-3 text-sm font-semibold text-canvas transition hover:opacity-90 disabled:opacity-60"
      >
        {pending ? "Checking…" : "Email me my link"}
      </button>
      {state.message ? (
        <p role={state.ok ? "status" : "alert"} className={`text-sm ${state.ok ? "text-ink-2" : "text-bad"}`}>
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
