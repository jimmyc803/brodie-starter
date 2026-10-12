import type { LineStatus, PowerHour, PowerHourStatus } from "./types";

/** Format a duration in ms as H:MM:SS (or D d H:MM:SS when over a day). Negative clamps to 0. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const hms = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return d > 0 ? `${d}d ${hms}` : hms;
}

/** Wait estimate range text, e.g. "~10-15 min". Returns null when unknown. */
export function formatEta(queueLength: number, etaCycleS: number | null): string | null {
  if (etaCycleS == null || etaCycleS <= 0 || queueLength <= 0) return null;
  const mid = (queueLength * etaCycleS) / 60;
  if (mid < 2) return "~1-2 min";
  const lo = Math.max(1, Math.round(mid * 0.75));
  let hi = Math.round(mid * 1.25);
  if (hi <= lo) hi = lo + 1;
  if (mid >= 30) {
    const r = Math.round(mid / 5) * 5;
    return `~${r} min`;
  }
  return `~${lo}-${hi} min`;
}

export function formatLineStatus(s: LineStatus | null): string {
  if (!s) return "Line status unavailable";
  if (s.stateSummary === "closed") return "Line closed";
  const state =
    s.stateSummary === "in_call"
      ? "In a call"
      : s.stateSummary === "offline"
        ? "Line resetting"
        : s.stateSummary === "claimed"
          ? "Next up on the line"
          : "Line open";
  const parts = [state];
  if (s.queueLength > 0) parts.push(`${s.queueLength} in line`);
  else parts.push("no wait");
  const eta = formatEta(s.queueLength, s.etaCycleS);
  if (eta) parts.push(eta);
  return parts.join(" · ");
}

export function powerHourStatus(ph: PowerHour | null, nowMs: number): PowerHourStatus {
  if (!ph) return { kind: "none" };
  const start = Date.parse(ph.startsAt);
  const end = Date.parse(ph.endsAt);
  if (Number.isNaN(start) || Number.isNaN(end)) return { kind: "none" };
  if (nowMs < start) return { kind: "upcoming", msUntil: start - nowMs };
  if (nowMs < end) return { kind: "live", msLeft: end - nowMs };
  return { kind: "over" };
}

export function isFinal(frozen: boolean, windowEnd: string, nowMs: number): boolean {
  const end = Date.parse(windowEnd);
  return frozen || (!Number.isNaN(end) && nowMs >= end);
}

export function smsLink(brodieNumber: string | null): string | null {
  if (!brodieNumber) return null;
  return `sms:${brodieNumber}&body=JOIN%20`;
}

/** YYYY-MM-DD of the given instant in America/New_York. */
export function etDate(nowMs: number): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(nowMs));
}

/** Today's (ET) power hour if present, else the nearest upcoming one, else null. */
export function pickPowerHour(rows: PowerHour[], nowMs: number): PowerHour | null {
  const today = etDate(nowMs);
  const t = rows.find((r) => r.dateEt === today);
  if (t) return t;
  const upcoming = rows
    .filter((r) => Date.parse(r.startsAt) > nowMs)
    .sort((a, b) => Date.parse(a.startsAt) - Date.parse(b.startsAt));
  return upcoming[0] ?? null;
}
