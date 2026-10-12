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
        <p className="eyebrow text-accent">{eyebrow}</p>
        <h1 className="mt-3 font-display text-hero font-extrabold uppercase italic tracking-tight">
          {title}
          {accent ? (
            <>
              {" "}
              <span className="text-accent">{accent}</span>
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
    <h2 id={id} className="flex items-baseline gap-3 font-display text-3xl font-extrabold uppercase sm:text-4xl">
      {index ? (
        <span aria-hidden className="font-mono text-base font-bold text-accent">
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
      <p className="font-display text-5xl font-extrabold leading-none tabular-nums text-ink sm:text-6xl">{value}</p>
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
      className="relative overflow-hidden rounded-[var(--radius-card)] border border-accent/40 bg-[radial-gradient(40rem_16rem_at_100%_0%,rgb(212_255_58/0.18),transparent_70%)] bg-surface p-6 sm:p-10"
    >
      <div className="relative flex flex-col gap-5 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="font-display text-4xl font-extrabold uppercase italic leading-none sm:text-5xl">{title}</p>
          <p className="mt-2 max-w-md text-ink-2">{body}</p>
        </div>
        <JoinButton href={joinHref} size="lg" label="Text JOIN" className="w-full sm:w-auto" />
      </div>
    </section>
  );
}
