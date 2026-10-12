import type { Loaded } from "../_lib/data";

export function Section({ title, aside, children }: { title: string; aside?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-hairline bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xs font-bold uppercase tracking-widest text-ink-2">{title}</h2>
        {aside && <div className="text-xs text-ink-2">{aside}</div>}
      </div>
      {children}
    </section>
  );
}

export function ErrorBox({ error }: { error: string }) {
  return (
    <p role="alert" className="rounded-md border border-bad/60 bg-bad/10 px-2 py-1.5 text-xs font-semibold text-bad">
      {error}
    </p>
  );
}

/** Render a loaded value or its error. */
export function Show<T>({ loaded, children }: { loaded: Loaded<T>; children: (data: T) => React.ReactNode }) {
  return loaded.ok ? <>{children(loaded.data)}</> : <ErrorBox error={loaded.error} />;
}

export function Table({ head, children, empty }: { head: string[]; children: React.ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-xs">
        <thead>
          <tr className="border-b border-hairline text-ink-2">
            {head.map((h) => (
              <th key={h} className="px-2 py-1.5 font-semibold whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="[&>tr]:border-b [&>tr]:border-hairline/50 [&_td]:px-2 [&_td]:py-1.5 [&_td]:align-top">
          {children}
        </tbody>
      </table>
      {empty && <p className="px-2 py-3 text-xs text-ink-2">Nothing here.</p>}
    </div>
  );
}

const fmt = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

/** Timestamp in ET (the competition's day logic), compact. */
export function Time({ at }: { at: string | null | undefined }) {
  if (!at) return <span className="text-ink-2">-</span>;
  const d = new Date(at);
  if (Number.isNaN(d.getTime())) return <span>{at}</span>;
  return (
    <time dateTime={at} title={at} className="tabular-nums whitespace-nowrap">
      {fmt.format(d)} ET
    </time>
  );
}

export function Pill({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "neutral" | "good" | "bad" }) {
  const cls =
    tone === "good"
      ? "bg-accent text-on-accent"
      : tone === "bad"
        ? "bg-bad text-canvas"
        : "bg-surface-2 text-ink-2";
  return <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] font-bold uppercase ${cls}`}>{children}</span>;
}

export function Mono({ children }: { children: React.ReactNode }) {
  return <span className="font-mono text-[11px] break-all text-ink-2">{children}</span>;
}
