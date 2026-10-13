import Link from "next/link";

import { BrodieHead } from "@/components/ui-kit/brodie";

// The Brodie wordmark: his head on a brand-orange disc and the name. The one place brand orange always appears.
export function Brand({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 text-base font-bold tracking-[-0.02em] text-ink">
      <BrodieHead size={24} />
      Brodie
    </Link>
  );
}
