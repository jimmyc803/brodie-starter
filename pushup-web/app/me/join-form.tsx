"use client";

import Link from "next/link";
import { useActionState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ME_IDLE } from "@/lib/me-view";
import { fieldCls, primaryCls } from "../login/login-form";
import { joinChallenge } from "./actions";

export function JoinForm({ email }: { email: string | null }) {
  const [state, action, pending] = useActionState(joinChallenge, ME_IDLE);
  const router = useRouter();
  useEffect(() => {
    if (state.ok) router.refresh();
  }, [state.ok, router]);

  return (
    <div>
      <p className="eyebrow text-accent">One step left</p>
      <h1 className="mt-3 font-display text-hero font-extrabold uppercase italic tracking-tight">
        Claim your <span className="text-accent">name.</span>
      </h1>
      <p className="mt-3 text-ink-2">
        Signed in{email ? ` as ${email}` : ""}. Pick the name that goes on the board and tell us where you FaceTime from,
        so Brodie knows the call is yours.
      </p>

      <form action={action} className="card mt-6 space-y-5 p-5 sm:p-6">
        <div className="space-y-2">
          <label htmlFor="join-name" className="eyebrow block">
            Board name
          </label>
          <input
            id="join-name"
            name="display_name"
            required
            minLength={3}
            maxLength={20}
            pattern="[A-Za-z0-9_]+( [A-Za-z0-9_]+)*"
            autoComplete="nickname"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="Marcus_T"
            className={fieldCls}
          />
          <p className="text-sm text-ink-3">3–20 letters, numbers, underscores or spaces. Public.</p>
        </div>
        <div className="space-y-2">
          <label htmlFor="join-handle" className="eyebrow block">
            iPhone FaceTime number or Apple ID email <span className="normal-case tracking-normal text-ink-3">(optional)</span>
          </label>
          <input
            id="join-handle"
            name="handle"
            maxLength={254}
            autoComplete="tel"
            autoCapitalize="none"
            spellCheck={false}
            placeholder="(555) 123-4567"
            className={fieldCls}
          />
          <p className="text-sm text-ink-3">
            Private, never shown. You&apos;ll verify it by texting a code to Brodie; until then (or if you skip it) we
            recognise your call by your turn in line.
          </p>
        </div>
        <fieldset className="space-y-3">
          <legend className="sr-only">Eligibility</legend>
          <label className="flex min-h-11 items-start gap-3 text-ink-2">
            <input type="checkbox" name="age_ok" required className="mt-1 size-5 shrink-0 accent-[var(--color-accent)]" />
            <span>I&apos;m 18 or older and in the US, calling from an iPhone.</span>
          </label>
          <label className="flex min-h-11 items-start gap-3 text-ink-2">
            <input type="checkbox" name="rules_ok" required className="mt-1 size-5 shrink-0 accent-[var(--color-accent)]" />
            <span>
              I accept the{" "}
              <Link href="/rules" className="font-semibold text-ink underline underline-offset-4">
                rules
              </Link>{" "}
              (strict reps, 5 calls a day, one account per person).
            </span>
          </label>
        </fieldset>
        <button type="submit" disabled={pending} className={primaryCls}>
          {pending ? "Joining…" : "Join the challenge"}
        </button>
        <p role="status" aria-live="polite" className={`text-sm ${state.ok ? "text-accent" : "text-bad"}`}>
          {state.status ? (state.ok ? state.message : state.error) : null}
        </p>
      </form>
    </div>
  );
}
