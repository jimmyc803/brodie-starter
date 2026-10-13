/** Client-safe types + pure view helpers for /me (no env, no network). Mirrors challenge/dispatcher/web.py. */

export type QueueStatus = "waiting" | "notified" | null;

export type Me =
  | { registered: false; email: string | null; server_time?: string }
  | {
      registered: true;
      email: string | null;
      display_name: string;
      /** Verified (LINKed) FaceTime handle; null until the owner texts LINK <code> (D-25). */
      handle: string | null;
      pending_claim: { handle: string; code: string; expires_at: string; expired: boolean } | null;
      points: number;
      points_today: number;
      valid_reps: number;
      rank: number | null;
      total_users: number;
      calls_today: number;
      calls_left: number;
      daily_call_cap: number | null;
      streak: number;
      avatar_level: number;
      opted_out: boolean;
      banned: boolean;
      queue: { status: QueueStatus; position: number | null; eta: { lo_min: number; hi_min: number } | null };
      claim: { line_id: string; claimed_until: string; seconds_left: number } | null;
      in_call: boolean;
      line_open: boolean;
      brodie_number: string | null;
      started: boolean;
      frozen: boolean;
      server_time?: string;
    };

export type RegisteredMe = Extract<Me, { registered: true }>;

export type WebResult = { ok: boolean; reason: string | null; me: Me };

/** Result of a /me server action. `me` (when present) is the fresh status to render immediately. */
export type MeActionState = { status: number; ok: boolean; message?: string; error?: string; me?: Me };

export const ME_IDLE: MeActionState = { status: 0, ok: false };

export type Phase = "up" | "in_call" | "waiting" | "open" | "idle" | "at_cap" | "closed" | "banned";

/** The single state the /me hero shows, in priority order. */
export function mePhase(me: RegisteredMe): Phase {
  if (me.banned) return "banned";
  if (me.claim && me.claim.seconds_left > 0) return "up";
  if (me.in_call) return "in_call";
  if (me.queue.status === "waiting" || me.queue.status === "notified") return "waiting";
  if (me.frozen || !me.started) return "closed";
  if (me.calls_left <= 0) return "at_cap";
  if (me.line_open) return "open";
  return "idle";
}

/** "~10–15 min" from the dispatcher's bucketed range; "any minute" for the 0–5 bucket. */
export function formatEtaRange(eta: { lo_min: number; hi_min: number } | null): string | null {
  if (!eta) return null;
  if (eta.lo_min <= 0) return "any minute";
  return `~${eta.lo_min}–${eta.hi_min} min`;
}

/**
 * Seconds left on a claim, counted down locally from the last server snapshot (so the banner ticks between polls)
 * while never going below 0. `snapshotAtMs` is the client clock when the snapshot arrived.
 */
export function claimSecondsLeft(secondsAtSnapshot: number, snapshotAtMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil(secondsAtSnapshot - (nowMs - snapshotAtMs) / 1000));
}

export function formatClock(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** facetime: deep link to Brodie's line (digits and + only), or null when the number isn't published. */
export function facetimeLink(brodieNumber: string | null): string | null {
  if (!brodieNumber) return null;
  const n = brodieNumber.replace(/[^\d+]/g, "");
  return /^\+?\d{7,15}$/.test(n) ? `facetime:${n}` : null;
}

/** sms: link that opens Messages to Brodie with "LINK <code>" typed (iOS `&body=` form), or null. */
export function linkSmsHref(brodieNumber: string | null, code: string): string | null {
  if (!brodieNumber || !/^\d{6}$/.test(code)) return null;
  const n = brodieNumber.replace(/[^\d+]/g, "");
  return /^\+?\d{7,15}$/.test(n) ? `sms:${n}&body=${encodeURIComponent(`LINK ${code}`)}` : null;
}

export function ordinalRank(rank: number | null): string {
  return rank ? `#${rank}` : "—";
}

const JOIN_REASONS: Record<string, string> = {
  bad_name: "Names are 3–20 letters, numbers or underscores (and keep it clean).",
  taken: "That name is taken. Try another.",
  bad_handle: "Enter the phone number or Apple ID email you FaceTime from.",
  closed: "Registration is closed.",
  confirm_required: "Confirm you're 18+ and accept the rules.",
};

const QUEUE_REASONS: Record<string, string> = {
  at_cap: "You've used today's calls. Back at midnight ET.",
  in_call: "You're on a call right now.",
  banned: "This account can't queue.",
  frozen: "The competition is over. Scores are final pending verification.",
  not_registered: "Finish signing up first.",
};

export function joinReasonMessage(reason: string | null): string {
  return (reason && JOIN_REASONS[reason]) || "Couldn't sign you up. Try again.";
}

export function queueReasonMessage(reason: string | null): string {
  return (reason && QUEUE_REASONS[reason]) || "Couldn't update your spot. Try again.";
}
