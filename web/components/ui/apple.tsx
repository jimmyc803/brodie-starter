import Link from "next/link";

// Apple-style building blocks shared by every page. Server-safe (no client hooks).

type Children = { children?: React.ReactNode; className?: string };

// A white rounded card on the canvas.
export function Surface({ className = "", children, as: Tag = "div" }: Children & { as?: "div" | "section" | "li" | "article" }) {
  return <Tag className={`rounded-[18px] border border-hairline bg-surface ${className}`}>{children}</Tag>;
}

// The always-black tile for the heat map and media, so neon/rank colors read exactly as designed.
export function Stage({ className = "", children }: Children) {
  return <div className={`rounded-[24px] border border-hairline bg-stage text-on-stage ${className}`}>{children}</div>;
}

const PILL_VARIANT = {
  primary: "bg-accent-fill text-white hover:bg-accent-fill-hover",
  secondary: "bg-fill text-ink hover:bg-white/[.12]",
  plain: "text-accent hover:underline underline-offset-4",
} as const;

const PILL_SIZE = {
  md: "h-9 px-4 t-callout",
  lg: "h-11 px-6 t-body",
} as const;

// A rounded pill link. "plain" is a bare accent text link with no pill padding.
export function PillLink({
  href,
  variant = "primary",
  size = "md",
  children,
  className = "",
}: {
  href: string;
  variant?: "primary" | "secondary" | "plain";
  size?: "md" | "lg";
  children?: React.ReactNode;
  className?: string;
}) {
  const shape = variant === "plain" ? (size === "lg" ? "t-body" : "t-callout") : `${PILL_SIZE[size]} rounded-full`;
  return (
    <Link
      href={href}
      className={`inline-flex items-center justify-center gap-1.5 whitespace-nowrap font-medium transition-colors ${shape} ${PILL_VARIANT[variant]} ${className}`}
    >
      {children}
    </Link>
  );
}

// A big tabular number with a quiet unit and a label under it.
export function Stat({
  value,
  suffix,
  label,
  className = "",
}: {
  value: React.ReactNode;
  suffix?: React.ReactNode;
  label: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={className}>
      <div className="t-title tabular-nums text-ink">
        {value}
        {suffix ? <span className="ml-0.5 text-ink-3">{suffix}</span> : null}
      </div>
      <div className="mt-1 t-footnote text-ink-2">{label}</div>
    </div>
  );
}

// A small sentence-case label above a headline.
export function Eyebrow({ children }: { children?: React.ReactNode }) {
  return <p className="t-callout font-semibold text-ink-2">{children}</p>;
}
