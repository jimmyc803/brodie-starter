import Link from "next/link";

/** Shared building blocks for the long-form pages (/rules, /privacy, /terms, /how-it-works). */

export function Bullets({ items }: { items: React.ReactNode[] }) {
  return (
    <ul className="space-y-3">
      {items.map((item, i) => (
        <li key={i} className="flex gap-3 text-ink-2">
          <span aria-hidden className="mt-1 font-display text-pink">✶</span>
          <span className="leading-relaxed">{item}</span>
        </li>
      ))}
    </ul>
  );
}

export function P({ children }: { children: React.ReactNode }) {
  return <p className="leading-relaxed text-ink-2">{children}</p>;
}

/** A numbered section with the big heading in a left column on wide screens. */
export function Section({ id, index, title, children }: { id: string; index: string; title: string; children: React.ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-4 border-t border-hairline pt-8 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
      <h2 id={id} className="flex items-baseline gap-3 self-start font-display text-3xl uppercase sm:text-4xl">
        <span aria-hidden className="bg-ink px-1.5 font-mono text-sm font-bold text-canvas">
          {index}
        </span>
        <span>{title}</span>
      </h2>
      <div className="prose-brodie min-w-0 space-y-4">{children}</div>
    </section>
  );
}

export function Toc({ items }: { items: readonly (readonly [string, string])[] }) {
  return (
    <nav aria-label="On this page" className="-mx-4 overflow-x-auto px-4 [scrollbar-width:none] sm:mx-0 sm:px-0">
      <ul className="flex w-max gap-2 sm:w-auto sm:flex-wrap">
        {items.map(([id, label]) => (
          <li key={id}>
            <a
              href={`#${id}`}
              className="inline-flex min-h-11 items-center border-2 border-ink bg-surface px-3 font-mono text-xs font-bold tracking-wider whitespace-nowrap text-ink uppercase transition-colors hover:bg-yellow"
            >
              {label}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

/** "The gist" box at the top of a legal page. */
export function Gist({ title = "The gist", items, note }: { title?: string; items: React.ReactNode[]; note?: React.ReactNode }) {
  return (
    <aside aria-label={title} className="card relative overflow-hidden bg-yellow p-5 sm:p-7">
      <p className="inline-block border-2 border-ink bg-canvas px-2 py-0.5 font-mono text-xs font-bold tracking-[0.14em] uppercase">{title}</p>
      <ul className="mt-4 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {items.map((item, i) => (
          <li key={i} className="flex gap-3 leading-snug text-ink">
            <span aria-hidden className="font-display text-ink">✶</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
      {note ? <p className="mt-4 border-t-2 border-ink/30 pt-3 text-sm text-ink">{note}</p> : null}
    </aside>
  );
}

/** Collapsible question and answer; works without JavaScript. */
export function Faq({ q, children }: { q: string; children: React.ReactNode }) {
  return (
    <details className="card-flat group bg-surface">
      <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between gap-4 px-4 py-3 font-semibold marker:hidden [&::-webkit-details-marker]:hidden">
        <span>{q}</span>
        <span aria-hidden className="font-display text-2xl leading-none text-accent transition-transform group-open:rotate-45">+</span>
      </summary>
      <div className="prose-brodie space-y-3 border-t border-hairline px-4 py-3">{children}</div>
    </details>
  );
}

/** The cross-links shown at the bottom of every long-form page. */
export function DocLinks({ current }: { current: string }) {
  const links = [
    ["/rules", "Official rules"],
    ["/how-it-works", "How it works"],
    ["/setup", "Camera setup"],
    ["/privacy", "Privacy policy"],
    ["/terms", "Terms of use"],
  ];
  return (
    <ul aria-label="Related pages" className="flex flex-wrap gap-2">
      {links
        .filter(([href]) => href !== current)
        .map(([href, label]) => (
          <li key={href}>
            <Link
              href={href}
              className="inline-flex min-h-11 items-center border-2 border-ink bg-surface px-3 font-mono text-xs font-bold tracking-wider text-ink uppercase transition-colors hover:bg-yellow"
            >
              {label}
            </Link>
          </li>
        ))}
    </ul>
  );
}

export const EFFECTIVE = "October 13, 2026";
