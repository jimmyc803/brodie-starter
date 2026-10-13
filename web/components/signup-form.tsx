"use client";

import Link from "next/link";
import { useActionState, useState } from "react";

import { signupAction, type SignupState } from "@/app/start/actions";

const field =
  "mt-1.5 block w-full rounded-[10px] border border-line-strong bg-canvas px-3.5 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:border-ink/40 focus:outline-none";

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
        <label htmlFor="name" className="text-sm font-medium text-ink">
          Your name
        </label>
        <input id="name" name="name" required maxLength={60} autoComplete="name" placeholder="Tristan Lee" className={field} />
        <p className="mt-1 text-xs text-ink-3">Clients see you as &quot;Coach&quot; + your first name.</p>
      </div>
      <div>
        <label htmlFor="email" className="text-sm font-medium text-ink">
          Email
        </label>
        <input id="email" name="email" type="email" required maxLength={254} autoComplete="email" placeholder="you@example.com" className={field} />
      </div>
      <div>
        <label htmlFor="where" className="text-sm font-medium text-ink">
          Where do you coach?
        </label>
        <input id="where" name="where" required maxLength={120} placeholder="e.g. Iron Temple Gym, Boston · or Online" className={field} />
      </div>
      <div>
        <label htmlFor="clients" className="text-sm font-medium text-ink">
          Active clients right now
        </label>
        <select id="clients" name="clients" required defaultValue="" className={field}>
          <option value="" disabled>
            Choose one
          </option>
          <option value="1-5">1–5</option>
          <option value="6-15">6–15</option>
          <option value="16-40">16–40</option>
          <option value="40+">40+</option>
        </select>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="instagram" className="text-sm font-medium text-ink">
            Instagram
          </label>
          <input id="instagram" name="instagram" maxLength={60} autoComplete="off" placeholder="@yourhandle" className={field} />
        </div>
        <div>
          <label htmlFor="site" className="text-sm font-medium text-ink">
            or website
          </label>
          <input id="site" name="site" maxLength={200} autoComplete="url" placeholder="yoursite.com" className={field} />
        </div>
      </div>
      <div>
        <label htmlFor="certification" className="text-sm font-medium text-ink">
          Certification <span className="font-normal text-ink-3">(optional)</span>
        </label>
        <input id="certification" name="certification" maxLength={120} placeholder="e.g. NASM-CPT, CSCS" className={field} />
      </div>
      <div>
        <label htmlFor="note" className="text-sm font-medium text-ink">
          Anything we should know? <span className="font-normal text-ink-3">(optional)</span>
        </label>
        <textarea id="note" name="note" maxLength={500} rows={2} placeholder="How you'd use Brodie with your clients" className={field} />
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
        className="w-full rounded-[14px] bg-brand px-6 py-3 text-base font-semibold text-on-brand transition hover:brightness-95 disabled:opacity-60"
      >
        {pending ? "Sending your application…" : "Apply and explore now"}
      </button>
      <p className="text-xs text-ink-3">
        By applying you agree to the{" "}
        <Link href="/privacy" className="text-ink-2 underline underline-offset-2">
          privacy notice
        </Link>
        .
      </p>
      {state.message ? (
        <p role="alert" className="text-sm text-bad">
          {state.message}
        </p>
      ) : null}
      <p className="text-xs leading-relaxed text-ink-3">
        Free during the pilot. You can explore with a demo client right away; we review every coach personally (usually within 24
        hours) before you add real clients.
      </p>
    </form>
  );
}
