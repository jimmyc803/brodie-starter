"use client";

import { useEffect, useState } from "react";
import {
  formatCountdown,
  formatLineStatus,
  isFinal,
  powerHourStatus,
} from "@/lib/format";
import type { LineStatus, PowerHour } from "@/lib/types";

function useNow(): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now());
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  return now;
}

function Card({ label, children, loud }: { label: string; children: React.ReactNode; loud?: boolean }) {
  return (
    <div
      className={`rounded-xl border p-4 ${loud ? "border-accent bg-accent text-on-accent" : "border-hairline bg-surface"}`}
    >
      <p className={`text-xs font-bold uppercase tracking-widest ${loud ? "" : "text-ink-2"}`}>{label}</p>
      <div className="mt-1 font-display text-3xl leading-tight tabular-nums">{children}</div>
    </div>
  );
}

export function Widgets({
  line,
  windowEnd,
  frozen,
  powerHour,
}: {
  line: LineStatus | null;
  windowEnd: string | null;
  frozen: boolean;
  powerHour: PowerHour | null;
}) {
  const now = useNow();
  const final = now != null && windowEnd ? isFinal(frozen, windowEnd, now) : frozen;
  const ph = now == null ? ({ kind: "none" } as const) : powerHourStatus(powerHour, now);
  const endMs = windowEnd ? Date.parse(windowEnd) : NaN;

  return (
    <section aria-label="Challenge status" className="grid gap-3 sm:grid-cols-3">
      <Card label="Line">
        <span className="text-xl">{formatLineStatus(line)}</span>
      </Card>
      <Card label={final ? "Status" : "Ends in"} loud={final}>
        {final ? (
          <span className="text-2xl">FINAL — pending verification</span>
        ) : now != null && !Number.isNaN(endMs) ? (
          formatCountdown(endMs - now)
        ) : (
          "--:--:--"
        )}
      </Card>
      <Card label="Power hour" loud={ph.kind === "live"}>
        {ph.kind === "live" ? (
          "LIVE — 2× NOW"
        ) : ph.kind === "upcoming" ? (
          <>
            <span className="text-sm font-sans font-semibold">Starts in </span>
            {formatCountdown(ph.msUntil)}
          </>
        ) : (
          <span className="text-xl">{ph.kind === "over" ? "Done for today" : "Announced daily"}</span>
        )}
      </Card>
    </section>
  );
}
