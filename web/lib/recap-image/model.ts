// Text and numbers for the recap image (GET /api/recap-image/[token]), derived from the session view. Pure, so the
// wording is unit-tested without rendering a PNG. Muscle colors come from muscle_scores as stored (never recomputed).
import { neonFills, type Fills } from "@/lib/body/neon";
import { allMuscles, MUSCLES, type Color, type SessionView } from "@/lib/contract";
import { sessionRank, type Rank } from "@/lib/ranks";
import { sessionStats } from "@/lib/recap";

export const LEGEND: { color: Color; label: string }[] = [
  { color: "green", label: "Solid" },
  { color: "yellow", label: "Room to improve" },
  { color: "red", label: "Needs work" },
  { color: "gray", label: "Not trained this session" },
];

export const FOOTER = "Estimated coverage · not a measure of muscle activation";
export const ALL_SOLID = "Everything solid today";
export const NO_REPS = "Call ended before the first rep";

const possessive = (name: string) => (/s$/i.test(name) ? `${name}'` : `${name}'s`);

export type RecapCard = {
  kicker: string;
  title: string;
  subtitle: string;
  rank: Rank; // today's rank (Novice when no reps were counted)
  fills: Fills; // the neon heat map fills, same as the web page
  stats: { value: string; label: string }[];
  focus: string[]; // up to 3 muscle labels, red first then yellow, lowest score first
  focusKind: "focus" | "solid" | "empty"; // empty = no reps counted, so nothing to praise or fix
  focusLine: string;
  footer: string;
};

export function recapCard(view: SessionView): RecapCard {
  const s = sessionStats(view);
  const muscles = allMuscles(view);

  const rank = (c: Color) => (c === "red" ? 0 : 1);
  const focus = muscles
    .filter((m) => m.color === "red" || m.color === "yellow")
    .sort((a, b) => rank(a.color) - rank(b.color) || a.score - b.score)
    .slice(0, 3)
    .map((m) => MUSCLES[m.muscle].label);

  const name = view.client.name.trim() || "Client";
  const subtitle = [view.day?.title ?? "Workout", `Coach ${view.coach.name.trim() || "Coach"}`].join(" · ");
  const clean = s.cleanRate === null ? "–" : `${Math.round(s.cleanRate * 100)}%`;

  return {
    kicker: "BRODIE FOR COACHES",
    title: `${possessive(name)} workout`,
    subtitle,
    rank: sessionRank(view).rank,
    fills: neonFills(muscles),
    stats: [
      { value: `${s.completed}/${s.planned}`, label: "reps counted" },
      { value: `${s.setsDone}/${s.setsPlanned}`, label: "sets" },
      { value: clean, label: "clean reps" },
    ],
    focus,
    focusKind: s.completed === 0 ? "empty" : focus.length ? "focus" : "solid",
    focusLine: s.completed === 0 ? NO_REPS : focus.length ? focus.join(" · ") : ALL_SOLID,
    footer: FOOTER,
  };
}
