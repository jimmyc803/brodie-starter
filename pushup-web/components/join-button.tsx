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
    sm: "min-h-11 px-4 text-base gap-2",
    md: "min-h-13 px-6 text-xl gap-2.5",
    lg: "min-h-16 px-7 text-2xl gap-3",
  } as const;
  const cls = `group inline-flex items-center justify-center rounded-full bg-accent font-display font-extrabold uppercase tracking-wide text-on-accent shadow-[0_0_0_1px_rgb(212_255_58/0.4),0_10px_40px_-10px_rgb(212_255_58/0.55)] transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-[0_0_0_1px_rgb(212_255_58/0.6),0_14px_50px_-8px_rgb(212_255_58/0.7)] active:translate-y-0 ${sizes[size]} ${className}`;
  const inner = (
    <>
      <MessageIcon className={size === "sm" ? "size-4" : "size-5"} />
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
