/**
 * Pure rank-change tracking keyed by publicId, shared by the podium and the list
 * so an athlete crossing between them (e.g. 4 -> 3) keeps their arrow.
 */
export type RankDeltaEntry = { delta: number; version: number };
export type RankTrackerState = {
  version: number;
  ranks: Record<string, number>;
  deltas: Record<string, RankDeltaEntry>;
};

export const EMPTY_TRACKER: RankTrackerState = { version: 0, ranks: {}, deltas: {} };

/**
 * Fold a fresh leaderboard snapshot into the tracker. The first snapshot only records ranks.
 * A changed rank replaces any older arrow for that athlete; unchanged athletes keep theirs until expired.
 */
export function trackRanks(
  state: RankTrackerState,
  rows: readonly { publicId: string; rank: number }[],
): RankTrackerState {
  const first = state.version === 0;
  const version = state.version + 1;
  const ranks: Record<string, number> = {};
  const deltas: Record<string, RankDeltaEntry> = {};
  for (const r of rows) {
    ranks[r.publicId] = r.rank;
    const prev = state.ranks[r.publicId];
    if (!first && prev !== undefined && prev !== r.rank) {
      deltas[r.publicId] = { delta: prev - r.rank, version };
    } else if (state.deltas[r.publicId]) {
      deltas[r.publicId] = state.deltas[r.publicId];
    }
  }
  return { version, ranks, deltas };
}

/** Drop arrows created at or before `version` (called when their display time is up). */
export function expireDeltas(state: RankTrackerState, version: number): RankTrackerState {
  const deltas: Record<string, RankDeltaEntry> = {};
  let changed = false;
  for (const [id, d] of Object.entries(state.deltas)) {
    if (d.version > version) deltas[id] = d;
    else changed = true;
  }
  return changed ? { ...state, deltas } : state;
}

/** Version of the newest arrow still showing, or null when none. Drives the expiry timer. */
export function latestDeltaVersion(state: RankTrackerState): number | null {
  let max: number | null = null;
  for (const d of Object.values(state.deltas)) if (max == null || d.version > max) max = d.version;
  return max;
}
