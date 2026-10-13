import { NO_TAGS, joinSmsHref, type JoinTags } from "./attribution";
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

/** Pre-filled "JOIN " text to the line; optional invite/source tags (see lib/attribution.ts). */
export function smsLink(brodieNumber: string | null, tags: JoinTags = NO_TAGS): string | null {
  return joinSmsHref(brodieNumber, tags);
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

/** "Sun Oct 18 · 11:59 PM ET" for an ISO instant, in America/New_York. Null when unparseable. */
export function formatEtDeadline(iso: string | null): string | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return null;
  const d = new Date(ms);
  const day = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    month: "short",
    day: "numeric",
  })
    .format(d)
    .replace(",", "");
  const time = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
  return `${day} · ${time} ET`;
}

export type CompetitionPhase = "pre" | "live" | "final";

/**
 * Single source of truth for whether the challenge is upcoming, running or over.
 * Final when frozen OR the window has ended, even if the freeze job hasn't run yet.
 * Unknown competition (null) is treated as live so the board still renders.
 */
export function competitionPhase(
  comp: { frozen: boolean; windowStart: string | null; windowEnd: string | null } | null,
  nowMs: number,
): CompetitionPhase {
  if (!comp) return "live";
  if (comp.frozen || (comp.windowEnd != null && isFinal(false, comp.windowEnd, nowMs))) return "final";
  const start = comp.windowStart ? Date.parse(comp.windowStart) : NaN;
  if (!Number.isNaN(start) && nowMs < start) return "pre";
  return "live";
}
