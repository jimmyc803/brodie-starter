import * as React from "react";
import { Avatar } from "@/components/brodie-avatar";
import type { PowerHour } from "./types";

type Raw = Record<string, unknown>;
const number = (value: unknown, fallback = 0): number => {
  const parsed = typeof value === "string" ? Number(value) : value;
  return typeof parsed === "number" && Number.isFinite(parsed) ? parsed : fallback;
};
const rank = (value: unknown): number | null => {
  const parsed = number(value);
  return parsed > 0 ? Math.floor(parsed) : null;
};
const level = (value: unknown) => Math.min(10, Math.max(1, Math.floor(number(value, 1))));

export type PublicProfile = {
  displayName: string;
  points: number;
  validReps: number;
  streak: number;
  avatarLevel: number;
  rank: number | null;
  bestCallId: string | null;
  bestCallPoints: number;
};

export function mapProfile(row: Raw): PublicProfile {
  return {
    displayName: typeof row.display_name === "string" ? row.display_name : "Athlete",
    points: number(row.points),
    validReps: number(row.valid_reps),
    streak: number(row.streak),
    avatarLevel: level(row.avatar_level),
    rank: rank(row.rank),
    bestCallId: typeof row.best_call_id === "string" ? row.best_call_id : null,
    bestCallPoints: number(row.best_call_points),
  };
}

export function mapDaily(row: Raw) {
  return {
    dateEt: typeof row.date_et === "string" ? row.date_et : "",
    points: number(row.points),
    validReps: number(row.valid_reps),
    calls: number(row.calls),
  };
}

export function mapThresholds(value: unknown): number[] {
  return Array.isArray(value)
    ? value.filter((item): item is number => typeof item === "number" && Number.isFinite(item))
    : [];
}

export function avatarLevelForPoints(points: number, thresholds: number[]): number {
  return Math.min(10, 1 + thresholds.slice(1).filter((threshold) => points >= threshold).length);
}

const reasonLabels: Record<string, string> = {
  multiple_people: "Multiple people", not_in_frame: "Out of frame", knees_down: "Knees down",
  hips_sag: "Hips sagging", hips_pike: "Hips too high", too_shallow: "Too shallow",
  no_lockout: "No lockout", too_fast: "Too fast", not_horizontal: "Not horizontal",
  before_start: "Before start", after_freeze: "Scoring closed", after_count: "After time",
  liveness_fail: "Liveness failed", in_challenge: "During liveness check",
};

export function mapCallResult(row: Raw) {
  const counts = new Map<string, number>();
  if (row.reasons && typeof row.reasons === "object" && !Array.isArray(row.reasons)) {
    for (const [reason, value] of Object.entries(row.reasons)) {
      const count = Math.max(0, Math.floor(number(value)));
      if (!count) continue;
      const label = Object.hasOwn(reasonLabels, reason)
        ? reasonLabels[reason]
        : reason.startsWith("classifier:") ? "Form check" : "Other";
      counts.set(label, (counts.get(label) ?? 0) + count);
    }
  }
  return {
    callId: typeof row.call_id === "string" ? row.call_id : "",
    displayName: typeof row.display_name === "string" ? row.display_name : "Athlete",
    points: row.void === true ? 0 : number(row.points),
    pointsBefore: number(row.points_before),
    totalPoints: number(row.total_points_after),
    validReps: number(row.valid_reps),
    rejectedReps: number(row.rejected_reps),
    levelBefore: level(row.avatar_level_before),
    levelAfter: level(row.avatar_level_after),
    rankBefore: rank(row.rank_before),
    rankAfter: rank(row.rank_after),
    void: row.void === true,
    reasons: Array.from(counts, ([label, count]) => ({ label, count })),
  };
}

export function publicSiteUrl(value: string | null | undefined): string {
  try {
    const url = new URL(value ?? "");
    if (["https:", "http:"].includes(url.protocol) && !url.username && !url.password) return url.origin;
  } catch { /* Use the configured deployment default when no valid URL is available. */ }
  return "https://brodie-pushups.vercel.app";
}

export function makeCardModel(
  result: ReturnType<typeof mapCallResult>,
  profile: PublicProfile | null,
  powerHour: PowerHour | null,
  siteUrl: string | null | undefined,
) {
  const start = powerHour ? new Date(powerHour.startsAt) : null;
  return {
    ...result,
    pointsLabel: `${result.points >= 0 ? "+" : ""}${result.points} points`,
    rankLabel: result.rankAfter === null ? "Unranked"
      : result.rankBefore === null ? `#${result.rankAfter}` : `#${result.rankBefore} → #${result.rankAfter}`,
    streak: profile?.streak ?? null,
    nextPowerHour: start && Number.isFinite(start.getTime())
      ? new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
      }).format(start) + " ET" : "Not scheduled",
    siteUrl: publicSiteUrl(siteUrl),
  };
}

export type CardModel = ReturnType<typeof makeCardModel>;

export function ResultCard({ model }: { model: CardModel }) {
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", padding: 64, background: "#f2ecdf", color: "#16120e", border: "16px solid #16120e", fontFamily: "sans-serif" }}>
      <div style={{ display: "flex", alignSelf: "flex-start", fontSize: 28, fontWeight: 700, background: "#16120e", color: "#f2ecdf", padding: "8px 16px", letterSpacing: 4 }}>BRODIE PUSH-UP CHALLENGE</div>
      <div style={{ display: "flex", fontSize: 60, fontWeight: 700, marginTop: 20 }}>{model.displayName}</div>
      <div style={{ display: "flex", justifyContent: "space-around", alignItems: "center", marginTop: 12 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Avatar level={model.levelBefore} size={260} />
          <div style={{ display: "flex", fontSize: 26 }}>Level {model.levelBefore}</div>
        </div>
        <div style={{ display: "flex", fontSize: 72, color: "#e0006f" }}>→</div>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
          <Avatar level={model.levelAfter} size={260} />
          <div style={{ display: "flex", fontSize: 26 }}>Level {model.levelAfter}</div>
        </div>
      </div>
      <div style={{ display: "flex", fontSize: 110, fontWeight: 700, color: "#ff3d97", textShadow: "6px 5px 0 #2346d8", marginTop: 24 }}>{model.pointsLabel}</div>
      {model.void && <div style={{ display: "flex", fontSize: 28 }}>VOID CALL · No points awarded</div>}
      <div style={{ display: "flex", fontSize: 34, marginTop: 12 }}>{model.validReps} valid · {model.rejectedReps} rejected</div>
      <div style={{ display: "flex", flexWrap: "wrap", marginTop: 16, fontSize: 23, color: "#4b4439", gap: 12 }}>
        {model.reasons.length === 0 ? "No rejected-rep reasons" : model.reasons.map(({ label, count }) => (
          <span key={label}>{label}: {count}</span>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 36, borderTop: "4px dashed #16120e", paddingTop: 24 }}>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <span style={{ fontSize: 56 }}>{model.totalPoints} total</span>
          <span style={{ fontSize: 24 }}>{model.pointsBefore} before this call</span>
        </div>
        <div style={{ display: "flex", fontSize: 48 }}>{model.rankLabel}</div>
      </div>
      <div style={{ display: "flex", fontSize: 30, marginTop: 24 }}>Current streak: {model.streak === null ? "unavailable" : `${model.streak} days`}</div>
      <div style={{ display: "flex", fontSize: 27, marginTop: 20 }}>Next power hour: {model.nextPowerHour}</div>
      <div style={{ display: "flex", fontSize: 25, color: "#e0006f", marginTop: "auto" }}>{model.siteUrl}</div>
    </div>
  );
}
