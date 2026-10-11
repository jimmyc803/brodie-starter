import Link from "next/link";

// The one header every page shares: the Brodie wordmark on the left, where you are on the right.
// Full-bleed: pages render it as the first child of <main>, outside their width container.
export function SiteHeader({ context, className = "" }: { context?: React.ReactNode; className?: string }) {
  return (
    <header
      className={`sticky top-0 z-40 w-full border-b border-hairline bg-black/70 backdrop-blur-xl backdrop-saturate-150 ${className}`}
    >
      <div className="mx-auto flex h-[52px] max-w-[980px] items-center justify-between gap-4 px-5 sm:px-6">
        <Link href="/" className="t-headline shrink-0 text-ink">
          Brodie <span className="font-normal text-ink-3">for Coaches</span>
        </Link>
        {context ? <div className="min-w-0 truncate t-footnote text-ink-2">{context}</div> : null}
      </div>
    </header>
  );
}

// Section heading used across pages: sentence case, quiet, no tracking-widest caps.
export function SectionHeading({ children, sub, as: Tag = "h2" }: { children: React.ReactNode; sub?: React.ReactNode; as?: "h2" | "h3" }) {
  return (
    <div className="mb-4">
      <Tag className="t-title-2 text-ink">{children}</Tag>
      {sub ? <p className="mt-1 t-callout text-ink-2">{sub}</p> : null}
    </div>
  );
}
