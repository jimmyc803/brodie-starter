import { COLORS, type Color } from "@/lib/contract";

// Small display helpers shared by the coach dashboard components.
const DATE_FMT = new Intl.DateTimeFormat("en-US", { weekday: "short", month: "short", day: "numeric" });

export function shortDate(iso: string): string {
  const t = Date.parse(iso);
  return Number.isFinite(t) ? DATE_FMT.format(new Date(t)) : "";
}

export function pct(x: number | null): string {
  return x === null ? "–" : `${Math.round(x * 100)}%`;
}

export function colorOf(c: Color): string {
  return COLORS[c];
}
