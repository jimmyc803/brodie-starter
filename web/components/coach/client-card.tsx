import Link from "next/link";

import { neonFills } from "@/lib/body/neon";
import { bodySvgDataUri } from "@/lib/body/svg";
import type { Color, SessionView } from "@/lib/contract";
import { flaggedSets, sessionStats } from "@/lib/recap";
import { colorOf, pct, sessionHref, shortDate } from "@/components/coach/format";

type Client = { id: string; name: string; sessions: SessionView[] };

// One client: their latest session at a glance, sets worth a look, and every recent session as a selectable row.
export function ClientCard({ client, token, selected }: { client: Client; token: string; selected: string | null }) {
  const latest = client.sessions[0];
  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 sm:p-5">
      <header className="flex items-center gap-3">
        <div className="flex size-10 shrink-0 items-center justify-center rounded-full bg-zinc-800 text-base font-semibold text-zinc-200">
          {client.name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <h2 className="truncate text-lg font-semibold text-zinc-50">{client.name}</h2>
          <p className="truncate text-sm text-zinc-400">
            {latest ? `Latest: ${shortDate(latest.session.started_at)} · ${latest.day?.title ?? "Workout"}` : "No sessions yet"}
          </p>
        </div>
      </header>

      {latest ? <LatestSummary view={latest} /> : (
        <p className="mt-4 rounded-xl border border-dashed border-zinc-800 p-4 text-center text-sm text-zinc-500">
          No sessions yet. Once {client.name} finishes a workout with Brodie, it shows up here.
        </p>
      )}

      {client.sessions.length > 0 && (
        <div className="mt-4">
          <h3 className="mb-2 text-xs font-medium uppercase tracking-widest text-zinc-500">Sessions</h3>
          <ul className="space-y-1.5">
            {client.sessions.map((s) => (
              <SessionRow key={s.session.share_token} view={s} token={token} active={s.session.share_token === selected} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function LatestSummary({ view }: { view: SessionView }) {
  const st = sessionStats(view);
  const flagged = flaggedSets(view);
  return (
    <>
      <div className="mt-4 grid grid-cols-3 gap-2 text-center">
        <Stat label="camera-counted reps" value={`${st.completed}/${st.planned}`} />
        <Stat label="clean reps" value={pct(st.cleanRate)} />
        <div className="rounded-xl bg-zinc-950/60 px-2 py-2.5">
          <p className="flex items-center justify-center gap-2 text-base font-semibold tabular-nums">
            <Dot color="green" n={st.green} />
            <Dot color="yellow" n={st.yellow} />
            <Dot color="red" n={st.red} />
          </p>
          <p className="mt-0.5 text-[11px] leading-tight text-zinc-500">muscles</p>
        </div>
      </div>

      <div className="mt-4">
        <h3 className="mb-2 text-xs font-medium uppercase tracking-widest text-zinc-500">Needs a look</h3>
        {flagged.length === 0 ? (
          <p className="text-sm text-zinc-400">Nothing flagged. Every set hit its reps with mostly clean form.</p>
        ) : (
          <ul className="space-y-1.5">
            {flagged.map((f) => (
              <li key={`${f.exercise}-${f.set_number}`} className="flex items-start gap-2 text-sm">
                <span
                  className="mt-1.5 size-2 shrink-0 rounded-full"
                  style={{ background: colorOf(f.faulty / Math.max(1, f.completed) >= 0.5 ? "red" : "yellow") }}
                />
                <span className="text-zinc-300">
                  <span className="font-medium text-zinc-100">{f.exercise}</span> · set {f.set_number}
                  <span className="text-zinc-400"> — {f.reason}</span>
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function SessionRow({ view, token, active }: { view: SessionView; token: string; active: boolean }) {
  const st = sessionStats(view);
  return (
    <li>
      <Link
        href={sessionHref(token, view.session.share_token)}
        aria-current={active ? "true" : undefined}
        className={`flex items-center gap-3 rounded-xl border px-3 py-2 transition-colors ${
          active ? "border-zinc-600 bg-zinc-800" : "border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800/50"
        }`}
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- tiny inline SVG data URI */}
        <img src={bodySvgDataUri("front", neonFills(view.muscles), { width: 24, glow: false, id: "t" })} alt="" className="h-9 w-auto shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-zinc-100">{view.day?.title ?? "Workout"}</p>
          <p className="truncate text-xs text-zinc-400">
            {shortDate(view.session.started_at)}
            {st.minutes ? ` · ${st.minutes} min` : ""} · {st.completed}/{st.planned} reps
          </p>
        </div>
        <span className="shrink-0 text-xs text-zinc-500">{active ? "Viewing" : "View"}</span>
      </Link>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-zinc-950/60 px-2 py-2.5">
      <p className="text-base font-semibold tabular-nums text-zinc-50">{value}</p>
      <p className="mt-0.5 text-[11px] leading-tight text-zinc-500">{label}</p>
    </div>
  );
}

function Dot({ color, n }: { color: Color; n: number }) {
  return (
    <span className="flex items-center gap-1" title={`${n} ${color}`}>
      <span className="size-2.5 rounded-full" style={{ background: colorOf(color) }} />
      <span className="text-zinc-100">{n}</span>
    </span>
  );
}
