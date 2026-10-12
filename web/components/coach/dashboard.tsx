import Link from "next/link";

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
  review: { text: "Needs review", className: "bg-red-500/10 text-red-300" },
  on_track: { text: "On track", className: "bg-green-500/10 text-green-300" },
  inactive: { text: "Inactive", className: "bg-zinc-800 text-zinc-400" },
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
        <h1 className="text-3xl font-bold tracking-tight text-zinc-50">Clients</h1>
        <p className="mt-1 text-sm text-zinc-400">
          {view.clients.length} {view.clients.length === 1 ? "client" : "clients"} · {sessionsThisWeek}{" "}
          {sessionsThisWeek === 1 ? "workout" : "workouts"} this week
          {toReview ? (
            <>
              {" · "}
              <span className="text-red-300">
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
        <div className="mt-8 rounded-2xl border border-dashed border-zinc-800 p-8 text-center">
          <p className="text-zinc-300">No clients yet.</p>
          <p className="mt-1 text-sm text-zinc-500">Add your first client, assign them a day, then send them their workout link.</p>
          {canEdit ? (
            <div className="mx-auto mt-5 max-w-xs text-left">
              <AddClient token={token} base={base} />
            </div>
          ) : null}
        </div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,280px)_minmax(0,1fr)] lg:items-start">
          <div className="lg:sticky lg:top-6">
            <ClientList clients={summaries} base={base} selectedId={client?.id ?? null} addToken={canEdit ? token : undefined} />
          </div>

          {client && summary ? (
            <div className="min-w-0 space-y-4">
              <ClientHeader client={client} summary={summary} base={base} activeSession={session?.session.share_token ?? null} programsHref={programsHref} coachName={view.coach.name} showLink={canEdit} editToken={canEdit ? token : undefined} />
              {session ? (
                <SessionDetail view={session} clientName={client.name} clips={clips} programHref={programsHref} />
              ) : (
                <p className="rounded-2xl border border-dashed border-zinc-800 p-8 text-center text-zinc-400">
                  No sessions yet. When {client.name} finishes a workout with Brodie, it shows up here.
                </p>
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
    <section aria-label={client.name} className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5 sm:p-6">
      <div className="flex flex-wrap items-center gap-3">
        <span className="grid size-10 place-items-center rounded-full bg-zinc-800 text-base font-semibold text-zinc-200">
          {client.name.charAt(0).toUpperCase()}
        </span>
        <h2 className="text-xl font-semibold text-zinc-50">{client.name}</h2>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${status.className}`}>{status.text}</span>
        {editToken ? <ManageClient key={client.id} token={editToken} clientId={client.id} name={client.name} base={base} /> : null}
      </div>

      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-xl bg-zinc-950/40 px-4 py-3">
          <dt className="text-xs text-zinc-500">Next up</dt>
          <dd className="mt-0.5 flex items-baseline justify-between gap-2">
            <span className="truncate text-sm font-medium text-zinc-100">{client.next ?? "Nothing assigned"}</span>
            <Link href={programsHref} className="shrink-0 text-xs text-zinc-400 hover:text-zinc-100">
              Change
            </Link>
          </dd>
        </div>
        <div className="rounded-xl bg-zinc-950/40 px-4 py-3">
          <dt className="text-xs text-zinc-500">This week</dt>
          <dd className="mt-0.5 text-sm font-medium text-zinc-100">
            {summary.thisWeek} {summary.thisWeek === 1 ? "session" : "sessions"}
          </dd>
        </div>
        <div className="rounded-xl bg-zinc-950/40 px-4 py-3">
          <dt className="text-xs text-zinc-500">Last session</dt>
          <dd className="mt-0.5 truncate text-sm font-medium text-zinc-100">{summary.detail}</dd>
        </div>
      </dl>

      {showLink && client.link ? (
        <div className="mt-3">
          <ClientLink code={client.link} name={client.name} coachName={coachName} />
        </div>
      ) : null}

      {client.sessions.length > 1 ? (
        <div className="mt-4">
          <p className="mb-2 text-xs text-zinc-500">Sessions</p>
          <ul className="flex gap-2 overflow-x-auto pb-1">
            {client.sessions.map((s) => {
              const st = sessionStats(s);
              const active = s.session.share_token === activeSession;
              return (
                <li key={s.session.share_token} className="shrink-0">
                  <Link
                    href={`${base}?c=${encodeURIComponent(client.id)}&s=${encodeURIComponent(s.session.share_token)}#session`}
                    aria-current={active ? "true" : undefined}
                    className={`block rounded-lg border px-3 py-1.5 text-xs transition-colors ${
                      active ? "border-zinc-500 bg-zinc-800 text-zinc-100" : "border-zinc-800 text-zinc-400 hover:border-zinc-700"
                    } ${st.completed === 0 && !active ? "opacity-50" : ""}`}
                  >
                    <span className="font-medium">{shortDate(s.session.started_at)}</span>
                    <span className="text-zinc-500"> · {st.completed}/{st.planned} reps</span>
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
