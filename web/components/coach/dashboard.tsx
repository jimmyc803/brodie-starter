import Link from "next/link";

import { BrodieEmpty } from "@/components/ui-kit/brodie";
import { ClientList } from "@/components/coach/client-list";
import { AddClient } from "@/components/coach/add-client";
import { ClientLink } from "@/components/coach/client-link";
import { ManageClient } from "@/components/coach/manage-client";
import { SessionDetail } from "@/components/coach/session-detail";
import { canManageClients } from "@/lib/coach-access";
import { ReviewBanner } from "@/components/coach/review-banner";
import { shortDate } from "@/components/coach/format";
import type { CoachClient, CoachView } from "@/lib/coach-view";
import { completedReps, type ExerciseClip } from "@/lib/contract";
import { coachOverview } from "@/lib/coach-overview";
import { sortSummaries, summarizeClient, type ClientSummary } from "@/lib/coach-status";
import { sessionStats } from "@/lib/recap";
import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";

const STATUS_LABEL: Record<ClientSummary["status"], { text: string; className: string }> = {
  review: { text: "Needs review", className: "bg-bad-soft text-bad" },
  on_track: { text: "On track", className: "bg-good-soft text-good" },
  inactive: { text: "Inactive", className: "bg-idle-soft text-ink-2" },
};

// Which client and session the dashboard shows for ?c= / ?s= (the page also uses it to load that session's footage).
export function pickSelection(view: CoachView, selectedClient: string | null, selectedSession: string | null) {
  const summaries = sortSummaries(view.clients.map((c) => summarizeClient(c)));
  const bySession = selectedSession ? view.clients.find((c) => c.sessions.some((s) => s.session.share_token === selectedSession)) : undefined;
  const client: CoachClient | undefined =
    view.clients.find((c) => c.id === selectedClient) ?? bySession ?? view.clients.find((c) => c.id === summaries[0]?.id);
  // With no session picked, open the newest one that has reps: an empty test call shouldn't hide the real workout.
  const hasReps = (s: CoachClient["sessions"][number]) => s.exercises.some((ex) => completedReps(ex) > 0);
  const session =
    client?.sessions.find((s) => s.session.share_token === selectedSession) ?? client?.sessions.find(hasReps) ?? client?.sessions[0];
  return { summaries, client, session };
}

// Coach dashboard (triage inbox): the roster on the left, sorted so clients who need the coach come first;
// the selected client on the right, with what they do next, their session history and the chosen session.
export function CoachDashboard({
  view,
  token,
  selectedClient,
  selectedSession,
  clips,
  base = `/c/${encodeURIComponent(token)}/clients`,
}: {
  view: CoachView;
  token: string;
  selectedClient: string | null;
  selectedSession: string | null;
  clips?: ExerciseClip[]; // workout footage for the shown session (see pickSelection), for the tap-a-muscle video
  base?: string; // where client/session links point; the lab page overrides it
}) {
  const { summaries, client, session } = pickSelection(view, selectedClient, selectedSession);
  // The public demo coach is view-only: no adding clients and no client workout links on show.
  const canEdit = canManageClients(token, view.coach.status);
  const summary = summaries.find((s) => s.id === client?.id);

  // Workouts with reps in the last 7 days: the same count as the Overview (empty test calls don't count).
  const sessionsThisWeek = coachOverview(view).sessionsThisWeek;
  const toReview = summaries.filter((s) => s.status === "review").length;
  const programsHref = `/c/${encodeURIComponent(token === "demo" ? SAMPLE_COACH_TOKEN : token)}/program`;

  return (
    <div>
      <header>
        <h1 className="text-[28px] font-semibold tracking-[-0.025em] text-ink">Clients</h1>
        <p className="mt-1 text-sm text-ink-2">
          {view.clients.length} {view.clients.length === 1 ? "client" : "clients"} · {sessionsThisWeek}{" "}
          {sessionsThisWeek === 1 ? "workout" : "workouts"} this week
          {toReview ? (
            <>
              {" · "}
              <span className="text-bad">
                {toReview} {toReview === 1 ? "needs" : "need"} review
              </span>
            </>
          ) : null}
        </p>
      </header>
      {view.coach.status !== "approved" ? (
        <div className="mt-6">
          <ReviewBanner status={view.coach.status} />
        </div>
      ) : null}

      {view.clients.length === 0 ? (
        <BrodieEmpty title="No clients yet." className="mt-8">
          <p className="mt-1 text-sm text-ink-2">Add your first client, assign them a day, then send them their workout link.</p>
          {canEdit ? (
            <div className="mx-auto mt-5 max-w-xs text-left">
              <AddClient token={token} base={base} />
            </div>
          ) : null}
        </BrodieEmpty>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)] lg:items-start">
          <div className="lg:sticky lg:top-6">
            <ClientList clients={summaries} base={base} selectedId={client?.id ?? null} addToken={canEdit ? token : undefined} />
          </div>

          {client && summary ? (
            <div className="min-w-0 space-y-4">
              <ClientHeader client={client} summary={summary} base={base} activeSession={session?.session.share_token ?? null} programsHref={programsHref} coachName={view.coach.name} showLink={canEdit} editToken={canEdit ? token : undefined} />
              {session ? (
                <SessionDetail view={session} clientName={client.name} clips={clips} programHref={programsHref} />
              ) : (
                <BrodieEmpty title="No sessions yet.">
                  <p className="mt-1 text-sm text-ink-2">When {client.name} finishes a workout with Brodie, it shows up here.</p>
                </BrodieEmpty>
              )}
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}

// The selected client: status, what they train next, this week, and their recent sessions as a switcher.
function ClientHeader({
  client,
  summary,
  base,
  activeSession,
  programsHref,
  coachName,
  showLink,
  editToken,
}: {
  client: CoachClient;
  summary: ClientSummary;
  base: string;
  activeSession: string | null;
  programsHref: string;
  coachName: string;
  showLink: boolean;
  editToken?: string;
}) {
  const status = STATUS_LABEL[summary.status];
  return (
    <section aria-label={client.name} className="rounded-[14px] border border-line bg-surface p-5 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-10 place-items-center rounded-full bg-sunken text-base font-semibold text-ink-2">
          {client.name.charAt(0).toUpperCase()}
        </span>
        <h2 className="min-w-0 break-words text-[26px] font-semibold tracking-[-0.025em] text-ink [overflow-wrap:anywhere]">{client.name}</h2>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${status.className}`}>{status.text}</span>
        {editToken ? <ManageClient key={client.id} token={editToken} clientId={client.id} name={client.name} base={base} /> : null}
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-[10px] bg-sunken/60 px-4 py-3">
          <dt className="text-[12.5px] font-medium text-ink-3">Next up</dt>
          <dd className="mt-0.5 flex items-baseline justify-between gap-2">
            <span className="truncate text-sm font-semibold text-ink">{client.next ?? "Nothing assigned"}</span>
            <Link href={programsHref} className="shrink-0 text-xs text-ink-3 hover:text-ink">
              Change
            </Link>
          </dd>
        </div>
        <div className="rounded-[10px] bg-sunken/60 px-4 py-3">
          <dt className="text-[12.5px] font-medium text-ink-3">This week</dt>
          <dd className="mt-0.5 text-sm font-semibold text-ink">
            {summary.thisWeek} {summary.thisWeek === 1 ? "session" : "sessions"}
          </dd>
        </div>
        <div className="rounded-[10px] bg-sunken/60 px-4 py-3">
          <dt className="text-[12.5px] font-medium text-ink-3">Last session</dt>
          <dd className="mt-0.5 truncate text-sm font-semibold text-ink">{summary.detail}</dd>
        </div>
      </dl>

      {showLink && client.link ? (
        <div className="mt-3">
          <ClientLink code={client.link} name={client.name} coachName={coachName} />
        </div>
      ) : null}

      {client.sessions.length > 1 ? (
        <div className="mt-4">
          <p className="mb-2 text-[12.5px] font-medium text-ink-3">Sessions</p>
          <ul className="flex gap-2 overflow-x-auto pb-1">
            {client.sessions.map((s) => {
              const st = sessionStats(s);
              const active = s.session.share_token === activeSession;
              return (
                <li key={s.session.share_token} className="shrink-0">
                  <Link
                    href={`${base}?c=${encodeURIComponent(client.id)}&s=${encodeURIComponent(s.session.share_token)}#session`}
                    aria-current={active ? "true" : undefined}
                    className={`block rounded-[10px] border px-3 py-1.5 text-xs transition-colors ${
                      active ? "border-ink/30 bg-sunken text-ink" : "border-line text-ink-2 hover:border-line-strong"
                    } ${st.completed === 0 && !active ? "opacity-50" : ""}`}
                  >
                    <span className="font-semibold">{shortDate(s.session.started_at)}</span>
                    <span className="text-ink-3"> · {st.completed}/{st.planned} reps</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
