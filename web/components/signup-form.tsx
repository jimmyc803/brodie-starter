"use client";

import { useActionState, useState } from "react";

import { signupAction, type SignupState } from "@/app/start/actions";

const field =
  "mt-1.5 block w-full rounded-xl border border-zinc-700 bg-zinc-950 px-3.5 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-500 focus:border-zinc-500 focus:outline-none";

export function SignupForm() {
  const [state, action, pending] = useActionState<SignupState, FormData>(signupAction, { ok: false, message: "" });
  // When the person first touches the form (kept in state: React resets uncontrolled fields after each submit).
  // The server rejects submissions faster than a human could type.
  const [started, setStarted] = useState(0);
  const stamp = () => {
    if (!started) setStarted(Date.now());
  };
  return (
    <form action={action} onFocus={stamp} className="space-y-4">
      <div>
        <label htmlFor="name" className="text-sm font-medium text-zinc-200">
          Your name
        </label>
        <input id="name" name="name" required maxLength={60} autoComplete="name" placeholder="Tristan Lee" className={field} />
        <p className="mt-1 text-xs text-zinc-500">Clients see you as &quot;Coach&quot; + your first name.</p>
      </div>
      <div>
        <label htmlFor="email" className="text-sm font-medium text-zinc-200">
          Email
        </label>
        <input id="email" name="email" type="email" required maxLength={254} autoComplete="email" placeholder="you@example.com" className={field} />
      </div>
      <div>
        <label htmlFor="instagram" className="text-sm font-medium text-zinc-200">
          Instagram <span className="font-normal text-zinc-500">(optional)</span>
        </label>
        <input id="instagram" name="instagram" maxLength={60} autoComplete="off" placeholder="@yourhandle" className={field} />
      </div>
      {/* honeypot: hidden from people, filled by bots */}
      <div aria-hidden className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
        <label>
          Website <input name="website" tabIndex={-1} autoComplete="off" />
        </label>
      </div>
      <input type="hidden" name="started" value={started} readOnly />
      <button
        disabled={pending}
        className="w-full rounded-full bg-green-500 px-6 py-3 text-base font-semibold text-zinc-950 transition-colors hover:bg-green-400 disabled:opacity-60"
      >
        {pending ? "Creating your dashboard…" : "Create my coach dashboard"}
      </button>
      {state.message ? (
        <p role="alert" className="text-sm text-red-300">
          {state.message}
        </p>
      ) : null}
      <p className="text-xs leading-relaxed text-zinc-500">
        Free while we&apos;re in pilot. No passwords: your private dashboard link is your login, so keep it safe.
      </p>
    </form>
  );
}
