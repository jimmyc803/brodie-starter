import Link from "next/link";

import { PillLink, Surface } from "@/components/ui/apple";

import { ClientList } from "@/components/coach/client-list";
import { SessionDetail } from "@/components/coach/session-detail";
import { shortDate } from "@/components/coach/format";
import { SiteHeader } from "@/components/site-header";
import type { CoachClient, CoachView } from "@/lib/coach-view";
import { sortSummaries, summarizeClient, type ClientSummary } from "@/lib/coach-status";
import { sessionStats } from "@/lib/recap";
import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";

const STATUS_LABEL: Record<ClientSummary["status"], { text: string; dot: string }> = {
  review: { text: "Needs review", dot: "bg-critical" },
  on_track: { text: "On track", dot: "bg-positive" },
  inactive: { text: "Inactive", dot: "bg-ink-3" },
};

// Coach dashboard (triage inbox): the roster on the left, sorted so clients who need the coach come first;
// the selected client on the right, with what they do next, their session history and the chosen session.
export function CoachDashboard({
  view,
  token,
  selectedClient,
  selectedSession,
  base = `/c/${encodeURIComponent(token)}`,
}: {
  view: CoachView;
  token: string;
  selectedClient: string | null;
  selectedSession: string | null;
  base?: string; // where client/session links point; the lab page overrides it
}) {
  const summaries = sortSummaries(view.clients.map((c) => summarizeClient(c)));
  const bySession = selectedSession ? view.clients.find((c) => c.sessions.some((s) => s.session.share_token === selectedSession)) : undefined;
  const client: CoachClient | undefined =
    view.clients.find((c) => c.id === selectedClient) ?? bySession ?? view.clients.find((c) => c.id === summaries[0]?.id);
  const summary = summaries.find((s) => s.id === client?.id);
  const session = client?.sessions.find((s) => s.session.share_token === selectedSession) ?? client?.sessions[0];

  const sessionsThisWeek = summaries.reduce((n, s) => n + s.thisWeek, 0);
  const toReview = summaries.filter((s) => s.status === "review").length;
  const programsHref = `/c/${encodeURIComponent(token === "demo" ? SAMPLE_COACH_TOKEN : token)}/program`;

  return (
    <>
      <SiteHeader
        context={
          <PillLink href={programsHref} variant="secondary">
            Programs
          </PillLink>
        }
      />
    <div className="mx-auto w-full max-w-[1120px] px-5 pb-16 pt-8 sm:px-6 sm:pt-10">
      <header>
        <h1 className="t-display text-ink">Coach {view.coach.name}</h1>
        <p className="t-callout mt-1 text-ink-2">
          {view.clients.length} {view.clients.length === 1 ? "client" : "clients"} · {sessionsThisWeek}{" "}
          {sessionsThisWeek === 1 ? "session" : "sessions"} this week
          {toReview ? (
            <>
              {" · "}
              <span className="text-critical">
                {toReview} {toReview === 1 ? "needs" : "need"} review
              </span>
            </>
          ) : null}
        </p>
      </header>

      {view.clients.length === 0 ? (
        <Surface className="mt-8 p-8 text-center t-callout text-ink-2">
          <p>No clients yet. Assign a program day to a client and their sessions show up here.</p>
        </Surface>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)] lg:items-start">
          <div className="lg:sticky lg:top-[72px]">
            <ClientList clients={summaries} base={base} selectedId={client?.id ?? null} />
          </div>

          {client && summary ? (
            <div className="min-w-0 space-y-4">
              <ClientHeader client={client} summary={summary} base={base} activeSession={session?.session.share_token ?? null} programsHref={programsHref} />
              {session ? (
                <SessionDetail view={session} clientName={client.name} />
              ) : (
                <Surface className="p-8 text-center t-callout text-ink-2">
                  <p>No sessions yet. When {client.name} finishes a workout with Brodie, it shows up here.</p>
                </Surface>
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
    </>
  );
}

// The selected client: status, what they train next, this week, and their recent sessions as a switcher.
function ClientHeader({
  client,
  summary,
  base,
  activeSession,
  programsHref,
}: {
  client: CoachClient;
  summary: ClientSummary;
  base: string;
  activeSession: string | null;
  programsHref: string;
}) {
  const status = STATUS_LABEL[summary.status];
  return (
    <Surface as="section" className="p-5 sm:p-6">
      <div aria-label={client.name} role="group" className="flex flex-wrap items-center gap-3">
        <h2 className="t-title text-ink">{client.name}</h2>
        <span className="flex items-center gap-1.5 t-footnote text-ink-2">
          <span className={`size-2 rounded-full ${status.dot}`} aria-hidden />
          {status.text}
        </span>
      </div>

      <dl className="mt-5 grid gap-4 sm:grid-cols-3 sm:divide-x sm:divide-hairline">
        <div className="sm:pr-4">
          <dt className="t-footnote text-ink-2">Next up</dt>
          <dd className="mt-0.5 flex items-baseline justify-between gap-2">
            <span className="truncate t-headline text-ink">{client.next ?? "Nothing assigned"}</span>
            <Link href={programsHref} className="shrink-0 t-footnote text-accent hover:underline">
              Change
            </Link>
          </dd>
        </div>
        <div className="sm:px-4">
          <dt className="t-footnote text-ink-2">This week</dt>
          <dd className="mt-0.5 t-headline text-ink">
            {summary.thisWeek} {summary.thisWeek === 1 ? "session" : "sessions"}
          </dd>
        </div>
        <div className="sm:pl-4">
          <dt className="t-footnote text-ink-2">Last session</dt>
          <dd className="mt-0.5 truncate t-headline text-ink">{summary.detail}</dd>
        </div>
      </dl>

      {client.sessions.length > 1 ? (
        <div className="mt-5 border-t border-hairline pt-4">
          <p className="mb-2 t-footnote text-ink-2">Sessions</p>
          <ul className="flex gap-2 overflow-x-auto pb-1">
            {client.sessions.map((s) => {
              const st = sessionStats(s);
              const active = s.session.share_token === activeSession;
              return (
                <li key={s.session.share_token} className="shrink-0">
                  <Link
                    href={`${base}?c=${encodeURIComponent(client.id)}&s=${encodeURIComponent(s.session.share_token)}#session`}
                    aria-current={active ? "true" : undefined}
                    className={`block rounded-full px-3.5 py-1.5 t-footnote transition-colors ${
                      active ? "bg-accent-fill text-white" : "bg-fill text-ink-2 hover:text-ink"
                    } ${st.completed === 0 && !active ? "opacity-60" : ""}`}
                  >
                    <span className="font-medium">{shortDate(s.session.started_at)}</span>
                    <span className={active ? "text-white/80" : "text-ink-3"}> · {st.completed}/{st.planned} reps</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </Surface>
  );
}
