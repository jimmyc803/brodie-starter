import Link from "next/link";

export default function NotFound() {
  return (
    <section className="mx-auto flex max-w-xl flex-col items-center py-16 text-center">
      <p aria-hidden className="font-display text-[8rem] font-extrabold italic leading-none text-accent">404</p>
      <h1 className="mt-2 font-display text-4xl font-extrabold uppercase">No rep. Page not found.</h1>
      <p className="mt-3 text-ink-2">That page isn&apos;t on the board. Head back and check the standings.</p>
      <Link
        href="/"
        className="mt-6 inline-flex min-h-12 items-center rounded-full bg-accent px-6 font-display text-lg font-extrabold uppercase text-on-accent"
      >
        Back to the board
      </Link>
    </section>
  );
}
