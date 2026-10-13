import { Brand } from "@/components/ui-kit/brand";

// The one header every page shares: the Brodie mark on the left, where you are / actions on the right.
export function SiteHeader({ context, className = "" }: { context?: React.ReactNode; className?: string }) {
  return (
    <header className={`flex items-center justify-between gap-4 border-b border-line pb-4 ${className}`}>
      <Brand />
      {context ? <div className="flex min-w-0 shrink-0 items-center gap-2 text-sm text-ink-2">{context}</div> : null}
    </header>
  );
}

// Section heading used across pages: sentence case, quiet.
export function SectionHeading({ children, sub, as: Tag = "h2" }: { children: React.ReactNode; sub?: React.ReactNode; as?: "h2" | "h3" }) {
  return (
    <div className="mb-3">
      <Tag className="text-base font-semibold text-ink">{children}</Tag>
      {sub ? <p className="mt-0.5 text-sm text-ink-3">{sub}</p> : null}
    </div>
  );
}
