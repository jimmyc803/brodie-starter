"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { JoinButton } from "@/components/join-button";

const NAV = [
  { href: "/", label: "Board" },
  { href: "/rules", label: "Rules" },
  { href: "/how-it-works", label: "How it works", short: "How" },
  { href: "/setup", label: "Setup" },
  // Web-only fallback (MESSAGING_PROVIDER=web_only): sign in, join and queue on the site.
  ...(process.env.NEXT_PUBLIC_WEB_JOIN === "1" ? [{ href: "/me", label: "My spot" }] : []),
];

/** Bill-poster wordmark: stacked type with a pink starburst seal. */
export function Logo() {
  return (
    <Link href="/" className="group flex min-h-11 items-center gap-2.5" aria-label="Brodie Push-Up Challenge, home">
      <svg viewBox="0 0 40 40" className="size-10 shrink-0 transition-transform duration-300 group-hover:rotate-[24deg]" aria-hidden>
        <path
          d="M20 1l3.6 5.1 5.9-2.1.4 6.3 6.1 1.4-2.6 5.7L38 22l-5.6 3 1 6.2-6.3-.3-2.3 5.9L20 33l-4.8 3.8-2.3-5.9-6.3.3 1-6.2L2 22l4.6-4.6L4 11.7l6.1-1.4.4-6.3 5.9 2.1z"
          fill="#ff3d97"
          stroke="#16120e"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        <path d="M11 25h18M13.5 25l2.6-8h7.8l2.6 8M16.1 17l3.9-4.8 3.9 4.8" stroke="#16120e" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      </svg>
      <span className="flex flex-col leading-none">
        <span className="font-display text-[1.65rem] leading-[0.85] uppercase">Brodie</span>
        <span className="hidden font-mono text-[0.6rem] font-bold tracking-[0.2em] uppercase min-[400px]:block">Push-up challenge</span>
      </span>
    </Link>
  );
}

export function SiteNav({ joinHref }: { joinHref: string | null }) {
  const path = usePathname();
  return (
    <div className="flex items-center gap-1 sm:gap-3">
      <ul className="flex items-center">
        {NAV.map((n) => {
          const active = n.href === "/" ? path === "/" : path.startsWith(n.href);
          return (
            <li key={n.href} className={n.href === "/" ? "hidden sm:block" : ""}>
              <Link
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={`relative flex min-h-11 items-center px-2.5 font-mono text-[0.8rem] font-bold tracking-wider uppercase transition-colors sm:px-3 ${active ? "text-ink" : "text-ink-2 hover:text-ink"}`}
              >
                <span className={active ? "highlight" : ""}>
                  {"short" in n && n.short ? (
                    <>
                      <span className="sm:hidden">{n.short}</span>
                      <span className="hidden sm:inline">{n.label}</span>
                    </>
                  ) : (
                    n.label
                  )}
                </span>
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

const TICKER = (prize: string) => [
  "Strict reps only",
  "Ends Tue Oct 20",
  `${prize} to 1st`,
  "FaceTime the line",
  "Judged live, every rep",
  "Power hour pays 2×",
  "Top 3 get the fighter call",
  "No video stored",
];

/** Fight-bill crawl across the top of every page. Decorative; the same facts live on the page. */
export function Ticker({ firstPrize }: { firstPrize: string }) {
  const items = TICKER(firstPrize);
  const run = (
    <span className="flex shrink-0 items-center">
      {items.map((t) => (
        <span key={t} className="flex items-center">
          <span className="px-4">{t}</span>
          <span className="text-pink">✶</span>
        </span>
      ))}
    </span>
  );
  return (
    <div aria-hidden className="overflow-hidden bg-ink py-1.5 text-canvas">
      <div className="flex w-max animate-marquee font-display text-[0.95rem] tracking-wider uppercase">
        {run}
        {run}
      </div>
    </div>
  );
}

/** Thumb-reach CTA on phones. Hidden on /join, where the page itself is the CTA. */
export function MobileJoinBar({ joinHref }: { joinHref: string | null }) {
  const path = usePathname();
  if (path.startsWith("/join") || path.startsWith("/me") || path.startsWith("/login")) return null;
  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-0 z-40 bg-gradient-to-t from-canvas via-canvas/90 to-transparent px-4 pt-8 pb-[max(1rem,env(safe-area-inset-bottom))] sm:hidden">
      <JoinButton href={joinHref} size="md" label="Text JOIN to compete" className="pointer-events-auto w-full" />
    </div>
  );
}
