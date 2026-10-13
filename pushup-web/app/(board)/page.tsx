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

  const dates = billDates(comp?.windowStart ?? null, comp?.windowEnd ?? null);

  return (
    <div className="space-y-10 sm:space-y-14">
      <LiveRefresh />

      <section className="relative grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-12">
        <div className="relative animate-rise">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2 font-mono text-xs font-bold tracking-[0.14em] uppercase">
            {final ? (
              <span className="border-2 border-ink bg-ink px-2 py-0.5 text-canvas">Final standings</span>
            ) : phase === "pre" ? (
              <span className="border-2 border-ink bg-yellow px-2 py-0.5">Starting soon</span>
            ) : (
              <span className="inline-flex items-center gap-2 border-2 border-ink bg-canvas px-2 py-0.5">
                <LiveDot />
                Live now
              </span>
            )}
            <span className="text-ink-2">{dates ? `Vol. 1 · ${dates}` : "Vol. 1 · One week"}</span>
          </div>

          <div className="relative mt-5">
            <h1 className="font-display text-mega uppercase">
              <span className="block">{final ? "It's" : "Strict"}</span>
              <span className="block overprint">{final ? "over." : "reps."}</span>
            </h1>
            <Seal className="pointer-events-none absolute right-0 bottom-0 hidden size-36 sm:block md:size-44" final={final} />
          </div>

          <p className="mt-6 max-w-xl text-lg leading-snug text-ink-2 sm:text-xl">
            <span className="font-semibold text-ink">FaceTime the line. Crank out push-ups. Get judged on every rep.</span>{" "}
            Climb the board and watch your Brodie bulk up.
          </p>
          <div className="mt-7 hidden flex-wrap items-center gap-5 sm:flex">
            <JoinButton href={joinHref} size="lg" label="Text JOIN to compete" />
            <Link
              href="/rules"
              className="inline-flex min-h-11 items-center gap-2 font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px] hover:text-accent"
            >
              How reps are judged <ArrowRightIcon className="size-4" />
            </Link>
          </div>
        </div>
        {leader ? <LeaderSpotlight row={leader} final={final} /> : null}

        <dl className="grid grid-cols-3 border-2 border-ink bg-surface lg:col-span-2">
          {[
            ["Athletes", `${rows.length.toLocaleString("en-US")}${more}`],
            ["Valid reps", `${totalReps.toLocaleString("en-US")}${more}`],
            ["1st prize", comp?.firstPrize ?? "$100"],
          ].map(([k, v], i) => (
            <div key={k} className={`px-3 py-3 sm:px-6 sm:py-4 ${i > 0 ? "border-l-2 border-ink" : ""} ${i === 2 ? "bg-yellow" : ""}`}>
              <dt className="eyebrow text-ink">{k}</dt>
              <dd className="mt-1 font-display text-[2rem] leading-none tabular-nums sm:text-6xl">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <Widgets serverNow={serverNow} line={line} windowStart={comp?.windowStart ?? null} windowEnd={comp?.windowEnd ?? null} frozen={comp?.frozen ?? false} powerHour={ph} />

      <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {final ? (
            <div role="status" className="mb-5 flex items-center gap-3 border-2 border-ink bg-yellow px-4 py-3">
              <CrownIcon className="size-5 shrink-0" />
              <p className="font-semibold">
                <span className="font-display text-2xl uppercase">Final</span>
                <span className="text-ink-2"> · pending verification. Scores are frozen.</span>
              </p>
            </div>
          ) : null}
          {rows.length === 0 ? (
            <section aria-label="Leaderboard" className="card relative flex flex-col items-center overflow-hidden px-6 py-12 text-center">
              <div aria-hidden className="halftone-fade absolute inset-0 [--dot:var(--color-pink)] opacity-60" />
              <div className="relative flex flex-col items-center">
                <Avatar level={1} size={120} pose="idle" />
                <h2 className="mt-4 font-display text-5xl uppercase">The board is empty</h2>
                <p className="mt-2 max-w-sm text-ink-2">First valid rep takes #1. Nobody&apos;s claimed it yet.</p>
                <JoinButton href={joinHref} className="mt-6" label="Take #1" />
              </div>
            </section>
          ) : (
            <Leaderboard rows={rows}>
              <div className="space-y-8">
                <Podium rows={rows} />
                {rest.length > 0 ? (
                  <ol aria-label="Ranks 4 and below" className="card divide-y divide-dashed divide-hairline-strong overflow-hidden">
                    {rest.map((r) => (
                      <LeaderRow key={r.publicId} row={r} />
                    ))}
                  </ol>
                ) : null}
              </div>
            </Leaderboard>
          )}
        </div>

        <aside className="space-y-6 lg:sticky lg:top-24 lg:self-start" aria-label="Prizes and how to play">
          <div className="card overflow-hidden">
            <p className="bg-ink px-5 py-2 font-display text-xl tracking-wide text-canvas uppercase">The purse</p>
            <div className="relative px-5 pt-4 pb-5">
              <div aria-hidden className="halftone-fade absolute -top-6 -right-8 size-40 [--dot:var(--color-pink)]" />
              <p className="eyebrow relative text-ink">1st place</p>
              <p className="relative font-display text-7xl leading-none overprint">{comp?.firstPrize ?? "$100"}</p>
              <div className="perf relative my-4" />
              <p className="eyebrow relative text-ink">Top 3</p>
              <p className="relative mt-1 text-lg leading-tight font-semibold">Group call with {ufcFighterCopy(comp?.ufcFighter)}</p>
            </div>
          </div>
          <div className="card p-5">
            <p className="font-display text-3xl uppercase">How to play</p>
            <ol className="mt-4 space-y-4">
              {[
                ["Text JOIN + your name", "Pick the name shown on the board."],
                ["Text QUEUE", "We text you when the line is yours."],
                ["FaceTime and rep out", "3 minutes. Every strict rep counts."],
              ].map(([t, d], i) => (
                <li key={t} className="flex gap-3">
                  <span className="font-display text-5xl leading-[0.8] type-outline">{i + 1}</span>
                  <span>
                    <span className="block font-semibold">{t}</span>
                    <span className="text-sm text-ink-2">{d}</span>
                  </span>
                </li>
              ))}
            </ol>
            <Link
              href="/setup"
              className="mt-5 inline-flex min-h-11 items-center gap-2 font-mono text-sm font-bold uppercase underline decoration-pink decoration-[3px] underline-offset-[6px] hover:text-accent"
            >
              30-second setup guide <ArrowRightIcon className="size-4" />
            </Link>
          </div>
        </aside>
      </div>
    </div>
  );
}

/** "Oct 12 – Oct 18" in Eastern time, for the poster's volume line. */
function billDates(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const f = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
  const a = Date.parse(start);
  const b = Date.parse(end);
  if (Number.isNaN(a) || Number.isNaN(b)) return null;
  return `${f.format(a)} – ${f.format(b)}`;
}

/** Rotating rubber-stamp seal that sits over the headline. Decorative. */
function Seal({ className, final }: { className?: string; final: boolean }) {
  const ring = final ? "Final board ✶ Scores frozen ✶ Final board ✶ Scores frozen ✶ " : "Judged live ✶ Every rep ✶ Strict form ✶ No cheats ✶ ";
  return (
    <div aria-hidden className={`${className} animate-stamp [--stamp-rot:-10deg]`}>
      <svg viewBox="0 0 200 200" className="size-full animate-spin-slow">
        <defs>
          <path id="seal-ring" d="M100 100m-74 0a74 74 0 1 1 148 0a74 74 0 1 1-148 0" />
        </defs>
        <circle cx="100" cy="100" r="96" fill="#2346d8" />
        <circle cx="100" cy="100" r="88" fill="none" stroke="#f2ecdf" strokeWidth="2" />
        <circle cx="100" cy="100" r="58" fill="none" stroke="#f2ecdf" strokeWidth="2" />
        <text fill="#f2ecdf" fontFamily="var(--font-display)" fontSize="19" letterSpacing="2.4">
          <textPath href="#seal-ring">{ring.toUpperCase()}</textPath>
        </text>
      </svg>
      <span className="absolute inset-0 grid place-items-center text-center font-display leading-[0.85] text-canvas uppercase">
        <span>
          <span className="block text-[2.6rem] md:text-5xl">{final ? "Done" : "7"}</span>
          <span className="block text-sm md:text-base">{final ? "Week 1" : "Days"}</span>
        </span>
      </span>
    </div>
  );
}
