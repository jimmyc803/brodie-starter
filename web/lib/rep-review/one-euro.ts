import type { PoseTrack } from "./pose-types";

const alpha = (cutoff: number, dt: number) => {
  const tau = 1 / (2 * Math.PI * cutoff);
  return 1 / (1 + tau / dt);
};

// One Euro filter (Casiez et al.): low-pass whose cutoff rises with signal speed.
export class OneEuroFilter {
  private xPrev: number | null = null;
  private dxPrev = 0;
  private tPrev = 0;

  constructor(
    private minCutoff = 1.2,
    private beta = 0.02,
    private dCutoff = 1,
  ) {}

  filter(x: number, t: number): number {
    if (this.xPrev === null) {
      this.xPrev = x;
      this.tPrev = t;
      return x;
    }
    const dt = t - this.tPrev;
    if (dt <= 0) return this.xPrev;
    const dx = (x - this.xPrev) / dt;
    const dxHat = this.dxPrev + alpha(this.dCutoff, dt) * (dx - this.dxPrev);
    const cutoff = this.minCutoff + this.beta * Math.abs(dxHat);
    const xHat = this.xPrev + alpha(cutoff, dt) * (x - this.xPrev);
    this.xPrev = xHat;
    this.dxPrev = dxHat;
    this.tPrev = t;
    return xHat;
  }

  reset() {
    this.xPrev = null;
    this.dxPrev = 0;
    this.tPrev = 0;
  }
}

const LANDMARKS = 33;
const MIN_VISIBILITY = 0.3;

// Smooth every landmark x/y over time; low-visibility samples hold the previous filtered value.
export function smoothTrack(track: PoseTrack, minCutoff = 1.2, beta = 0.02): PoseTrack {
  const filters = Array.from({ length: LANDMARKS * 2 }, () => new OneEuroFilter(minCutoff, beta));
  const last: number[] = new Array(LANDMARKS * 2).fill(NaN);
  const frames = track.frames.map((row) => {
    const out = row.slice();
    const t = row[0];
    for (let i = 0; i < LANDMARKS; i++) {
      const base = 1 + i * 3;
      const vis = row[base + 2];
      for (let c = 0; c < 2; c++) {
        const k = i * 2 + c;
        if (vis < MIN_VISIBILITY && !Number.isNaN(last[k])) {
          out[base + c] = last[k];
        } else {
          last[k] = filters[k].filter(row[base + c], t);
          out[base + c] = last[k];
        }
      }
    }
    return out;
  });
  return { ...track, frames };
}
