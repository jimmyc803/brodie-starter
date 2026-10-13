"use client";

import { useEffect, useState } from "react";
import { BoltIcon } from "@/components/ui/icons";
import {
  competitionPhase,
  formatCountdown,
  formatEta,
  formatEtDeadline,
  formatLineStatus,
  powerHourStatus,
  type CompetitionPhase,
} from "@/lib/format";
import type { LineStatus, LineSummary, PowerHour } from "@/lib/types";

/** Ticks every second. Starts from the server render time so SSR and hydration match with no layout shift. */
function useNow(initial: number): number {
  const [now, setNow] = useState<number>(initial);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

const LINE_LOOK: Record<LineSummary, { label: string; dot: string; pulse: boolean }> = {
  in_call: { label: "On a call", dot: "bg-live text-live", pulse: true },
  idle: { label: "Line open", dot: "bg-good text-good", pulse: true },
  claimed: { label: "Next up connecting", dot: "bg-gold text-gold", pulse: true },
  offline: { label: "Resetting", dot: "bg-ink-3 text-ink-3", pulse: false },
  closed: { label: "Closed", dot: "bg-ink-3 text-ink-3", pulse: false },
};

export function LiveDot({ className = "bg-live text-live", pulse = true }: { className?: string; pulse?: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block size-2.5 shrink-0 rounded-full ${className} ${pulse ? "animate-pulse-dot" : ""}`}
    />
  );
}

/** Live scoreboard strip for the single FaceTime line. */
function LineTicker({ line: rawLine, phase }: { line: LineStatus | null; phase: CompetitionPhase }) {
  // Once the challenge is over the queue is meaningless: show the line as closed regardless of its last state.
  const line = phase === "final" ? null : rawLine;
  const look = phase === "final" ? LINE_LOOK.closed : line ? LINE_LOOK[line.stateSummary] : null;
  const eta = line ? formatEta(line.queueLength, line.etaCycleS) : null;
  const walkIn = phase === "live" && line?.stateSummary === "idle" && line.queueLength === 0;
  const copy =
    phase === "final"
      ? "Challenge over. Final board below."
      : phase === "pre"
        ? "The line opens when the challenge starts. Text JOIN now to be ready."
        : walkIn
          ? "Nobody waiting. FaceTime in now."
          : line && line.stateSummary !== "closed"
            ? "Text QUEUE or just FaceTime to grab a spot. We text you when you're up."
            : "The line reopens soon. Watch this space.";
  return (
    <div className="card relative overflow-hidden lg:col-span-4">
      <p className="sr-only" aria-live="polite">
        {phase === "final" ? `Line closed. ${copy}` : `${formatLineStatus(line)}. ${copy}`}
      </p>
      <div aria-hidden className="flex items-center justify-between gap-3 bg-ink py-2 pr-2 pl-4 text-canvas">
        <span className="font-display text-xl tracking-wider uppercase">Now serving</span>
        <span className="inline-flex items-center gap-2 bg-canvas px-2.5 py-1 font-mono text-[0.7rem] font-bold tracking-wider text-ink uppercase">
          <LiveDot className={look?.dot ?? "bg-ink-3 text-ink-3"} pulse={look?.pulse ?? false} />
          {look?.label ?? "Unavailable"}
        </span>
      </div>
      <dl aria-hidden className="grid grid-cols-2 divide-x-2 divide-ink px-4 pt-4 sm:px-5">
        <div className="pr-4">
          <dt className="eyebrow">In line</dt>
          <dd className="font-display text-6xl leading-none tabular-nums sm:text-7xl lg:text-6xl">
            {line ? line.queueLength : "–"}
          </dd>
        </div>
        <div className="pl-4">
          <dt className="eyebrow">Est. wait</dt>
          <dd className="font-display text-6xl leading-none whitespace-nowrap tabular-nums sm:text-7xl lg:text-[3.25rem]">
            {walkIn ? (
              <span className="overprint">0</span>
            ) : eta ? (
              <>
                {eta.replace(/^~/, "").replace(/ min$/, "").replace("-", "–")}
                <span className="ml-1 font-mono text-xs font-bold text-ink-2 uppercase">min</span>
              </>
            ) : (
              "–"
            )}
          </dd>
        </div>
      </dl>
      <p aria-hidden className="mx-4 mt-4 mb-4 border-t-2 border-dashed border-hairline-strong pt-3 text-sm font-medium text-ink-2 sm:mx-5 sm:mb-5">
        {copy}
      </p>
    </div>
  );
}

function Segment({ value, unit }: { value: string; unit: string }) {
  return (
    <span className="flex flex-col items-center">
      <span className="border-2 border-ink bg-canvas px-1.5 py-1 font-display text-[2.4rem] leading-none text-ink tabular-nums sm:px-2 sm:text-[3.2rem]">
        {value}
      </span>
      <span className="mt-1.5 font-mono text-[0.625rem] font-bold tracking-[0.2em] uppercase">{unit}</span>
    </span>
  );
}

function Countdown({ ms }: { ms: number | null }) {
  const t = ms == null ? null : Math.max(0, Math.floor(ms / 1000));
  const p = (n: number) => String(n).padStart(2, "0");
  const segs: [string, string][] =
    t == null
      ? [["--", "days"], ["--", "hrs"], ["--", "min"], ["--", "sec"]]
      : [
          [p(Math.floor(t / 86400)), "days"],
          [p(Math.floor((t % 86400) / 3600)), "hrs"],
          [p(Math.floor((t % 3600) / 60)), "min"],
          [p(t % 60), "sec"],
        ];
  return (
    <div className="flex items-start gap-1.5 sm:gap-2" role="timer" aria-label={t == null ? "Loading" : formatCountdown(ms ?? 0)}>
      {segs.map(([v, u], i) => (
        <span key={u} className="flex items-start gap-1.5 sm:gap-2" aria-hidden>
          {i > 0 ? <span className="pt-2 font-display text-2xl sm:text-3xl">:</span> : null}
          <Segment value={v} unit={u} />
        </span>
      ))}
    </div>
  );
}

export function Widgets({
  line,
  windowStart,
  windowEnd,
  frozen,
  powerHour,
  serverNow,
}: {
  serverNow: number;
  line: LineStatus | null;
  windowStart: string | null;
  windowEnd: string | null;
  frozen: boolean;
  powerHour: PowerHour | null;
}) {
  const now = useNow(serverNow);
  const phase = competitionPhase({ frozen, windowStart, windowEnd }, now);
  const final = phase === "final";
  const pre = phase === "pre";
  const ph = powerHourStatus(powerHour, now);
  const target = pre && windowStart ? Date.parse(windowStart) : windowEnd ? Date.parse(windowEnd) : NaN;
  const live = ph.kind === "live" && phase === "live";

  return (
    <section aria-label="Challenge status" className="grid gap-3 lg:grid-cols-12">
      <LineTicker line={line} phase={phase} />

      {final ? (
        <div className="card relative overflow-hidden bg-yellow p-4 sm:p-5 lg:col-span-5">
          <p className="eyebrow text-ink">Status</p>
          <p className="mt-3 font-display text-7xl leading-[0.85] uppercase">Final</p>
          <p className="mt-2 text-sm font-semibold text-ink">
            Pending verification. Top 3 do a live check before payout.
          </p>
        </div>
      ) : (
        <div className="drop-shadow-[5px_5px_0_var(--color-ink)] lg:col-span-5">
          <div className="ticket h-full border-y-2 border-ink bg-blue px-7 py-4 text-canvas sm:px-8 sm:py-5">
            <div className="flex items-center justify-between gap-2">
              <p className="font-display text-xl tracking-wider uppercase">{pre ? "Bell rings in" : "Final bell in"}</p>
              <p aria-hidden className="font-mono text-[0.65rem] font-bold tracking-[0.2em] uppercase opacity-80">Admit one</p>
            </div>
            <div className="mt-3">
              <Countdown ms={!Number.isNaN(target) ? target - now : null} />
            </div>
            {pre && formatEtDeadline(windowStart) ? (
              <p className="mt-3 font-mono text-xs uppercase">{formatEtDeadline(windowStart)}. First rep scores then.</p>
            ) : !pre && formatEtDeadline(windowEnd) ? (
              <p className="mt-3 font-mono text-xs uppercase">{formatEtDeadline(windowEnd)}. Scores freeze at zero.</p>
            ) : null}
          </div>
        </div>
      )}

      {live ? (
        <div className="card relative -order-1 overflow-hidden bg-pink p-4 text-ink sm:p-5 lg:order-none lg:col-span-3">
          <div aria-hidden className="stripes-live absolute inset-0 animate-stripes" />
          <div className="relative">
            <div className="flex items-center justify-between">
              <p className="font-display text-xl tracking-wider uppercase">Power hour</p>
              <span className="inline-flex items-center gap-1.5 bg-ink px-2.5 py-1 font-mono text-xs font-bold tracking-wider text-canvas uppercase">
                <LiveDot className="bg-live text-live" />
                Live
              </span>
            </div>
            <p className="mt-2 flex items-center gap-2 font-display font-extrabold uppercase leading-none">
              <span className="inline-block animate-throb text-8xl overprint-ink">2×</span>
              <span className="text-2xl leading-[0.95]">
                points
                <br />
                right now
              </span>
            </p>
            <p className="mt-2 font-mono text-sm font-bold tabular-nums">
              Ends in {ph.kind === "live" ? formatCountdown(ph.msLeft) : ""}
            </p>
            <span className="sr-only">Power hour live: double points now</span>
          </div>
        </div>
      ) : (
        <div className="card relative overflow-hidden p-4 sm:p-5 lg:col-span-3">
          <div aria-hidden className="halftone-fade absolute -right-10 -bottom-10 size-44 [--dot:var(--color-pink)]" />
          <p className="relative flex items-center gap-1.5 font-display text-xl tracking-wider uppercase">
            <BoltIcon className="size-4 text-accent" /> Power hour
          </p>
          {ph.kind === "upcoming" && !final ? (
            <>
              <p className="relative mt-3 text-sm font-semibold text-ink-2">2× points starts in</p>
              <p className="relative font-display text-5xl tabular-nums">{formatCountdown(ph.msUntil)}</p>
            </>
          ) : (
            <>
              <p className="relative mt-3 font-display text-4xl leading-[0.9] uppercase">
                {final ? "Over" : ph.kind === "over" ? "Done for today" : "Announced daily"}
              </p>
              <p className="relative mt-2 text-sm text-ink-2">
                {final ? "No more multipliers." : "One random hour, 12–10 PM ET. Every valid rep scores 2×."}
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
