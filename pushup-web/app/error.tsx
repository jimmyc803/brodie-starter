"use client";

import Link from "next/link";
import { useEffect } from "react";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <section role="alert" className="card mx-auto flex max-w-xl flex-col items-center px-6 py-14 text-center">
      <p className="eyebrow text-bad">Missed rep</p>
      <h1 className="mt-3 font-display text-6xl uppercase leading-none">Something broke</h1>
      <p className="mt-3 text-ink-2">The board couldn&apos;t load. Your reps are safe; this is just the page.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={reset}
          className="press inline-flex min-h-12 items-center rounded-[var(--radius-card)] border-2 border-ink bg-pink px-6 font-display text-xl uppercase text-ink"
        >
          Try again
        </button>
        <Link href="/rules" className="inline-flex min-h-12 items-center px-5 font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px]">
          Read the rules
        </Link>
      </div>
    </section>
  );
}
