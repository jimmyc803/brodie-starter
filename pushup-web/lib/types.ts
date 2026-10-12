export type LeaderboardRow = {
  rank: number;
  publicId: string;
  displayName: string;
  points: number;
  validReps: number;
  streak: number;
  avatarLevel: number;
  badges: string[];
  reachedAt: string | null;
};

export type LineSummary = "idle" | "in_call" | "offline" | "claimed" | "closed";

export type LineStatus = {
  stateSummary: LineSummary;
  queueLength: number;
  linesActive: number;
  etaCycleS: number | null;
  updatedAt: string | null;
};

export type PowerHour = { dateEt: string; startsAt: string; endsAt: string };

export type CompetitionPublic = {
  windowStart: string;
  windowEnd: string;
  frozen: boolean;
  rafflePrize: string;
  raffleMinValidReps: number;
  brodieNumber: string | null;
  siteUrl: string | null;
};

export type PowerHourStatus =
  | { kind: "none" }
  | { kind: "upcoming"; msUntil: number }
  | { kind: "live"; msLeft: number }
  | { kind: "over" };
