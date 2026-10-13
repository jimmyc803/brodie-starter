import Link from "next/link";

export default function NotFound() {
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center py-16 text-center">
      <p aria-hidden className="font-display text-[11rem] leading-[0.85] overprint">404</p>
      <h1 className="mt-4 font-display text-5xl uppercase">No rep. Page not found.</h1>
      <p className="mt-3 text-ink-2">That page isn&apos;t on the board. Head back and check the standings.</p>
      <Link
        href="/"
        className="mt-7 press inline-flex min-h-12 items-center rounded-[var(--radius-card)] border-2 border-ink bg-pink px-6 font-display text-xl uppercase text-ink"
      >
        Back to the board
      </Link>
    </section>
  );
}
