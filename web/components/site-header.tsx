import Link from "next/link";

// The one header every page shares: the Brodie wordmark on the left, where you are on the right.
export function SiteHeader({ context, className = "" }: { context?: React.ReactNode; className?: string }) {
  return (
    <header className={`flex items-center justify-between gap-4 border-b border-zinc-800/80 pb-4 ${className}`}>
      <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight text-zinc-100">
        <span aria-hidden className="grid size-6 place-items-center rounded-md bg-green-500 text-[13px] font-bold text-zinc-950">
          B
        </span>
        Brodie <span className="font-normal text-zinc-500">for Coaches</span>
      </Link>
      {context ? <div className="min-w-0 shrink-0 text-sm text-zinc-400">{context}</div> : null}
    </header>
  );
}

// Section heading used across pages: sentence case, quiet, no tracking-widest caps.
export function SectionHeading({ children, sub, as: Tag = "h2" }: { children: React.ReactNode; sub?: React.ReactNode; as?: "h2" | "h3" }) {
  return (
    <div className="mb-3">
      <Tag className="text-base font-semibold text-zinc-100">{children}</Tag>
      {sub ? <p className="mt-0.5 text-sm text-zinc-500">{sub}</p> : null}
    </div>
  );
}
