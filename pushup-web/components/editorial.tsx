import { JoinButton } from "@/components/join-button";

/** Shared building blocks for the editorial pages (/rules, /setup, /join). */

export function PageIntro({
  eyebrow,
  title,
  accent,
  lede,
  art,
}: {
  eyebrow: string;
  title: string;
  accent?: string;
  lede: React.ReactNode;
  art?: React.ReactNode;
}) {
  return (
    <header className="grid items-center gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:gap-12">
      <div className="animate-rise">
        <p className="inline-block border-2 border-ink bg-yellow px-2 py-0.5 font-mono text-xs font-bold tracking-[0.14em] uppercase">{eyebrow}</p>
        <h1 className="mt-4 font-display text-hero uppercase">
          {title}
          {accent ? (
            <>
              {" "}
              <span className="overprint">{accent}</span>
            </>
          ) : null}
        </h1>
        <p className="mt-4 max-w-xl text-lg text-ink-2">{lede}</p>
      </div>
      {art ? <div className="animate-rise [animation-delay:80ms]">{art}</div> : null}
    </header>
  );
}

export function SectionHeading({ id, index, children }: { id?: string; index?: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="flex items-baseline gap-3 font-display text-4xl uppercase sm:text-5xl">
      {index ? (
        <span aria-hidden className="bg-ink px-1.5 font-mono text-sm font-bold text-canvas">
          {index}
        </span>
      ) : null}
      <span>{children}</span>
    </h2>
  );
}

export function StatTile({ value, label, hint }: { value: string; label: string; hint?: string }) {
  return (
    <div className="card p-4 sm:p-5">
      <p className="font-display text-6xl leading-none tabular-nums text-ink sm:text-7xl">{value}</p>
      <p className="mt-2 font-semibold">{label}</p>
      {hint ? <p className="mt-0.5 text-sm text-ink-3">{hint}</p> : null}
    </div>
  );
}

/** Closing call to action used at the bottom of every editorial page. */
export function CtaBand({ joinHref, title, body }: { joinHref: string | null; title: string; body: string }) {
  return (
    <section
      aria-label="Join the challenge"
      className="card relative overflow-hidden bg-blue p-6 text-canvas sm:p-10"
    >
      <div aria-hidden className="halftone-fade absolute -top-16 -right-16 size-80 [--dot:var(--color-pink)]" />
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-display text-5xl leading-[0.9] uppercase sm:text-7xl">{title}</p>
          <p className="mt-3 max-w-md text-canvas/85">{body}</p>
        </div>
        <JoinButton href={joinHref} size="lg" label="Text JOIN" className="w-full sm:w-auto" />
      </div>
    </section>
  );
}
