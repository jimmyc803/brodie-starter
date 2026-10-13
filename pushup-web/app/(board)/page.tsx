import Link from "next/link";
import { Avatar } from "@/components/brodie-avatar";
import { JoinButton } from "@/components/join-button";
import { LeaderRow } from "@/components/leader-row";
import { Leaderboard } from "@/components/leaderboard";
import { LeaderSpotlight } from "@/components/leader-spotlight";
import { LiveRefresh } from "@/components/live-refresh";
import { Podium } from "@/components/podium";
import { ArrowRightIcon, CrownIcon } from "@/components/ui/icons";
import { LiveDot, Widgets } from "@/components/widgets";
import { getCompetition, getLeaderboard, getLineStatus, getPowerHour } from "@/lib/data";
import { competitionPhase, smsLink } from "@/lib/format";
import { ufcFighterCopy } from "@/lib/mappers";

export const dynamic = "force-dynamic";

/** Request time, so the first client render of the widgets matches the server (no CLS when power hour is live). */
function requestTime(): number {
  return Date.now();
}

export default async function Home() {
  const serverNow = requestTime();
  const [rows, line, ph, comp] = await Promise.all([
    getLeaderboard(100),
    getLineStatus(),
    getPowerHour(),
    getCompetition(),
  ]);
  const joinHref = smsLink(comp?.brodieNumber ?? null);
  // Final if frozen OR the window has closed (the freeze job may lag); same rule the widgets use.
  const phase = competitionPhase(comp, serverNow);
  const final = phase === "final";
  const totalReps = rows.reduce((n, r) => n + r.validReps, 0);
  const rest = rows.filter((r) => r.rank > 3);
  const leader = rows.find((r) => r.rank === 1) ?? null;
  const more = rows.length >= 100 ? "+" : "";

  return (
    <div className="space-y-8 sm:space-y-12">
      <LiveRefresh />

      <section className="relative grid items-center gap-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
        <div className="animate-rise">
          <p className="inline-flex items-center gap-2 rounded-full border border-hairline bg-surface/70 px-3 py-1.5 text-xs font-bold uppercase tracking-[0.16em] text-ink-2">
            {final ? (
              <>Final standings</>
            ) : phase === "pre" ? (
              <>
                Starting soon<span className="hidden sm:inline"> · One week · Strict reps only</span>
              </>
            ) : (
              <>
                <LiveDot />
                <span>
                  Live now<span className="hidden sm:inline"> · One week · Strict reps only</span>
                </span>
              </>
            )}
          </p>
          <h1 className="mt-4 font-display text-mega font-extrabold uppercase italic tracking-tight">
            {final ? "It's over." : "Strict reps."}
            <br />
            <span className="text-accent">{final ? "Final board." : "Live board."}</span>
          </h1>
          <p className="mt-4 max-w-xl text-lg text-ink-2">
            FaceTime the line, crank out push-ups, get judged on every rep. Climb the board and watch your
            Brodie bulk up.
          </p>
          <div className="mt-6 hidden flex-wrap items-center gap-3 sm:flex">
            <JoinButton href={joinHref} size="lg" label="Text JOIN to compete" />
            <Link
              href="/rules"
              className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 font-semibold text-ink-2 hover:text-ink"
            >
              How reps are judged <ArrowRightIcon className="size-4" />
            </Link>
          </div>
          <dl className="mt-6 grid max-w-xl grid-cols-3 gap-2 sm:mt-8 sm:gap-3">
            {[
              ["Athletes", `${rows.length.toLocaleString("en-US")}${more}`],
              ["Valid reps", `${totalReps.toLocaleString("en-US")}${more}`],
              ["1st prize", comp?.firstPrize ?? "$100"],
            ].map(([k, v]) => (
              <div key={k} className="card px-3 py-3 sm:px-4">
                <dt className="eyebrow">{k}</dt>
                <dd className="mt-1 font-display text-3xl font-extrabold tabular-nums leading-none sm:text-4xl">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        {leader ? <LeaderSpotlight row={leader} final={final} /> : null}
      </section>

      <Widgets serverNow={serverNow} line={line} windowStart={comp?.windowStart ?? null} windowEnd={comp?.windowEnd ?? null} frozen={comp?.frozen ?? false} powerHour={ph} />

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {final ? (
            <div role="status" className="mb-4 flex items-center gap-3 rounded-2xl border border-accent/50 bg-accent-dim px-4 py-3">
              <CrownIcon className="size-5 shrink-0 text-accent" />
              <p className="font-semibold">
                <span className="font-display text-xl font-extrabold uppercase text-accent">Final</span>
                <span className="text-ink-2"> · pending verification. Scores are frozen.</span>
              </p>
            </div>
          ) : null}
          {rows.length === 0 ? (
            <section aria-label="Leaderboard" className="card flex flex-col items-center px-6 py-12 text-center">
              <Avatar level={1} size={120} pose="idle" />
              <h2 className="mt-4 font-display text-4xl font-extrabold uppercase">The board is empty</h2>
              <p className="mt-2 max-w-sm text-ink-2">First valid rep takes #1. Nobody&apos;s claimed it yet.</p>
              <JoinButton href={joinHref} className="mt-6" label="Take #1" />
            </section>
          ) : (
            <Leaderboard rows={rows}>
              <div className="space-y-6">
                <Podium rows={rows} />
                {rest.length > 0 ? (
                  <ol aria-label="Ranks 4 and below" className="card divide-y divide-hairline overflow-hidden">
                    {rest.map((r) => (
                      <LeaderRow key={r.publicId} row={r} />
                    ))}
                  </ol>
                ) : null}
              </div>
            </Leaderboard>
          )}
        </div>

        <aside className="space-y-4 lg:sticky lg:top-20 lg:self-start" aria-label="Prizes and how to play">
          <div className="card overflow-hidden">
            <p className="eyebrow px-5 pt-5">Prizes</p>
            <ul className="mt-2 divide-y divide-hairline">
              <li className="flex items-center justify-between gap-3 px-5 py-3">
                <span className="text-ink-2">1st place</span>
                <span className="font-display text-3xl font-extrabold text-accent">{comp?.firstPrize ?? "$100"}</span>
              </li>
              <li className="flex items-center justify-between gap-3 px-5 py-3">
                <span className="text-ink-2">Top 3</span>
                <span className="text-right font-semibold">Group call with {ufcFighterCopy(comp?.ufcFighter)}</span>
              </li>
            </ul>
          </div>
          <div className="card p-5">
            <p className="eyebrow">How to play</p>
            <ol className="mt-3 space-y-3">
              {[
                ["Text JOIN + your name", "Pick the name shown on the board."],
                ["Text QUEUE", "We text you when the line is yours."],
                ["FaceTime and rep out", "3 minutes. Every strict rep counts."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="grid size-7 shrink-0 place-items-center rounded-full bg-accent font-display text-base font-extrabold text-on-accent">
                    {i + 1}
                  </span>
                  <span>
                    <span className="block font-semibold">{t}</span>
                    <span className="text-sm text-ink-2">{d}</span>
                  </span>
                </li>
              ))}
            </ol>
            <Link
              href="/setup"
              className="mt-4 inline-flex min-h-11 items-center gap-2 font-semibold text-accent hover:underline"
            >
              30-second setup guide <ArrowRightIcon className="size-4" />
            </Link>
          </div>
        </aside>
      </div>
    </div>
  );
}
