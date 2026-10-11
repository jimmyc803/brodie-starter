import { ACCENTS, type ReviewClip, type ReviewRep } from "@/lib/rep-review/clips.config";
import { sampleJoints } from "@/lib/rep-review/pose";
import { JOINT, type JointName, type PoseTrack } from "@/lib/rep-review/pose-types";
import type { Sfx } from "@/lib/rep-review/sfx";

// Canvas renderer + timeline for the rep review player. One canvas draws the graded video frame and every overlay
// (so a screen recording and Export look identical); the timeline is driven by video.currentTime, the rep clicker by
// the hardcoded rep timestamps. Phases: intro (title slam, video held) → play → end (frozen frame + set card).

export type Phase = "intro" | "play" | "end";
export type Fonts = { display: string; cond: string; ui: string };
export type EngineOpts = {
  mode: "coach" | "client";
  clientName: string;
  fonts: Fonts;
  sfx: Sfx;
  letterbox: boolean;
  onPhase: (p: Phase) => void;
};

const AMBER = "#FFB020";
const RED = "#FF2D2D";
const CHALK = "#F4F4F0";
const GRAPHITE = "#17171A";

const INTRO_MS = 950;
const SLOWMO_MS = 1200;
const SLOWMO_RATE = 0.35;
const CUE_MS = 3400;
const STAMP_MS = 1500;
const TRACE_S = 1.5;
const VIS = 0.45;

const BONES: [JointName, JointName][] = [
  ["left_shoulder", "right_shoulder"],
  ["left_shoulder", "left_elbow"],
  ["left_elbow", "left_wrist"],
  ["right_shoulder", "right_elbow"],
  ["right_elbow", "right_wrist"],
  ["left_shoulder", "left_hip"],
  ["right_shoulder", "right_hip"],
  ["left_hip", "right_hip"],
  ["left_hip", "left_knee"],
  ["left_knee", "left_ankle"],
  ["right_hip", "right_knee"],
  ["right_knee", "right_ankle"],
];
const DOTS = Object.keys(JOINT).filter((j) => j !== "nose") as JointName[];

// cubic-bezier(.2,.8,.2,1): the house easing for every move.
function bezier(x1: number, y1: number, x2: number, y2: number) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx;
  const cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const sx = (t: number) => ((ax * t + bx) * t + cx) * t;
  const sy = (t: number) => ((ay * t + by) * t + cy) * t;
  const dsx = (t: number) => (3 * ax * t + 2 * bx) * t + cx;
  return (x: number) => {
    if (x <= 0) return 0;
    if (x >= 1) return 1;
    let t = x;
    for (let i = 0; i < 6; i++) {
      const d = dsx(t);
      if (Math.abs(d) < 1e-6) break;
      t -= (sx(t) - x) / d;
    }
    return sy(Math.min(1, Math.max(0, t)));
  };
}
const ease = bezier(0.2, 0.8, 0.2, 1);
const easeIn = (x: number) => x * x * x;
const backOut = (x: number) => {
  const c = 1.9;
  const p = Math.min(1, Math.max(0, x)) - 1;
  return 1 + (c + 1) * p * p * p + c * p * p;
};
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const prog = (now: number, start: number, dur: number) => clamp01((now - start) / dur);

export function scoreColor(score: number, flagged: boolean, accent: string) {
  if (flagged || score < 75) return RED;
  if (score < 85) return AMBER;
  return accent;
}

function parseTarget(target?: string): ((deg: number) => boolean) | null {
  const m = target?.match(/([<>])\s*(\d+(?:\.\d+)?)/);
  if (!m) return null;
  const v = Number(m[2]);
  return m[1] === "<" ? (d) => d < v : (d) => d > v;
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, r);
}

function withAlpha(hex: string, a: number) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

type Pt = { x: number; y: number; v: number };

export class ReviewEngine {
  readonly canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private video: HTMLVideoElement;
  private clip: ReviewClip;
  private track: PoseTrack | null;
  private o: EngineOpts;
  private accent: string;
  private W: number;
  private H: number;
  private u: number; // layout unit: 1 at 1080 px on the short side
  private raf = 0;
  private alive = true;

  phase: Phase = "intro";
  private introStart = 0;
  private endStart = 0;
  private lastT = 0;
  private repsDone = 0;
  private repAt = -1e9; // performance.now() of the last click
  private prevDigits = "00";
  private ringFrac = 0;
  private ringScore = 0;
  private flagIdx = -1; // rep currently in its flag moment
  private slowStart = -1e9;
  private stampAt = -1e9;
  private flagsDone = new Set<number>();
  private zoom = 1;
  private focus = { x: 0, y: 0 };
  private shakeAt = -1e9;
  private shakeAmp = 0;
  private hitAt: number[] = [];
  private wasHit: boolean[] = [];
  private chimed = false;
  private grain: HTMLCanvasElement[] = [];
  private vignette: HTMLCanvasElement;
  private frozen: HTMLCanvasElement | null = null;
  private targets: (((d: number) => boolean) | null)[];
  private canFilter: boolean;
  private flashAt = -1e9;
  private wholeEndHook: (() => void) | null = null;

  constructor(canvas: HTMLCanvasElement, video: HTMLVideoElement, clip: ReviewClip, track: PoseTrack | null, o: EngineOpts) {
    this.canvas = canvas;
    this.video = video;
    this.clip = clip;
    this.track = track;
    this.o = o;
    this.accent = ACCENTS[clip.accent ?? "volt"];
    const portrait = video.videoHeight >= video.videoWidth;
    this.W = portrait ? 1080 : 1920;
    this.H = portrait ? 1920 : 1080;
    canvas.width = this.W;
    canvas.height = this.H;
    this.u = Math.min(this.W, this.H) / 1080;
    this.ctx = canvas.getContext("2d", { alpha: false })!;
    this.canFilter = "filter" in this.ctx;
    this.targets = clip.trackedAngles.map((a) => parseTarget(a.target));
    this.hitAt = clip.trackedAngles.map(() => -1e9);
    this.wasHit = clip.trackedAngles.map(() => false);
    this.vignette = this.makeVignette();
    for (let i = 0; i < 4; i++) this.grain.push(this.makeGrain());
    this.focus = { x: this.W / 2, y: this.H / 2 };
    video.addEventListener("ended", this.onEnded);
  }

  get size() {
    return { w: this.W, h: this.H };
  }

  // Runs once, now: called after the clip and fonts are ready.
  start() {
    this.reset();
    this.loop();
  }

  replay() {
    this.reset();
  }

  // Called once the end card has finished animating (Export stops recording there).
  onceSettled(fn: () => void) {
    this.wholeEndHook = fn;
  }

  destroy() {
    this.alive = false;
    cancelAnimationFrame(this.raf);
    this.video.removeEventListener("ended", this.onEnded);
    this.video.pause();
  }

  private reset() {
    const v = this.video;
    v.pause();
    v.playbackRate = 1;
    v.currentTime = 0;
    this.repsDone = 0;
    this.prevDigits = "00";
    this.repAt = -1e9;
    this.ringFrac = 0;
    this.ringScore = 0;
    this.flagIdx = -1;
    this.flagsDone.clear();
    this.slowStart = this.stampAt = this.shakeAt = this.flashAt = -1e9;
    this.zoom = 1;
    this.frozen = null;
    this.chimed = false;
    this.lastT = 0;
    this.hitAt = this.hitAt.map(() => -1e9);
    this.wasHit = this.wasHit.map(() => false);
    this.setPhase("intro");
    this.introStart = performance.now();
    this.o.sfx.whoosh();
  }

  private setPhase(p: Phase) {
    this.phase = p;
    this.o.onPhase(p);
  }

  private onEnded = () => {
    if (this.phase === "play") this.toEnd();
  };

  private toEnd() {
    this.video.pause();
    this.video.playbackRate = 1;
    this.frozen = this.freezeFrame();
    this.endStart = performance.now();
    this.setPhase("end");
  }

  private loop = () => {
    if (!this.alive) return;
    this.raf = requestAnimationFrame(this.loop);
    this.tick(performance.now());
  };

  private tick(now: number) {
    const v = this.video;
    if (this.phase === "intro") {
      const k = now - this.introStart;
      if (k > 300 && k < 340 && this.shakeAt < this.introStart) {
        this.o.sfx.slam();
        this.shake(now, 16);
        this.flashAt = now;
      }
      if (k >= INTRO_MS) {
        this.setPhase("play");
        void v.play().catch(() => {});
      }
    }
    const t = v.currentTime;
    if (this.phase === "play") {
      this.updateReps(t, now);
      this.updateFlag(t, now);
      if (v.duration && t >= v.duration - 0.04) this.toEnd();
    }
    this.lastT = t;
    this.draw(now, t);
    if (this.phase === "end" && now - this.endStart > 3600 && this.wholeEndHook) {
      const fn = this.wholeEndHook;
      this.wholeEndHook = null;
      fn();
    }
  }

  private updateReps(t: number, now: number) {
    const done = this.clip.reps.filter((r) => r.t <= t).length;
    if (done > this.repsDone) {
      this.prevDigits = String(this.repsDone).padStart(2, "0");
      this.repsDone = done;
      this.repAt = now;
      this.o.sfx.click();
    } else if (done < this.repsDone) {
      this.repsDone = done; // seeked back
      this.prevDigits = String(done).padStart(2, "0");
    }
  }

  private faultTime(r: ReviewRep) {
    return r.faultAt ?? r.t - 0.45;
  }

  // Flag moment: slow to 0.35x just before the fault, punch in, stamp the flag at the fault, back to 1x after ~1.2 s.
  private updateFlag(t: number, now: number) {
    const reps = this.clip.reps;
    if (this.flagIdx < 0) {
      const i = reps.findIndex((r, idx) => r.flag && !this.flagsDone.has(idx) && t >= this.faultTime(r) - 0.22 && t < r.t + 0.3);
      if (i >= 0) {
        this.flagIdx = i;
        this.flagsDone.add(i);
        this.slowStart = now;
        this.stampAt = -1e9;
        this.video.playbackRate = SLOWMO_RATE;
      }
      return;
    }
    const r = reps[this.flagIdx];
    if (this.stampAt < this.slowStart && t >= this.faultTime(r)) {
      this.stampAt = now;
      this.shake(now, 22);
      this.o.sfx.stamp();
    }
    if (now - this.slowStart >= SLOWMO_MS && this.stampAt >= this.slowStart) {
      this.video.playbackRate = 1;
      if (now - this.stampAt > CUE_MS) this.flagIdx = -1;
    }
  }

  private shake(now: number, amp: number) {
    this.shakeAt = now;
    this.shakeAmp = amp * this.u;
  }

  // ---- geometry ------------------------------------------------------------------------------------------------

  private coverRect() {
    const vw = this.video.videoWidth || 9;
    const vh = this.video.videoHeight || 16;
    const s = Math.max(this.W / vw, this.H / vh);
    return { x: (this.W - vw * s) / 2, y: (this.H - vh * s) / 2, w: vw * s, h: vh * s };
  }

  private joints(t: number): Record<JointName, Pt> | null {
    if (!this.track) return null;
    const row = sampleJoints(this.track, t);
    if (!row) return null;
    const r = this.coverRect();
    const out = {} as Record<JointName, Pt>;
    for (const [name, i] of Object.entries(JOINT) as [JointName, number][]) {
      out[name] = { x: r.x + row[i * 3] * r.w, y: r.y + row[i * 3 + 1] * r.h, v: row[i * 3 + 2] };
    }
    return out;
  }

  private inFlagWindow(t: number) {
    const reps = this.clip.reps;
    return reps.some((r, i) => r.flag && t >= (i > 0 ? reps[i - 1].t : 0) + 0.05 && t <= r.t + 0.2);
  }

  // ---- drawing -------------------------------------------------------------------------------------------------

  private draw(now: number, t: number) {
    const { ctx, W, H } = this;
    const J = this.phase === "end" ? null : this.joints(t);
    const flagged = this.inFlagWindow(t);

    // Camera: punch-in during the flag moment, centred on the hips; screen shake on slams/stamps.
    const slow = this.flagIdx >= 0 && this.video.playbackRate < 1;
    const zTarget = slow ? 1.15 : 1;
    this.zoom = lerp(this.zoom, zTarget, slow ? 0.12 : 0.06);
    if (J && J.left_hip.v > 0.3) {
      const fx = (J.left_hip.x + J.right_hip.x) / 2;
      const fy = (J.left_hip.y + J.right_hip.y) / 2;
      this.focus.x = lerp(this.focus.x, fx, 0.1);
      this.focus.y = lerp(this.focus.y, fy, 0.1);
    }
    const sk = prog(now, this.shakeAt, 260);
    const amp = sk < 1 ? this.shakeAmp * (1 - sk) * (1 - sk) : 0;
    const sx = amp ? (Math.random() * 2 - 1) * amp : 0;
    const sy = amp ? (Math.random() * 2 - 1) * amp : 0;

    ctx.save();
    ctx.fillStyle = "#0A0A0A";
    ctx.fillRect(0, 0, W, H);
    ctx.translate(sx, sy);
    ctx.translate(this.focus.x, this.focus.y);
    ctx.scale(this.zoom, this.zoom);
    ctx.translate(-this.focus.x, -this.focus.y);

    if (this.phase === "end" && this.frozen) {
      ctx.drawImage(this.frozen, 0, 0, W, H);
    } else {
      this.drawVideo();
      if (J && this.phase === "play") {
        this.drawTrace(t, flagged);
        this.drawSkeleton(J, flagged);
        if (this.flagIdx < 0) this.drawAngles(J, now, flagged); // the flag + cue own the screen during the flag moment
      }
    }
    ctx.restore();

    // Grade layers: vignette, grain, edge gradients for HUD legibility, letterbox.
    ctx.drawImage(this.vignette, 0, 0);
    if (this.phase !== "end") this.drawEdgeShade();
    this.drawGrain();
    if (flagged && this.phase === "play") this.drawRedPulse(now);
    const bar = this.o.letterbox ? Math.round(H * 0.032) : 0;
    if (bar) {
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, W, bar);
      ctx.fillRect(0, H - bar, W, bar);
    }

    ctx.save();
    ctx.translate(sx * 0.5, sy * 0.5);
    if (this.phase === "intro") this.drawIntro(now, bar);
    if (this.phase === "play") {
      this.drawLockup(bar, 1);
      this.drawClicker(now, bar);
      this.drawRing(bar);
      this.drawFlagMoment(now, bar);
    }
    if (this.phase === "end") this.drawEndCard(now, bar);
    ctx.restore();

    const fl = prog(now, this.flashAt, 220);
    if (fl < 1) {
      ctx.fillStyle = `rgba(255,255,255,${0.16 * (1 - fl)})`;
      ctx.fillRect(0, 0, W, H);
    }
  }

  private drawVideo() {
    const { ctx } = this;
    const r = this.coverRect();
    if (this.canFilter) ctx.filter = "contrast(1.12) saturate(1.06) brightness(0.96) sepia(0.07)";
    if (this.video.readyState >= 2) ctx.drawImage(this.video, r.x, r.y, r.w, r.h);
    if (this.canFilter) ctx.filter = "none";
    if (this.phase === "intro") {
      const k = (performance.now() - this.introStart) / INTRO_MS;
      ctx.fillStyle = `rgba(6,6,6,${0.72 * (1 - ease(clamp01((k - 0.55) / 0.45)))})`;
      ctx.fillRect(0, 0, this.W, this.H);
    }
  }

  private glowLine(pts: { x: number; y: number }[], color: string, width: number, glow: number, alpha = 1) {
    const { ctx } = this;
    if (pts.length < 2) return;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.globalCompositeOperation = "lighter";
    for (const [w, a] of [
      [width * 4.2, 0.08],
      [width * 2.2, 0.2],
    ] as const) {
      ctx.strokeStyle = withAlpha(color, a * alpha);
      ctx.lineWidth = w;
      ctx.beginPath();
      pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
      ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
    ctx.shadowColor = color;
    ctx.shadowBlur = glow;
    ctx.strokeStyle = withAlpha(color, 0.95 * alpha);
    ctx.lineWidth = width;
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y)));
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = `rgba(255,255,255,${0.55 * alpha})`;
    ctx.lineWidth = Math.max(1, width * 0.35);
    ctx.stroke();
    ctx.restore();
  }

  private drawSkeleton(J: Record<JointName, Pt>, flagged: boolean) {
    const { ctx, u } = this;
    const color = flagged ? RED : this.accent;
    for (const [a, b] of BONES) {
      if (J[a].v < VIS || J[b].v < VIS) continue;
      this.glowLine([J[a], J[b]], color, 5 * u, 18 * u);
    }
    ctx.save();
    for (const name of DOTS) {
      const p = J[name];
      if (p.v < VIS) continue;
      const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 26 * u);
      g.addColorStop(0, withAlpha(color, 0.55));
      g.addColorStop(1, withAlpha(color, 0));
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 26 * u, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = "#0A0A0A";
      ctx.beginPath();
      ctx.arc(p.x, p.y, 9 * u, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 3.5 * u;
      ctx.strokeStyle = CHALK;
      ctx.stroke();
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(p.x, p.y, 4.5 * u, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.restore();
  }

  // The trace joint's path over the last 1.5 s, sampled from the cached track (deterministic, no history buffer).
  private drawTrace(t: number, flagged: boolean) {
    if (!this.track) return;
    const idx = JOINT[this.clip.traceJoint];
    const r = this.coverRect();
    const pts: { x: number; y: number }[] = [];
    for (let s = Math.max(0, t - TRACE_S); s <= t + 1e-3; s += 1 / 30) {
      const row = sampleJoints(this.track, s);
      if (!row || row[idx * 3 + 2] < VIS) continue;
      pts.push({ x: r.x + row[idx * 3] * r.w, y: r.y + row[idx * 3 + 1] * r.h });
    }
    const color = flagged ? RED : this.accent;
    const n = pts.length;
    for (let i = 1; i < n; i++) {
      const a = i / n;
      this.glowLine([pts[i - 1], pts[i]], color, (2 + 5 * a) * this.u, 12 * this.u, a * a);
    }
  }

  private drawAngles(J: Record<JointName, Pt>, now: number, flagged: boolean) {
    const { ctx, u } = this;
    this.clip.trackedAngles.forEach((ang, i) => {
      const [a, b, c] = ang.joints.map((j) => J[j]);
      if (a.v < VIS || b.v < VIS || c.v < VIS) return;
      const a1 = Math.atan2(a.y - b.y, a.x - b.x);
      const a2 = Math.atan2(c.y - b.y, c.x - b.x);
      let d = a2 - a1;
      while (d > Math.PI) d -= 2 * Math.PI;
      while (d < -Math.PI) d += 2 * Math.PI;
      const deg = Math.round(Math.abs(d) * (180 / Math.PI));
      const hit = this.targets[i]?.(deg) ?? false;
      if (hit && !this.wasHit[i]) this.hitAt[i] = now;
      this.wasHit[i] = hit;
      const color = flagged ? RED : hit ? this.accent : CHALK;

      // Arc between the two limbs.
      ctx.save();
      ctx.strokeStyle = withAlpha(color, 0.9);
      ctx.lineWidth = 3 * u;
      ctx.shadowColor = color;
      ctx.shadowBlur = 10 * u;
      ctx.beginPath();
      ctx.arc(b.x, b.y, 54 * u, a1, a1 + d, d < 0);
      ctx.stroke();
      ctx.restore();

      // Pill on the outside of the joint.
      const side = Math.cos((a1 + a2) / 2) > 0 ? -1 : 1;
      const label = `${ang.name.toUpperCase()} ${deg}°`;
      ctx.save();
      ctx.font = `700 ${36 * u}px ${this.o.fonts.cond}`;
      const tw = ctx.measureText(label).width;
      const pw = tw + 36 * u;
      const ph = 58 * u;
      const px = side > 0 ? b.x + 70 * u : b.x - 70 * u - pw;
      const py = b.y - ph / 2;
      const pop = this.hitAt[i] > 0 ? 1 + 0.18 * (1 - ease(prog(now, this.hitAt[i], 320))) : 1;
      ctx.translate(px + pw / 2, py + ph / 2);
      ctx.scale(pop, pop);
      ctx.translate(-(px + pw / 2), -(py + ph / 2));
      roundRect(ctx, px, py, pw, ph, ph / 2);
      ctx.fillStyle = hit || flagged ? color : withAlpha(GRAPHITE, 0.82);
      if (hit) {
        ctx.shadowColor = color;
        ctx.shadowBlur = 24 * u;
      }
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.lineWidth = 1.5 * u;
      ctx.strokeStyle = hit || flagged ? "transparent" : "rgba(255,255,255,0.16)";
      ctx.stroke();
      ctx.fillStyle = hit || flagged ? "#0A0A0A" : CHALK;
      ctx.textBaseline = "middle";
      ctx.fillText(label, px + 18 * u, py + ph / 2 + 1 * u);
      // leader line to the joint
      ctx.strokeStyle = withAlpha(color, 0.5);
      ctx.lineWidth = 2 * u;
      ctx.beginPath();
      ctx.moveTo(b.x + side * 14 * u, b.y);
      ctx.lineTo(side > 0 ? px : px + pw, b.y);
      ctx.stroke();
      ctx.restore();
    });
  }

  private makeVignette() {
    const c = document.createElement("canvas");
    c.width = this.W;
    c.height = this.H;
    const x = c.getContext("2d")!;
    const g = x.createRadialGradient(this.W / 2, this.H * 0.48, Math.min(this.W, this.H) * 0.32, this.W / 2, this.H / 2, Math.hypot(this.W, this.H) * 0.62);
    g.addColorStop(0, "rgba(0,0,0,0)");
    g.addColorStop(1, "rgba(0,0,0,0.62)");
    x.fillStyle = g;
    x.fillRect(0, 0, this.W, this.H);
    return c;
  }

  private makeGrain() {
    const c = document.createElement("canvas");
    c.width = c.height = 192;
    const x = c.getContext("2d")!;
    const img = x.createImageData(192, 192);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.random() * 255;
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    x.putImageData(img, 0, 0);
    return c;
  }

  private drawGrain() {
    const { ctx } = this;
    const tile = this.grain[Math.floor(Math.random() * this.grain.length)];
    const pat = ctx.createPattern(tile, "repeat");
    if (!pat) return;
    ctx.save();
    ctx.globalAlpha = 0.06;
    ctx.globalCompositeOperation = "overlay";
    ctx.translate(Math.random() * 192, Math.random() * 192);
    ctx.fillStyle = pat;
    ctx.fillRect(-192, -192, this.W + 192, this.H + 192);
    ctx.restore();
  }

  private drawEdgeShade() {
    const { ctx, W, H } = this;
    const top = ctx.createLinearGradient(0, 0, 0, H * 0.22);
    top.addColorStop(0, "rgba(0,0,0,0.6)");
    top.addColorStop(1, "rgba(0,0,0,0)");
    ctx.fillStyle = top;
    ctx.fillRect(0, 0, W, H * 0.22);
    const bot = ctx.createLinearGradient(0, H * 0.7, 0, H);
    bot.addColorStop(0, "rgba(0,0,0,0)");
    bot.addColorStop(1, "rgba(0,0,0,0.72)");
    ctx.fillStyle = bot;
    ctx.fillRect(0, H * 0.7, W, H * 0.3);
  }

  private drawRedPulse(now: number) {
    const { ctx, W, H } = this;
    const a = 0.16 + 0.08 * Math.sin(now / 140);
    const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.35, W / 2, H / 2, Math.hypot(W, H) * 0.6);
    g.addColorStop(0, "rgba(255,45,45,0)");
    g.addColorStop(1, `rgba(255,45,45,${a})`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H);
  }

  // ---- HUD ----------------------------------------------------------------------------------------------------

  private lockupPos(bar: number) {
    return { x: 56 * this.u, y: bar + 64 * this.u, size: 84 * this.u };
  }

  private drawLockup(bar: number, alpha: number, titleOverride?: { x: number; y: number; size: number }, extrasOnly = false) {
    const { ctx, u } = this;
    const L = titleOverride ?? this.lockupPos(bar);
    const title = this.clip.exercise.toUpperCase();
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.textBaseline = "top";
    ctx.fillStyle = CHALK;
    ctx.font = `400 ${L.size}px ${this.o.fonts.display}`;
    if (!extrasOnly) ctx.fillText(title, L.x, L.y);
    const tw = ctx.measureText(title).width;
    if (!titleOverride) {
      ctx.fillStyle = this.accent;
      ctx.fillText(` · ${this.clip.setLabel.toUpperCase()}`, L.x + tw, L.y);
      ctx.font = `600 ${21 * u}px ${this.o.fonts.ui}`;
      ctx.letterSpacing = `${4 * u}px`;
      ctx.fillStyle = withAlpha(CHALK, 0.72);
      const y2 = L.y + L.size * 0.98;
      ctx.fillRect(L.x, y2 + 11 * u, 28 * u, 3 * u);
      ctx.fillText(`PROGRAM BY ${this.clip.coachName.toUpperCase()}`, L.x + 40 * u, y2);
      ctx.fillStyle = withAlpha(CHALK, 0.45);
      ctx.fillText(this.o.clientName.toUpperCase(), L.x + 40 * u, y2 + 32 * u);
      ctx.letterSpacing = "0px";
    }
    ctx.restore();
  }

  private drawIntro(now: number, bar: number) {
    const { ctx, W, H, u } = this;
    const k = now - this.introStart;
    const title = this.clip.exercise.toUpperCase();
    const L = this.lockupPos(bar);
    ctx.save();
    ctx.font = `400 100px ${this.o.fonts.display}`;
    const w100 = ctx.measureText(title).width;
    ctx.restore();
    const big = Math.min(300 * u, ((W * 0.86) / w100) * 100);
    const bigW = (w100 / 100) * big;
    const center = { x: (W - bigW) / 2, y: H * 0.42 - big / 2, size: big };

    if (k < 300) {
      // Slam: falls in from 2.2x with motion smear.
      const p = easeIn(clamp01(k / 300));
      const s = lerp(2.2, 1, p);
      ctx.save();
      ctx.translate(W / 2, H * 0.42);
      ctx.scale(s, s);
      ctx.translate(-W / 2, -H * 0.42);
      for (let i = 3; i >= 0; i--) this.drawLockup(bar, (p * (i === 0 ? 1 : 0.14)) / 1, { ...center, y: center.y - i * 14 * u * (1 - p) });
      ctx.restore();
    } else if (k < 540) {
      this.drawLockup(bar, 1, center);
      ctx.save();
      ctx.textAlign = "center";
      ctx.font = `600 ${24 * u}px ${this.o.fonts.ui}`;
      ctx.letterSpacing = `${6 * u}px`;
      ctx.fillStyle = withAlpha(this.accent, ease(clamp01((k - 330) / 150)));
      ctx.fillText(`${this.clip.setLabel.toUpperCase()} · PROGRAM BY ${this.clip.coachName.toUpperCase()}`, W / 2, center.y + big + 30 * u);
      ctx.restore();
    } else {
      const p = ease(clamp01((k - 540) / (INTRO_MS - 540)));
      const pos = { x: lerp(center.x, L.x, p), y: lerp(center.y, L.y, p), size: lerp(big, L.size, p) };
      this.drawLockup(bar, 1, pos);
      if (p > 0.9) this.drawLockup(bar, (p - 0.9) / 0.1, undefined, true);
    }
  }

  // Mechanical tally counter, top right: two digit wheels that roll up on every rep, the rep's score flashes below.
  private drawClicker(now: number, bar: number) {
    const { ctx, u } = this;
    const total = this.clip.reps.length;
    const slotW = 84 * u;
    const slotH = 122 * u;
    const gap = 8 * u;
    const pad = 14 * u;
    const boxW = slotW * 2 + gap + pad * 2;
    const boxH = slotH + pad * 2;
    const x = this.W - 56 * u - boxW;
    const y = bar + 64 * u;
    const p = backOut(prog(now, this.repAt, 300));
    const cur = String(this.repsDone).padStart(2, "0");

    ctx.save();
    ctx.font = `600 ${19 * u}px ${this.o.fonts.ui}`;
    ctx.letterSpacing = `${4 * u}px`;
    ctx.fillStyle = withAlpha(CHALK, 0.6);
    ctx.textBaseline = "bottom";
    ctx.fillText("REPS", x + 2 * u, y - 10 * u);
    ctx.textAlign = "right";
    ctx.fillText(`OF ${String(total).padStart(2, "0")}`, x + boxW - 2 * u, y - 10 * u);
    ctx.letterSpacing = "0px";
    ctx.textAlign = "left";

    // housing
    roundRect(ctx, x, y, boxW, boxH, 18 * u);
    const hg = ctx.createLinearGradient(0, y, 0, y + boxH);
    hg.addColorStop(0, "#2A2A2E");
    hg.addColorStop(1, "#111113");
    ctx.fillStyle = hg;
    ctx.shadowColor = "rgba(0,0,0,0.6)";
    ctx.shadowBlur = 30 * u;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1.5 * u;
    ctx.stroke();

    for (let d = 0; d < 2; d++) {
      const sx = x + pad + d * (slotW + gap);
      const sy = y + pad;
      ctx.save();
      roundRect(ctx, sx, sy, slotW, slotH, 8 * u);
      ctx.fillStyle = "#050505";
      ctx.fill();
      ctx.clip();
      ctx.font = `400 ${slotH * 1.02}px ${this.o.fonts.display}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      const changed = this.prevDigits[d] !== cur[d] && p < 1;
      const cy = sy + slotH / 2 + 5 * u;
      if (changed) {
        ctx.fillStyle = withAlpha(CHALK, 1 - p);
        ctx.fillText(this.prevDigits[d], sx + slotW / 2, cy - p * slotH);
        ctx.fillStyle = CHALK;
        ctx.fillText(cur[d], sx + slotW / 2, cy + (1 - p) * slotH);
      } else {
        ctx.fillStyle = CHALK;
        ctx.fillText(cur[d], sx + slotW / 2, cy);
      }
      // wheel shading + split line
      const sg = ctx.createLinearGradient(0, sy, 0, sy + slotH);
      sg.addColorStop(0, "rgba(0,0,0,0.75)");
      sg.addColorStop(0.28, "rgba(0,0,0,0)");
      sg.addColorStop(0.72, "rgba(0,0,0,0)");
      sg.addColorStop(1, "rgba(0,0,0,0.75)");
      ctx.fillStyle = sg;
      ctx.fillRect(sx, sy, slotW, slotH);
      ctx.fillStyle = "rgba(0,0,0,0.7)";
      ctx.fillRect(sx, sy + slotH / 2 - 1 * u, slotW, 2 * u);
      ctx.restore();
    }

    // Rep score flash.
    const last = this.clip.reps[this.repsDone - 1];
    const age = now - this.repAt;
    if (last && age < 1700) {
      const inP = backOut(clamp01(age / 220));
      const out = 1 - clamp01((age - 1400) / 300);
      const color = scoreColor(last.score, Boolean(last.flag), this.accent);
      const text = `REP ${this.repsDone} · ${last.score}`;
      ctx.font = `700 ${34 * u}px ${this.o.fonts.cond}`;
      ctx.letterSpacing = `${1.5 * u}px`;
      const tw = ctx.measureText(text).width;
      const pw = tw + 40 * u;
      const ph = 56 * u;
      const px = x + boxW - pw;
      const py = y + boxH + 16 * u;
      ctx.globalAlpha = out;
      ctx.translate(px + pw, py);
      ctx.scale(inP, inP);
      ctx.translate(-(px + pw), -py);
      roundRect(ctx, px, py, pw, ph, 10 * u);
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = 28 * u;
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.fillStyle = "#0A0A0A";
      ctx.textBaseline = "middle";
      ctx.fillText(text, px + 20 * u, py + ph / 2 + 2 * u);
    }
    ctx.restore();
  }

  // Set score ring, bottom left: fills rep by rep, showing the running average.
  private drawRing(bar: number) {
    const { ctx, u } = this;
    const reps = this.clip.reps;
    const done = reps.slice(0, this.repsDone);
    const avg = done.length ? done.reduce((s, r) => s + r.score, 0) / done.length : 0;
    this.ringFrac = lerp(this.ringFrac, reps.length ? done.length / reps.length : 0, 0.12);
    this.ringScore = lerp(this.ringScore, avg, 0.15);
    const R = 76 * u;
    const cx = 56 * u + R;
    const cy = this.H - bar - 64 * u - R;
    const color = done.length ? scoreColor(avg, false, this.accent) : CHALK;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, R + 16 * u, 0, Math.PI * 2);
    ctx.fillStyle = "rgba(10,10,10,0.55)";
    ctx.fill();
    ctx.lineCap = "round";
    ctx.lineWidth = 10 * u;
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.stroke();
    if (this.ringFrac > 0.003) {
      ctx.strokeStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = 18 * u;
      ctx.beginPath();
      ctx.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + this.ringFrac * Math.PI * 2);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
    // tick marks per rep
    ctx.strokeStyle = "rgba(10,10,10,0.9)";
    ctx.lineWidth = 3 * u;
    for (let i = 0; i < reps.length; i++) {
      const a = -Math.PI / 2 + (i / reps.length) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(cx + Math.cos(a) * (R - 7 * u), cy + Math.sin(a) * (R - 7 * u));
      ctx.lineTo(cx + Math.cos(a) * (R + 7 * u), cy + Math.sin(a) * (R + 7 * u));
      ctx.stroke();
    }
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = CHALK;
    ctx.font = `400 ${78 * u}px ${this.o.fonts.display}`;
    ctx.fillText(done.length ? String(Math.round(this.ringScore)) : "—", cx, cy + 4 * u);
    ctx.font = `600 ${16 * u}px ${this.o.fonts.ui}`;
    ctx.letterSpacing = `${3 * u}px`;
    ctx.fillStyle = withAlpha(CHALK, 0.6);
    ctx.textAlign = "left";
    ctx.fillText("SET SCORE", cx + R + 32 * u, cy - 14 * u);
    ctx.fillStyle = withAlpha(CHALK, 0.4);
    ctx.fillText(`${done.length}/${reps.length} REPS`, cx + R + 32 * u, cy + 16 * u);
    ctx.restore();
  }

  // Flag stamp (red, rotated, with a rubber-stamp border) + the coach's standard as a lower third.
  private drawFlagMoment(now: number, bar: number) {
    if (this.flagIdx < 0 || this.stampAt < this.slowStart) return;
    const { ctx, W, H, u } = this;
    const r = this.clip.reps[this.flagIdx];
    const age = now - this.stampAt;

    if (age < STAMP_MS + 300 && r.flag) {
      const pin = clamp01(age / 130);
      const s = lerp(1.7, 1, easeIn(pin));
      const a = pin * (1 - clamp01((age - STAMP_MS) / 300));
      const text = r.flag.toUpperCase();
      ctx.save();
      ctx.translate(W / 2, H * 0.3);
      ctx.rotate((-6 * Math.PI) / 180);
      ctx.scale(s, s);
      ctx.globalAlpha = a;
      ctx.font = `400 ${150 * u}px ${this.o.fonts.display}`;
      ctx.letterSpacing = `${4 * u}px`;
      const tw = ctx.measureText(text).width;
      const bw = tw + 70 * u;
      const bh = 180 * u;
      ctx.strokeStyle = RED;
      ctx.lineWidth = 9 * u;
      ctx.shadowColor = RED;
      ctx.shadowBlur = 40 * u;
      roundRect(ctx, -bw / 2, -bh / 2, bw, bh, 14 * u);
      ctx.stroke();
      ctx.fillStyle = "rgba(255,45,45,0.14)";
      ctx.fill();
      ctx.shadowBlur = 26 * u;
      ctx.fillStyle = RED;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(text, 2 * u, 8 * u);
      ctx.restore();
    }

    if (r.cue && age < CUE_MS) {
      const [label, body] = r.cue.includes(":") ? [r.cue.split(":")[0], r.cue.slice(r.cue.indexOf(":") + 1)] : ["Coach's standard", r.cue];
      const inP = ease(clamp01((age - 120) / 420));
      const outP = ease(clamp01((age - (CUE_MS - 380)) / 380));
      const x0 = 56 * u;
      const y0 = H - bar - 64 * u - 152 * u - 190 * u;
      const w = W - 112 * u;
      const h = 150 * u;
      ctx.save();
      ctx.globalAlpha = inP * (1 - outP);
      ctx.translate(lerp(-80 * u, 0, inP) + outP * -60 * u, 0);
      roundRect(ctx, x0, y0, w, h, 14 * u);
      ctx.fillStyle = "rgba(12,12,13,0.86)";
      ctx.fill();
      ctx.fillStyle = RED;
      ctx.fillRect(x0, y0, 10 * u, h);
      ctx.textBaseline = "top";
      ctx.font = `700 ${22 * u}px ${this.o.fonts.ui}`;
      ctx.letterSpacing = `${4 * u}px`;
      ctx.fillStyle = RED;
      ctx.fillText(label.trim().toUpperCase(), x0 + 40 * u, y0 + 26 * u);
      ctx.letterSpacing = `${0.5 * u}px`;
      ctx.font = `700 ${56 * u}px ${this.o.fonts.cond}`;
      ctx.fillStyle = CHALK;
      let line = body.trim().toUpperCase();
      while (ctx.measureText(line).width > w - 70 * u && line.length > 4) line = line.slice(0, -1);
      ctx.fillText(line === body.trim().toUpperCase() ? `${line}.` : `${line}…`, x0 + 40 * u, y0 + 62 * u);
      ctx.restore();
    }
  }

  // Cheap blur that works everywhere (no ctx.filter): downscale twice, upscale, then dim.
  private freezeFrame() {
    const small = document.createElement("canvas");
    small.width = Math.round(this.W / 18);
    small.height = Math.round(this.H / 18);
    const sctx = small.getContext("2d")!;
    const r = this.coverRect();
    const mid = document.createElement("canvas");
    mid.width = Math.round(this.W / 6);
    mid.height = Math.round(this.H / 6);
    const mctx = mid.getContext("2d")!;
    mctx.drawImage(this.video, r.x / 6, r.y / 6, r.w / 6, r.h / 6);
    sctx.imageSmoothingQuality = "high";
    sctx.drawImage(mid, 0, 0, small.width, small.height);
    const out = document.createElement("canvas");
    out.width = this.W;
    out.height = this.H;
    const octx = out.getContext("2d")!;
    octx.imageSmoothingQuality = "high";
    octx.drawImage(small, 0, 0, this.W, this.H);
    octx.fillStyle = "rgba(6,6,7,0.62)";
    octx.fillRect(0, 0, this.W, this.H);
    return out;
  }

  private drawEndCard(now: number, bar: number) {
    const { ctx, W, H } = this;
    const k = now - this.endStart;
    const coach = this.o.mode === "coach";
    // Layout in a 1080x1920 column, scaled to fit (landscape gets a centred column).
    const s = Math.min(W / 1080, H / 1920);
    const ox = (W - 1080 * s) / 2;
    const oy = (H - 1920 * s) / 2 + bar * 0.5;
    ctx.save();
    ctx.translate(ox, oy);
    ctx.scale(s, s);
    const fade = (start: number, dur = 420) => ease(clamp01((k - start) / dur));
    const rise = (start: number) => (1 - fade(start)) * 28;
    const reps = this.clip.reps;
    const color = scoreColor(this.clip.setScore, false, this.accent);

    // header
    ctx.textAlign = "center";
    ctx.textBaseline = "alphabetic";
    ctx.globalAlpha = fade(0);
    ctx.font = `700 26px ${this.o.fonts.ui}`;
    ctx.letterSpacing = "8px";
    ctx.fillStyle = this.accent;
    ctx.fillText("SET COMPLETE", 540, 190 + rise(0));
    ctx.letterSpacing = "1px";
    ctx.font = `400 96px ${this.o.fonts.display}`;
    ctx.fillStyle = CHALK;
    ctx.fillText(`${this.clip.exercise.toUpperCase()} · ${this.clip.setLabel.toUpperCase()}`, 540, 290 + rise(60));

    // big score count-up
    const cp = ease(clamp01((k - 300) / 1300));
    const val = Math.round(this.clip.setScore * cp);
    if (cp >= 1 && !this.chimed) {
      this.chimed = true;
      this.o.sfx.chime();
    }
    ctx.globalAlpha = fade(200);
    ctx.font = `400 400px ${this.o.fonts.display}`;
    ctx.letterSpacing = "0px";
    ctx.fillStyle = color;
    ctx.shadowColor = withAlpha(color, 0.55);
    ctx.shadowBlur = 60;
    ctx.fillText(String(val), 540, 670);
    ctx.shadowBlur = 0;
    ctx.font = `600 24px ${this.o.fonts.ui}`;
    ctx.letterSpacing = "8px";
    ctx.fillStyle = withAlpha(CHALK, 0.6);
    ctx.fillText(`SET SCORE / 100 · ${this.o.clientName.toUpperCase()}`, 540, 730);

    // per-rep bars
    const cx0 = 150;
    const cw = 780;
    const top = 800;
    const ch = 240;
    const n = reps.length;
    const bw = Math.min(110, (cw - (n - 1) * 22) / n);
    const totalW = n * bw + (n - 1) * 22;
    ctx.globalAlpha = fade(500);
    ctx.strokeStyle = "rgba(255,255,255,0.1)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(cx0, top + ch);
    ctx.lineTo(cx0 + cw, top + ch);
    ctx.stroke();
    reps.forEach((r, i) => {
      const bp = backOut(clamp01((k - 650 - i * 90) / 520));
      const hgt = Math.max(8, ((Math.max(40, r.score) - 40) / 60) * ch) * bp;
      const bx = 540 - totalW / 2 + i * (bw + 22);
      const c = scoreColor(r.score, Boolean(r.flag), this.accent);
      ctx.globalAlpha = 1;
      roundRect(ctx, bx, top + ch - hgt, bw, hgt, 8);
      ctx.fillStyle = c;
      if (r.flag) {
        ctx.shadowColor = c;
        ctx.shadowBlur = 24;
      }
      ctx.fill();
      ctx.shadowBlur = 0;
      ctx.globalAlpha = clamp01(bp);
      ctx.font = `700 34px ${this.o.fonts.cond}`;
      ctx.letterSpacing = "0px";
      ctx.fillStyle = CHALK;
      ctx.fillText(String(r.score), bx + bw / 2, top + ch - hgt - 14);
      ctx.font = `600 18px ${this.o.fonts.ui}`;
      ctx.letterSpacing = "3px";
      ctx.fillStyle = r.flag ? RED : withAlpha(CHALK, 0.5);
      ctx.fillText(r.flag ? "FLAG" : `R${i + 1}`, bx + bw / 2, top + ch + 36);
    });

    // insight (coach only)
    let y = 1150;
    if (coach && this.clip.insight) {
      ctx.globalAlpha = fade(1500);
      ctx.textAlign = "left";
      ctx.fillStyle = this.accent;
      ctx.fillRect(150, y - 6 + rise(1500), 6, 150);
      ctx.font = `700 22px ${this.o.fonts.ui}`;
      ctx.letterSpacing = "6px";
      ctx.fillText("COACH INSIGHT", 186, y + 20 + rise(1500));
      ctx.font = `500 40px ${this.o.fonts.ui}`;
      ctx.letterSpacing = "0px";
      ctx.fillStyle = CHALK;
      const lines = this.wrap(this.clip.insight, 720);
      lines.forEach((ln, i) => ctx.fillText(ln, 186, y + 76 + i * 52 + rise(1500)));
      y += 120 + lines.length * 52;
    }

    // muscle chips
    ctx.textAlign = "left";
    ctx.font = `700 24px ${this.o.fonts.ui}`;
    ctx.letterSpacing = "4px";
    const chips = this.clip.muscles.map((m) => m.replace(/_/g, " ").toUpperCase());
    const widths = chips.map((c) => ctx.measureText(c).width + 52);
    const chipsW = widths.reduce((a, b) => a + b, 0) + (chips.length - 1) * 14;
    let x = 540 - chipsW / 2;
    chips.forEach((c, i) => {
      const a = fade(coach ? 1800 + i * 80 : 1500 + i * 80);
      ctx.globalAlpha = a;
      roundRect(ctx, x, y + (1 - a) * 18, widths[i], 58, 29);
      ctx.strokeStyle = withAlpha(this.accent, 0.7);
      ctx.lineWidth = 2;
      ctx.stroke();
      ctx.fillStyle = withAlpha(this.accent, 0.08);
      ctx.fill();
      ctx.fillStyle = CHALK;
      ctx.textBaseline = "middle";
      ctx.fillText(c, x + 26, y + 31 + (1 - a) * 18);
      x += widths[i] + 14;
    });
    ctx.restore();
  }

  private wrap(text: string, max: number) {
    const words = text.split(/\s+/);
    const lines: string[] = [];
    let cur = "";
    for (const w of words) {
      const next = cur ? `${cur} ${w}` : w;
      if (this.ctx.measureText(next).width > max && cur) {
        lines.push(cur);
        cur = w;
      } else cur = next;
    }
    if (cur) lines.push(cur);
    return lines;
  }
}
