"use client";

import Link from "next/link";
import { useState, useSyncExternalStore } from "react";

const noop = () => () => {};

// First-visit banner for a new coach (the dashboard link is their login) and the steps to their first client workout.
export function WelcomeBanner({ coachName }: { coachName: string }) {
  const [copied, setCopied] = useState(false);
  const href = useSyncExternalStore(noop, () => window.location.href.replace(/\?.*$/, ""), () => "");
  async function copy() {
    try {
      await navigator.clipboard.writeText(href);
      setCopied(true);
    } catch {
      /* the address bar still has it */
    }
  }
  return (
    <section className="rounded-[14px] border border-line bg-surface p-5">
      <h2 className="text-lg font-semibold text-ink">Welcome, Coach {coachName} 🎉</h2>
      <p className="mt-1 max-w-2xl text-sm text-ink-2">
        This page&apos;s link is your login: there&apos;s no password. <b className="text-ink">Bookmark it now</b> or copy it somewhere safe.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="min-w-0 max-w-full truncate rounded-md bg-canvas px-2 py-1.5 text-xs text-ink-2">{href}</code>
        <button type="button" onClick={copy} className="rounded-full bg-ink px-3 py-1.5 text-xs font-medium text-canvas">
          {copied ? "Copied" : "Copy my link"}
        </button>
      </div>
    </section>
  );
}

export type Step = { done: boolean; title: string; sub: string; href: string; cta: string };

export function GettingStarted({ steps }: { steps: Step[] }) {
  const done = steps.filter((s) => s.done).length;
  return (
    <section className="rounded-[14px] border border-line bg-surface p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-ink">Get your first client training</h2>
        <p className="text-xs tabular-nums text-ink-3">
          {done} of {steps.length} done
        </p>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-sunken">
        <div className="h-full rounded-full bg-ink transition-all" style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s.title} className={`rounded-[10px] border p-4 ${s.done ? "border-line bg-canvas opacity-70" : "border-line-strong bg-canvas"}`}>
            <span
              className={`grid size-6 place-items-center rounded-full text-xs font-semibold ${s.done ? "bg-good text-on-brand" : "bg-sunken text-ink-2"}`}
            >
              {s.done ? "✓" : i + 1}
            </span>
            <p className={`mt-3 text-sm font-medium ${s.done ? "text-ink-3 line-through" : "text-ink"}`}>{s.title}</p>
            <p className="mt-0.5 text-xs text-ink-3">{s.sub}</p>
            {!s.done ? (
              <Link href={s.href} className="mt-3 inline-block text-xs font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                {s.cta} →
              </Link>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
