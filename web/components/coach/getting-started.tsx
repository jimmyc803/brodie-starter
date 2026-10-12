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
    <section className="rounded-2xl border border-green-500/25 bg-green-500/5 p-5">
      <h2 className="text-lg font-semibold text-green-200">Welcome, Coach {coachName} 🎉</h2>
      <p className="mt-1 max-w-2xl text-sm text-zinc-300">
        This page&apos;s link is your login: there&apos;s no password. <b className="text-zinc-100">Bookmark it now</b> or copy it somewhere safe.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <code className="min-w-0 max-w-full truncate rounded-md bg-zinc-950/60 px-2 py-1.5 text-xs text-zinc-300">{href}</code>
        <button type="button" onClick={copy} className="rounded-full bg-zinc-50 px-3 py-1.5 text-xs font-medium text-zinc-950">
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
    <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-base font-semibold text-zinc-100">Get your first client training</h2>
        <p className="text-xs tabular-nums text-zinc-500">
          {done} of {steps.length} done
        </p>
      </div>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full rounded-full bg-green-500 transition-all" style={{ width: `${(done / steps.length) * 100}%` }} />
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {steps.map((s, i) => (
          <li key={s.title} className={`rounded-xl border p-4 ${s.done ? "border-zinc-800 bg-zinc-950/30" : "border-zinc-700 bg-zinc-950/60"}`}>
            <span
              className={`grid size-6 place-items-center rounded-full text-xs font-semibold ${s.done ? "bg-green-500 text-zinc-950" : "bg-zinc-800 text-zinc-300"}`}
            >
              {s.done ? "✓" : i + 1}
            </span>
            <p className={`mt-3 text-sm font-medium ${s.done ? "text-zinc-500 line-through" : "text-zinc-100"}`}>{s.title}</p>
            <p className="mt-0.5 text-xs text-zinc-500">{s.sub}</p>
            {!s.done ? (
              <Link href={s.href} className="mt-3 inline-block text-xs font-medium text-green-300 hover:text-green-200">
                {s.cta} →
              </Link>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
