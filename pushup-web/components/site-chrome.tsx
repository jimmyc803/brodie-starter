"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { JoinButton } from "@/components/join-button";

const NAV = [
  { href: "/", label: "Board" },
  { href: "/rules", label: "Rules" },
  { href: "/setup", label: "Setup" },
  // Web-only fallback (MESSAGING_PROVIDER=web_only): sign in, join and queue on the site.
  ...(process.env.NEXT_PUBLIC_WEB_JOIN === "1" ? [{ href: "/me", label: "My spot" }] : []),
];

export function Logo() {
  return (
    <Link
      href="/"
      className="flex min-h-11 items-center gap-2 rounded-lg"
    >
      <svg viewBox="0 0 32 32" className="size-8" aria-hidden>
        <rect width="32" height="32" rx="8" fill="#d4ff3a" />
        <path d="M7 21.5h18M10 21.5l3-9.5h6l3 9.5M13 12l3-4 3 4" stroke="#0a0b05" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </svg>
      <span className="font-display text-xl font-extrabold uppercase leading-none tracking-wide whitespace-nowrap">
        Brodie<span className="hidden min-[400px]:inline"><span className="text-accent">/</span>Push-Ups</span>
      </span>
    </Link>
  );
}

export function SiteNav({ joinHref }: { joinHref: string | null }) {
  const path = usePathname();
  return (
    <div className="flex items-center gap-1 sm:gap-2">
      <ul className="flex items-center">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <li key={n.href} className={n.href === "/" ? "hidden sm:block" : ""}>
              <Link
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-11 items-center rounded-full px-3 text-sm font-semibold transition-colors ${active ? "text-ink" : "text-ink-2 hover:text-ink"}`}
              >
                {n.label}
                {active ? <span aria-hidden className="ml-1.5 size-1.5 rounded-full bg-accent" /> : null}
              </Link>
            </li>
          );
        })}
      </ul>
      <div className="hidden sm:block">
        <JoinButton href={joinHref} size="sm" label="Join" />
      </div>
    </div>
  );
}

/** Thumb-reach CTA on phones. Hidden on /join, where the page itself is the CTA. */
export function MobileJoinBar({ joinHref }: { joinHref: string | null }) {
  const path = usePathname();
  if (path.startsWith("/join") || path.startsWith("/me") || path.startsWith("/login")) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 bg-gradient-to-t from-canvas via-canvas/85 to-transparent px-4 pt-8 pb-[max(1rem,env(safe-area-inset-bottom))] sm:hidden">
      <JoinButton href={joinHref} size="md" label="Text JOIN to compete" className="pointer-events-auto w-full" />
    </div>
  );
}
