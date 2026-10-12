"use client";

import { useEffect, useState } from "react";
import { BoltIcon } from "@/components/ui/icons";
import { formatCountdown, formatEta, formatEtDeadline, formatLineStatus, isFinal, powerHourStatus } from "@/lib/format";
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
  idle: { label: "Line open", dot: "bg-accent text-accent", pulse: true },
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
function LineTicker({ line }: { line: LineStatus | null }) {
  const look = line ? LINE_LOOK[line.stateSummary] : null;
  const eta = line ? formatEta(line.queueLength, line.etaCycleS) : null;
  const walkIn = line?.stateSummary === "idle" && line.queueLength === 0;
  return (
    <div className="card relative overflow-hidden p-4 sm:p-5 lg:col-span-4">
      <p className="sr-only" aria-live="polite">
        {formatLineStatus(line)}
      </p>
      <div aria-hidden className="flex items-center justify-between gap-3">
        <span className="eyebrow">The line</span>
        <span className="inline-flex items-center gap-2 rounded-full border border-hairline bg-surface-2 px-3 py-1 text-xs font-bold uppercase tracking-wider">
          <LiveDot className={look?.dot ?? "bg-ink-3 text-ink-3"} pulse={look?.pulse ?? false} />
          {look?.label ?? "Unavailable"}
        </span>
      </div>
      <dl aria-hidden className="mt-4 grid grid-cols-2 divide-x divide-hairline">
        <div className="pr-4">
          <dt className="text-xs font-semibold uppercase tracking-wider text-ink-3">In line</dt>
          <dd className="font-display text-[2.75rem] font-extrabold leading-none tabular-nums sm:text-6xl lg:text-5xl">
            {line ? line.queueLength : "–"}
          </dd>
        </div>
        <div className="pl-4">
          <dt className="text-xs font-semibold uppercase tracking-wider text-ink-3">Est. wait</dt>
          <dd className="font-display text-[2.75rem] font-extrabold leading-none whitespace-nowrap tabular-nums sm:text-6xl lg:text-5xl">
            {walkIn ? (
              <span className="text-accent">0</span>
            ) : eta ? (
              <>
                {eta.replace(/^~/, "").replace(/ min$/, "").replace("-", "–")}
                <span className="ml-1 text-xl text-ink-2">min</span>
              </>
            ) : (
              "–"
            )}
          </dd>
        </div>
      </dl>
      <p aria-hidden className="mt-4 text-sm text-ink-2">
        {walkIn
          ? "Nobody waiting. FaceTime in now."
          : line && line.stateSummary !== "closed"
            ? "Text QUEUE to grab a spot. We text you when you're up."
            : "The line reopens soon. Watch this space."}
      </p>
    </div>
  );
}

function Segment({ value, unit }: { value: string; unit: string }) {
  return (
    <span className="flex flex-col items-center">
      <span className="rounded-lg bg-surface-2 px-1.5 py-1 font-mono text-[2rem] font-bold leading-none tabular-nums ring-1 ring-hairline sm:px-2 sm:text-[2.6rem]">
        {value}
      </span>
      <span className="mt-1.5 text-[0.625rem] font-bold uppercase tracking-[0.2em] text-ink-3">{unit}</span>
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
          {i > 0 ? <span className="pt-1 font-mono text-2xl font-bold text-ink-3 sm:text-3xl">:</span> : null}
          <Segment value={v} unit={u} />
        </span>
      ))}
    </div>
  );
}

export function Widgets({
  line,
  windowEnd,
  frozen,
  powerHour,
  serverNow,
}: {
  serverNow: number;
  line: LineStatus | null;
  windowEnd: string | null;
  frozen: boolean;
  powerHour: PowerHour | null;
}) {
  const now = useNow(serverNow);
  const final = windowEnd ? isFinal(frozen, windowEnd, now) : frozen;
  const ph = powerHourStatus(powerHour, now);
  const endMs = windowEnd ? Date.parse(windowEnd) : NaN;
  const live = ph.kind === "live" && !final;

  return (
    <section aria-label="Challenge status" className="grid gap-3 lg:grid-cols-12">
      <LineTicker line={line} />

      {final ? (
        <div className="card relative overflow-hidden border-accent/60 p-4 sm:p-5 lg:col-span-5">
          <p className="eyebrow text-accent">Status</p>
          <p className="mt-3 font-display text-5xl font-extrabold uppercase leading-[0.9]">Final</p>
          <p className="mt-2 text-sm font-semibold text-ink-2">
            Pending verification. Top 3 do a live check before payout.
          </p>
        </div>
      ) : (
        <div className="card p-4 sm:p-5 lg:col-span-5">
          <p className="eyebrow">Challenge ends in</p>
          <div className="mt-3">
            <Countdown ms={!Number.isNaN(endMs) ? endMs - now : null} />
          </div>
          {formatEtDeadline(windowEnd) ? (
            <p className="mt-3 text-sm text-ink-2">{formatEtDeadline(windowEnd)}. Scores freeze at zero.</p>
          ) : null}
        </div>
      )}

      {live ? (
        <div className="relative -order-1 overflow-hidden rounded-[var(--radius-card)] bg-accent p-4 lg:order-none text-on-accent shadow-[0_0_60px_-12px_rgb(212_255_58/0.6)] sm:p-5 lg:col-span-3">
          <div aria-hidden className="stripes-live absolute inset-0 animate-stripes" />
          <div className="relative">
            <div className="flex items-center justify-between">
              <p className="text-[0.6875rem] font-extrabold uppercase tracking-[0.18em]">Power hour</p>
              <span className="inline-flex items-center gap-1.5 rounded-full bg-on-accent px-2.5 py-1 text-xs font-extrabold uppercase tracking-wider text-accent">
                <LiveDot className="bg-live text-live" />
                Live
              </span>
            </div>
            <p className="mt-2 flex items-center gap-2 font-display font-extrabold uppercase leading-none">
              <span className="inline-block animate-throb text-7xl">2×</span>
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
        <div className="card p-4 sm:p-5 lg:col-span-3">
          <p className="eyebrow flex items-center gap-1.5">
            <BoltIcon className="size-3.5 text-accent" /> Power hour
          </p>
          {ph.kind === "upcoming" && !final ? (
            <>
              <p className="mt-3 text-sm font-semibold text-ink-2">2× points starts in</p>
              <p className="font-mono text-4xl font-bold tabular-nums">{formatCountdown(ph.msUntil)}</p>
            </>
          ) : (
            <>
              <p className="mt-3 font-display text-3xl font-extrabold uppercase leading-none">
                {final ? "Over" : ph.kind === "over" ? "Done for today" : "Announced daily"}
              </p>
              <p className="mt-2 text-sm text-ink-2">
                {final ? "No more multipliers." : "One random hour, 12–10 PM ET. Every valid rep scores 2×."}
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
