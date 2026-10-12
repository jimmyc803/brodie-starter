import type { CompetitionPublic, LeaderboardRow, LineStatus, PowerHour } from "./types";

/**
 * Deterministic demo data for design/QA (PUSHUP_FIXTURES=1). Never used in production.
 * Contains display names only: no handles, phones or emails.
 */

const NAMES = [
  "Marcus T", "Jess the Beast", "Big Dre", "Coach Lou", "Priya K", "Tank", "Sam R", "Nina V",
  "Diego", "Hannah B", "Kofi", "Ollie", "Rae", "Jordan P", "Mia Strong", "Theo", "Bex", "Luis M",
  "Ava", "Chris O", "Dani", "Ezra", "Fatima", "Gabe", "Hugo", "Ivy", "Jamal", "Kira", "Leo", "Maya",
  "Noah G", "Omar", "Pia", "Quinn", "Ruby", "Sol", "Tess", "Uri", "Val", "Wes", "Xavi", "Yara",
  "Zeke", "Ari", "Bo", "Cam", "Dex", "Eli", "Finn", "Gio", "Hal", "Ines", "Jude", "Kai", "Lena",
  "Max", "Nico", "Odin", "Pax", "Remy",
];

const BADGES: Record<number, string[]> = {
  1: ["Power hour king"],
  2: ["100 club"],
  4: ["Early bird"],
  7: ["100 club"],
};

/** Small LCG so fixture data is stable across renders and builds. */
function rng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

export function fixtureLeaderboard(): LeaderboardRow[] {
  const r = rng(42);
  let points = 1480;
  return NAMES.map((name, i) => {
    const rank = i + 1;
    if (i > 0) points = Math.max(4, points - Math.round(6 + r() * (i < 10 ? 70 : 28)));
    const validReps = Math.round(points / (1.1 + r() * 0.35));
    const streak = rank <= 12 ? Math.max(0, 6 - Math.floor(r() * 5)) : r() > 0.6 ? 1 + Math.floor(r() * 3) : 0;
    const avatarLevel = Math.min(10, Math.max(1, Math.ceil(points / 150)));
    return {
      rank,
      publicId: `fx-${String(rank).padStart(3, "0")}`,
      displayName: name,
      points,
      validReps,
      streak,
      avatarLevel,
      badges: BADGES[rank] ?? [],
      reachedAt: new Date(Date.UTC(2026, 9, 12, 12, 0, rank)).toISOString(),
    };
  });
}

export function fixtureLineStatus(nowMs: number): LineStatus {
  return {
    stateSummary: "in_call",
    queueLength: 4,
    linesActive: 1,
    etaCycleS: 240,
    updatedAt: new Date(nowMs).toISOString(),
  };
}

/** Power hour that is live right now (started 20 min ago, 40 min left). */
export function fixturePowerHour(nowMs: number): PowerHour {
  const start = nowMs - 20 * 60_000;
  return {
    dateEt: new Date(nowMs).toISOString().slice(0, 10),
    startsAt: new Date(start).toISOString(),
    endsAt: new Date(start + 3_600_000).toISOString(),
  };
}

export function fixtureCompetition(frozen: boolean): CompetitionPublic {
  return {
    windowStart: "2026-10-12T04:00:00.000Z",
    windowEnd: "2026-10-19T03:59:59.000Z",
    frozen,
    rafflePrize: "Signed Brodie gloves",
    raffleMinValidReps: 100,
    ufcFighter: null,
    firstPrize: "$100",
    // Short code style number: keeps the demo free of anything phone-shaped.
    brodieNumber: "27632",
    siteUrl: null,
  };
}
