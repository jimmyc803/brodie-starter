import Link from "next/link";
import { FileText, LayoutDashboard, Users } from "lucide-react";

import { Brand } from "@/components/ui-kit/brand";

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
    <div className="flex min-h-dvh flex-1 flex-col bg-canvas text-ink lg:flex-row">
      <aside className="border-b border-line lg:bg-sunken/60 lg:sticky lg:top-0 lg:flex lg:h-dvh lg:w-60 lg:shrink-0 lg:flex-col lg:border-b-0 lg:border-r lg:border-line">
        <div className="flex items-center justify-between gap-4 px-4 py-4 lg:px-5 lg:py-6">
          <Brand />
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
                className={`flex shrink-0 items-center gap-3 rounded-[10px] px-3 py-2 text-sm transition-colors ${
                  on ? "bg-surface font-semibold text-ink shadow-[0_0_0_1px_var(--color-line)]" : "text-ink-2 hover:bg-surface/70 hover:text-ink"
                }`}
              >
                <Icon className="size-4" aria-hidden />
                {it.label}
                {it.badge ? (
                  <span className="ml-auto rounded-full bg-bad-soft px-1.5 text-xs font-semibold tabular-nums text-bad">{it.badge}</span>
                ) : null}
              </Link>
            );
          })}
        </nav>
        <div className="mt-auto hidden items-center gap-3 border-t border-line px-5 py-4 lg:flex">
          <span className="grid size-8 place-items-center rounded-full bg-surface text-sm font-semibold text-ink-2">
            {coachName.charAt(0).toUpperCase()}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">Coach {coachName}</p>
            <p className="text-xs text-ink-3">Private coach link</p>
          </div>
        </div>
      </aside>
      <div className="min-w-0 flex-1">
        <div className="mx-auto w-full max-w-6xl px-4 pb-12 pt-6 sm:px-6 lg:px-8 lg:pt-8">{children}</div>
      </div>
    </div>
  );
}
