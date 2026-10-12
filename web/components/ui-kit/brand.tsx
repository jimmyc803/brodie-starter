import Link from "next/link";

// The Brodie wordmark: an orange square and the name. The one place brand orange always appears.
export function Brand({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 text-base font-bold tracking-[-0.02em] text-ink">
      <span aria-hidden className="size-3.5 rounded-[4px] bg-brand" />
      Brodie
    </Link>
  );
}
