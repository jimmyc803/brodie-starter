import type { Metadata } from "next";
import Link from "next/link";
import { requireAdmin } from "@/lib/admin";
import { signOut } from "../actions";

export const metadata: Metadata = { title: "Admin · Brodie Push-Ups", robots: { index: false, follow: false } };

const sections = [
  { href: "/admin", label: "Line & queue" },
  { href: "/admin/users", label: "Users & scores" },
  { href: "/admin/calls", label: "Calls" },
  { href: "/admin/config", label: "Config" },
  { href: "/admin/broadcast", label: "Broadcast" },
  { href: "/admin/rejudge", label: "Rejudge" },
  { href: "/admin/raffle", label: "Raffle" },
  { href: "/admin/highlights", label: "Highlights" },
  { href: "/admin/health", label: "Health" },
];

// Layout gating is convenience only; every page and every server action re-runs the allowlist check itself.
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const { email } = await requireAdmin();
  return (
    <div className="relative left-1/2 w-[min(80rem,calc(100vw-2rem))] -translate-x-1/2 text-sm">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2 border-b border-hairline pb-3">
        <h1 className="font-display text-2xl uppercase tracking-wide text-accent">Admin console</h1>
        <form action={signOut} className="flex items-center gap-3 text-xs text-ink-2">
          <span>{email}</span>
          <button type="submit" className="rounded-md border border-hairline px-2 py-1 font-semibold hover:border-accent">
            Sign out
          </button>
        </form>
      </div>
      <div className="grid gap-4 md:grid-cols-[11rem_1fr]">
        <nav aria-label="Admin">
          <ul className="flex flex-wrap gap-1 md:flex-col">
            {sections.map((s) => (
              <li key={s.href}>
                <Link
                  href={s.href}
                  className="block rounded-md px-2 py-1.5 font-semibold text-ink-2 hover:bg-surface-2 hover:text-accent"
                >
                  {s.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <div className="min-w-0 space-y-6">{children}</div>
      </div>
    </div>
  );
}
