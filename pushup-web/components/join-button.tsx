import Link from "next/link";
import { MessageIcon } from "@/components/ui/icons";

/**
 * The one primary CTA. Opens Messages with "JOIN " pre-filled when the number is published,
 * otherwise routes to /join (which explains the state).
 */
export function JoinButton({
  href,
  size = "md",
  label = "Text JOIN",
  className = "",
}: {
  href: string | null;
  size?: "sm" | "md" | "lg";
  label?: string;
  className?: string;
}) {
  const sizes = {
    sm: "min-h-11 px-4 text-lg gap-2",
    md: "min-h-14 px-6 text-2xl gap-2.5",
    lg: "min-h-16 px-7 text-[1.75rem] gap-3",
  } as const;
  const cls = `press group inline-flex items-center justify-center rounded-[var(--radius-card)] border-2 border-ink bg-pink font-display uppercase tracking-wide text-ink ${sizes[size]} ${className}`;
  const inner = (
    <>
      <MessageIcon className={`${size === "sm" ? "size-4" : "size-5"} transition-transform group-hover:-rotate-12`} />
      <span>{label}</span>
    </>
  );
  return href ? (
    <a href={href} className={cls}>
      {inner}
    </a>
  ) : (
    <Link href="/join" className={cls}>
      {inner}
    </Link>
  );
}
