import type { CoachView } from "@/lib/coach-view";
import Link from "next/link";
import { SAMPLE_COACH_TOKEN } from "@/lib/session-view";
import { flaggedSets } from "@/lib/recap";
import { ClientCard } from "@/components/coach/client-card";
import { SessionDetail } from "@/components/coach/session-detail";

const WEEK_MS = 7 * 24 * 60 * 60 * 1000;
const withinLastWeek = (iso: string) => Date.now() - Date.parse(iso) <= WEEK_MS;

// Coach dashboard body: header with summary chips, clients on the left, the selected session on the right.
export function CoachDashboard({ view, token, selected }: { view: CoachView; token: string; selected: string | null }) {
  const all = view.clients.flatMap((c) => c.sessions.map((s) => ({ client: c, session: s })));
  const picked =
    (selected && all.find((x) => x.session.session.share_token === selected)) ||
    all.find((x) => x.client.sessions[0] === x.session) ||
    null;

  const thisWeek = all.filter((x) => withinLastWeek(x.session.session.started_at)).length;
  const toReview = view.clients.reduce((n, c) => n + (c.sessions[0] ? flaggedSets(c.sessions[0]).length : 0), 0);
  const activeToken = picked?.session.session.share_token ?? null;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 sm:py-10">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-800 bg-zinc-900 px-3 py-1 text-xs font-medium text-zinc-300">
            <span className="size-1.5 rounded-full bg-[#22c55e]" />
            Brodie for Coaches
          </span>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">Coach {view.coach.name}</h1>
          <p className="mt-1 text-sm text-zinc-400">How your clients&apos; workouts with Brodie went.</p>
          <Link className="mt-4 inline-flex rounded-full bg-teal-800 px-6 py-3 text-sm font-semibold text-white" href={`/c/${encodeURIComponent(token === "demo" ? SAMPLE_COACH_TOKEN : token)}/program`}>
            Upload &amp; assign a program
          </Link>
        </div>
        <ul className="flex flex-wrap gap-2">
          <Chip value={view.clients.length} label={view.clients.length === 1 ? "client" : "clients"} />
          <Chip value={thisWeek} label={thisWeek === 1 ? "session this week" : "sessions this week"} />
          <Chip value={toReview} label={toReview === 1 ? "set needs a look" : "sets need a look"} accent={toReview > 0} />
        </ul>
      </header>

      {view.clients.length === 0 ? (
        <p className="mt-8 rounded-2xl border border-dashed border-zinc-800 p-8 text-center text-zinc-400">
          No clients yet. Assign a program day to a client and their sessions show up here.
        </p>
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,380px)_minmax(0,1fr)] lg:items-start">
          <div className="space-y-4">
            <h2 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Clients</h2>
            {view.clients.map((c) => (
              <ClientCard key={c.id} client={c} token={token} selected={activeToken} />
            ))}
          </div>
          <div className="space-y-4 lg:sticky lg:top-6">
            <h2 className="text-xs font-medium uppercase tracking-widest text-zinc-500">Session</h2>
            {picked ? (
              <SessionDetail view={picked.session} clientName={picked.client.name} />
            ) : (
              <p className="rounded-2xl border border-dashed border-zinc-800 p-8 text-center text-zinc-400">
                No sessions yet. When a client finishes a workout with Brodie, the details show up here.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Chip({ value, label, accent }: { value: number; label: string; accent?: boolean }) {
  return (
    <li className="flex items-baseline gap-1.5 rounded-xl border border-zinc-800 bg-zinc-900 px-3 py-2">
      <span className="text-lg font-semibold tabular-nums" style={{ color: accent ? "#eab308" : "#fafafa" }}>
        {value}
      </span>
      <span className="text-xs text-zinc-400">{label}</span>
    </li>
  );
}
