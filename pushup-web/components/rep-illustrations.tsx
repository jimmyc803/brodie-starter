import { CheckIcon, XIcon } from "@/components/ui/icons";

type Pt = readonly [number, number];
type Pose = { head: Pt; shoulder: Pt; elbow: Pt; hand: Pt; hip: Pt; knee: Pt; ankle: Pt };

const INK = "#16120e";
const SKIN = "#f1e6d2";
const GOOD = "#2346d8";
const BAD = "#ff3d97";
const GROUND = 86;
type Part = "hip" | "knee" | "arm";

const path = (...pts: Pt[]) => "M" + pts.map(([x, y]) => `${x} ${y}`).join(" L");

/** A chunky limb in Brodie's style: thick ink outline around a skin (or fault-pink) core. */
function Limb({ pts, w, fill }: { pts: Pt[]; w: number; fill: string }) {
  const d = path(...pts);
  const cap = { strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <>
      <path d={d} stroke={INK} strokeWidth={w + 5} {...cap} />
      <path d={d} stroke={fill} strokeWidth={w} {...cap} />
    </>
  );
}

/**
 * Brodie, side-on, doing a push-up: round head with his tuft, black BRODIE tank, cream limbs.
 * `fault` paints the offending part pink so the eye goes straight to it. He grins on good reps
 * and grimaces (with sweat) on bad ones.
 */
function Brodie({ pose, fault, guide, ok }: { pose: Pose; fault?: Part; guide?: number; ok: boolean }) {
  const skin = (part: Part) => (fault === part ? BAD : SKIN);
  const [hx, hy] = pose.head;
  const [sx, sy] = pose.shoulder;
  const [px, py] = pose.hip;
  const angle = (Math.atan2(py - sy, px - sx) * 180) / Math.PI;
  const mid: Pt = [sx + (px - sx) * 0.5, sy + (py - sy) * 0.5];
  return (
    <>
      <line x1="6" y1={GROUND + 3} x2="194" y2={GROUND + 3} stroke="rgb(22 18 14 / 0.3)" strokeWidth="2" />
      {/* legs (shorts-free, like the mascot) */}
      <Limb pts={[pose.hip, pose.knee, pose.ankle]} w={7} fill={skin("knee")} />
      {/* arm sits behind the tank so a bent elbow tucks under it */}
      <Limb pts={[pose.shoulder, pose.elbow, pose.hand]} w={8} fill={skin("arm")} />
      {/* torso: the black tank, pink when the hips are the fault */}
      <path d={path(pose.shoulder, pose.hip)} stroke={INK} strokeWidth={19} strokeLinecap="round" fill="none" />
      <path d={path(pose.shoulder, pose.hip)} stroke={fault === "hip" ? BAD : INK} strokeWidth={14} strokeLinecap="round" fill="none" />
      <g transform={`translate(${mid[0]} ${mid[1]}) rotate(${angle})`}>
        <text y="2.6" textAnchor="middle" fontSize="7.5" fontWeight="800" letterSpacing="0.6" fill={fault === "hip" ? INK : SKIN}
          style={{ fontFamily: "var(--font-archivo), sans-serif" }}>BRODIE</text>
      </g>
      {/* the 90° depth line, over the body so it reads against the tank */}
      {guide != null ? (
        <line x1="4" y1={guide} x2="128" y2={guide} stroke={GOOD} strokeWidth="2" strokeDasharray="5 4" />
      ) : null}
      {/* head: tuft, brow, eye, mouth; faces left */}
      <path d={`M${hx + 1} ${hy - 12} q 3 -7 8 -6 q -3 2 -2 5`} fill={SKIN} stroke={INK} strokeWidth="2" strokeLinejoin="round" />
      <circle cx={hx} cy={hy} r="12" fill={SKIN} stroke={INK} strokeWidth="2.5" />
      <path d={ok ? `M${hx - 9} ${hy - 6} L${hx - 3} ${hy - 4}` : `M${hx - 9} ${hy - 4} L${hx - 3} ${hy - 7}`}
        stroke={INK} strokeWidth="2.2" strokeLinecap="round" />
      <circle cx={hx - 6} cy={hy - 1} r="1.7" fill={INK} />
      {ok ? (
        <path d={`M${hx - 10} ${hy + 4} Q ${hx - 5} ${hy + 10} ${hx} ${hy + 5} Z`} fill="#fff" stroke={INK} strokeWidth="1.8" strokeLinejoin="round" />
      ) : (
        <path d={`M${hx - 10} ${hy + 7} Q ${hx - 6} ${hy + 3} ${hx - 1} ${hy + 6}`} fill="none" stroke={INK} strokeWidth="2" strokeLinecap="round" />
      )}
      {ok ? null : (
        <g fill={GOOD} stroke={INK} strokeWidth="1">
          <path d={`M${hx - 15} ${hy - 15} q 3 4 0 6 q -3 -2 0 -6 Z`} />
          <path d={`M${hx - 21} ${hy - 7} q 2.5 3.5 0 5 q -2.5 -1.5 0 -5 Z`} />
        </g>
      )}
    </>
  );
}

const REPS: { title: string; detail: string; says: string; ok: boolean; pose: Pose; fault?: Part; guide?: number }[] = [
  {
    title: "Chest down",
    says: "Deep. Love it.",
    detail: "Elbows at 90° or lower, body in one straight line.",
    ok: true,
    guide: 66,
    pose: { head: [38, 61], shoulder: [54, 66], elbow: [74, 62], hand: [58, GROUND], hip: [115, 75], knee: [146, 79], ankle: [180, 84] },
  },
  {
    title: "Full lockout",
    says: "Lock it out, bro.",
    detail: "Arms straight at the top before the next rep.",
    ok: true,
    pose: { head: [40, 36], shoulder: [56, 42], elbow: [56, 64], hand: [56, GROUND], hip: [116, 63], knee: [147, 73], ankle: [180, 84] },
  },
  {
    title: "Knees down",
    says: "Knees up, bro.",
    detail: "Knees stay off the floor the entire rep.",
    ok: false,
    fault: "knee",
    pose: { head: [40, 42], shoulder: [56, 48], elbow: [56, 67], hand: [56, GROUND], hip: [108, 68], knee: [134, GROUND - 2], ankle: [166, 70] },
  },
  {
    title: "Hips sagging",
    says: "Brace that core.",
    detail: "A dipping middle fails the straight-line check.",
    ok: false,
    fault: "hip",
    pose: { head: [40, 38], shoulder: [56, 44], elbow: [56, 65], hand: [56, GROUND], hip: [114, 79], knee: [147, 80], ankle: [180, 84] },
  },
  {
    title: "Hips piked",
    says: "Butt down, bro.",
    detail: "Butt in the air shortens the rep. No count.",
    ok: false,
    fault: "hip",
    pose: { head: [46, 52], shoulder: [60, 52], elbow: [58, 69], hand: [56, GROUND], hip: [112, 26], knee: [146, 55], ankle: [180, 84] },
  },
  {
    title: "Half rep",
    says: "That's half, bro.",
    detail: "Chest stays high above the 90° line.",
    ok: false,
    fault: "arm",
    guide: 66,
    pose: { head: [40, 47], shoulder: [56, 52], elbow: [66, 68], hand: [56, GROUND], hip: [116, 68], knee: [147, 76], ankle: [180, 84] },
  },
];

export function RepIllustrations() {
  return (
    <ul className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-3">
      {REPS.map((r) => (
        <li key={r.title} className="card overflow-hidden">
          <figure>
            <div className={`relative border-b-2 border-ink px-2 pt-14 pb-1 sm:pt-9 ${r.ok ? "bg-surface" : "bg-surface-2"}`}>
              <span
                className={`absolute top-2 left-2 inline-flex items-center gap-1 border-2 border-ink px-1.5 py-0.5 font-mono text-[0.6875rem] font-bold uppercase tracking-wider ${r.ok ? "bg-blue text-canvas" : "bg-pink text-ink"}`}
              >
                {r.ok ? <CheckIcon className="size-3" /> : <XIcon className="size-3" />}
                {r.ok ? "Counts" : "No rep"}
              </span>
              <span
                aria-hidden
                className={`absolute top-9 right-2 max-w-[80%] sm:top-2 sm:max-w-[55%] border-2 border-ink bg-canvas px-1.5 py-0.5 text-right font-display text-[0.6875rem] leading-tight whitespace-nowrap sm:whitespace-normal uppercase sm:text-sm ${r.ok ? "rotate-2" : "-rotate-2"}`}
              >
                {r.says}
              </span>
              <svg viewBox="0 0 200 100" role="img" aria-label={`Brodie demonstrating: ${r.title}. ${r.ok ? "Counts" : "Does not count"}.`} className="w-full">
                <Brodie pose={r.pose} fault={r.fault} guide={r.guide} ok={r.ok} />
              </svg>
            </div>
            <figcaption className="p-3 sm:p-4">
              <span className="block font-display text-xl font-extrabold uppercase leading-none sm:text-2xl">{r.title}</span>
              <span className="mt-1 block text-sm leading-snug text-ink-2">{r.detail}</span>
            </figcaption>
          </figure>
        </li>
      ))}
    </ul>
  );
}
