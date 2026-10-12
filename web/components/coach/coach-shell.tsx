import Link from "next/link";
import { FileText, LayoutDashboard, Users } from "lucide-react";

import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";

export type CoachSection = "overview" | "clients" | "programs";

// Links for the three coach pages. The public "demo" alias opens Tristan; his programs page lives under his real token.
export function coachLinks(token: string) {
  const t = encodeURIComponent(token);
  const programs = encodeURIComponent(token === "demo" ? SAMPLE_COACH_TOKEN : token);
  return { overview: `/c/${t}`, clients: `/c/${t}/clients`, programs: `/c/${programs}/program` };
}

// The coach app frame: a sidebar (top bar on phones) with Overview / Clients / Programs, and the page beside it.
export function CoachShell({
  token,
  coachName,
  active,
  needReview = 0,
  children,
}: {
  token: string;
  coachName: string;
  active: CoachSection;
  needReview?: number;
  children: React.ReactNode;
}) {
  const links = coachLinks(token);
  const items: { key: CoachSection; label: string; href: string; icon: typeof Users; badge?: number }[] = [
    { key: "overview", label: "Overview", href: links.overview, icon: LayoutDashboard },
    { key: "clients", label: "Clients", href: links.clients, icon: Users, badge: needReview || undefined },
    { key: "programs", label: "Programs", href: links.programs, icon: FileText },
  ];
  return (
    <div className="flex min-h-dvh flex-1 flex-col bg-zinc-950 text-zinc-100 lg:flex-row">
      <aside className="border-b border-zinc-800/80 lg:sticky lg:top-0 lg:flex lg:h-dvh lg:w-60 lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-4 px-4 py-4 lg:px-5 lg:py-6">
          <Link href="/" className="flex items-center gap-2 text-sm font-semibold tracking-tight">
            <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-green-500 text-sm font-bold text-zinc-950">
              B
            </span>
            Brodie <span className="font-normal text-zinc-500">for Coaches</span>
          </Link>
        </div>
        <nav aria-label="Coach" className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:px-3 lg:pb-0">
          {items.map((it) => {
            const on = it.key === active;
            const Icon = it.icon;
            return (
              <Link
                key={it.key}
                href={it.href}
                aria-current={on ? "page" : undefined}
                className={`flex shrink-0 items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                  on ? "bg-zinc-800/80 font-medium text-zinc-50" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-100"
                }`}
              >
                <Icon className="size-4" aria-hidden />
                {it.label}
                {it.badge ? (
                  <span className="ml-auto rounded-full bg-red-500/15 px-1.5 text-xs font-medium tabular-nums text-red-300">{it.badge}</span>
                ) : null}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto hidden items-center gap-3 border-t border-zinc-800/80 px-5 py-4 lg:flex">
          <span className="grid size-8 place-items-center rounded-full bg-zinc-800 text-sm font-medium text-zinc-200">
            {coachName.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-zinc-100">Coach {coachName}</p>
            <p className="text-xs text-zinc-500">Private coach link</p>
          </div>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-6 sm:px-6 lg:px-8 lg:pt-8">{children}</div>
      </div>
    </div>
  );
}
