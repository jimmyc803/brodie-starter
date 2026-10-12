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
      <h1 className="mt-3 font-display text-5xl font-extrabold uppercase italic leading-none">Something broke</h1>
      <p className="mt-3 text-ink-2">The board couldn&apos;t load. Your reps are safe; this is just the page.</p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        <button
          type="button"
          onClick={reset}
          className="inline-flex min-h-12 items-center rounded-full bg-accent px-6 font-display text-lg font-extrabold uppercase text-on-accent"
        >
          Try again
        </button>
        <Link href="/rules" className="inline-flex min-h-12 items-center rounded-full px-5 font-semibold text-ink-2 hover:text-ink">
          Read the rules
        </Link>
      </div>
    </section>
  );
}
