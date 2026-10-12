import { CheckIcon, XIcon } from "@/components/ui/icons";

type Pt = readonly [number, number];
type Pose = { head: Pt; shoulder: Pt; elbow: Pt; hand: Pt; hip: Pt; knee: Pt; ankle: Pt };

const INK = "#f6f6f3";
const GOOD = "#d4ff3a";
const BAD = "#ff6b5e";
const GROUND = 86;

const path = (...pts: Pt[]) => "M" + pts.map(([x, y]) => `${x} ${y}`).join(" L");

/** A side-on push-up figure. `fault` paints the offending segment so the eye goes straight to it. */
function Figure({ pose, fault, guide }: { pose: Pose; fault?: "hip" | "knee" | "arm"; guide?: number }) {
  const limb = { strokeWidth: 6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  const color = (part: "hip" | "knee" | "arm") => (fault === part ? BAD : INK);
  return (
    <>
      <line x1="6" y1={GROUND} x2="194" y2={GROUND} stroke="rgb(255 255 255 / 0.18)" strokeWidth="2" />
      {guide != null ? (
        <line x1="20" y1={guide} x2="95" y2={guide} stroke={GOOD} strokeWidth="1.5" strokeDasharray="4 4" opacity="0.8" />
      ) : null}
      <path d={path(pose.shoulder, pose.hip)} stroke={color("hip")} {...limb} />
      <path d={path(pose.hip, pose.knee, pose.ankle)} stroke={color("knee")} {...limb} />
      <path d={path(pose.shoulder, pose.elbow, pose.hand)} stroke={color("arm")} {...limb} strokeWidth={5} />
      <circle cx={pose.head[0]} cy={pose.head[1]} r="8" fill={INK} />
    </>
  );
}

const REPS: { title: string; detail: string; ok: boolean; pose: Pose; fault?: "hip" | "knee" | "arm"; guide?: number }[] = [
  {
    title: "Chest down",
    detail: "Elbows at 90° or lower, body in one straight line.",
    ok: true,
    guide: 66,
    pose: { head: [38, 61], shoulder: [54, 66], elbow: [74, 62], hand: [58, GROUND], hip: [115, 75], knee: [146, 79], ankle: [180, 84] },
  },
  {
    title: "Full lockout",
    detail: "Arms straight at the top before the next rep.",
    ok: true,
    pose: { head: [40, 36], shoulder: [56, 42], elbow: [56, 64], hand: [56, GROUND], hip: [116, 63], knee: [147, 73], ankle: [180, 84] },
  },
  {
    title: "Knees down",
    detail: "Knees stay off the floor the entire rep.",
    ok: false,
    fault: "knee",
    pose: { head: [40, 42], shoulder: [56, 48], elbow: [56, 67], hand: [56, GROUND], hip: [108, 68], knee: [134, GROUND - 2], ankle: [166, 70] },
  },
  {
    title: "Hips sagging",
    detail: "A dipping middle fails the straight-line check.",
    ok: false,
    fault: "hip",
    pose: { head: [40, 38], shoulder: [56, 44], elbow: [56, 65], hand: [56, GROUND], hip: [114, 79], knee: [147, 80], ankle: [180, 84] },
  },
  {
    title: "Hips piked",
    detail: "Butt in the air shortens the rep. No count.",
    ok: false,
    fault: "hip",
    pose: { head: [46, 52], shoulder: [60, 52], elbow: [58, 69], hand: [56, GROUND], hip: [112, 26], knee: [146, 55], ankle: [180, 84] },
  },
  {
    title: "Half rep",
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
        <li key={r.title} className={`card overflow-hidden ${r.ok ? "border-accent/40" : ""}`}>
          <figure>
            <div className="relative bg-surface-2/60 px-2 pt-6 pb-1">
              <span
                className={`absolute top-2 left-2 inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[0.6875rem] font-extrabold uppercase tracking-wider ${r.ok ? "bg-accent text-on-accent" : "bg-bad/15 text-bad"}`}
              >
                {r.ok ? <CheckIcon className="size-3" /> : <XIcon className="size-3" />}
                {r.ok ? "Counts" : "No rep"}
              </span>
              <svg viewBox="0 0 200 100" role="img" aria-label={`${r.ok ? "Counts" : "Does not count"}: ${r.title}`} className="w-full">
                <Figure pose={r.pose} fault={r.fault} guide={r.guide} />
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
