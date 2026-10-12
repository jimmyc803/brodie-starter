// Quality rules shared by the client recap and the coach dashboard (web/STYLE.md "Rules").
import cues from "@/lib/generated/fault_cues.json";
import { faultPrefix, faultyReps, setReached, topFaults, type SessionView, type SetView } from "@/lib/contract";

export type Quality = "good" | "warn" | "bad" | "none" | "skipped";

const CUE_PREFIXES = new Set(Object.keys(cues as Record<string, string>).map((k) => k.split(" - ")[0]));

// Brodie only judges form for exercises it has fault cues for; the rest are camera-counted reps only.
export function formChecked(exerciseKey: string): boolean {
  const prefix = faultPrefix(exerciseKey);
  return Boolean(prefix && CUE_PREFIXES.has(prefix));
}

export function setQuality(set: SetView, exerciseKey: string): Quality {
  if (!setReached(set)) return "skipped";
  if (!formChecked(exerciseKey)) return "none";
  const done = set.completed_reps;
  const clean = done ? Math.max(0, done - faultyReps(set)) / done : 0;
  if (clean < 0.5) return "bad";
  if (clean < 0.8 || done < set.planned_reps) return "warn";
  return "good";
}

export function setSummary(set: SetView, exerciseKey: string): string {
  const head = `Set ${set.set_number}`;
  if (!setReached(set)) return `${head} · not reached`;
  const reps = `${head} · ${set.completed_reps} of ${set.planned_reps} reps`;
  if (!formChecked(exerciseKey)) return `${reps} · form not checked`;
  const flagged = faultyReps(set);
  if (!flagged) return `${reps} · clean`;
  const [cue] = topFaults(set.reps, 1);
  return `${reps} · ${flagged} flagged${cue ? `: ${cue[0]}` : ""}`;
}

// The heat map in one line: how many muscles were solid / okay / need work.
export function muscleBalance(view: SessionView) {
  const n = (c: string) => view.muscles.filter((m) => m.color === c).length;
  const good = n("green"), warn = n("yellow"), bad = n("red");
  const parts = [good && `${good} solid`, warn && `${warn} okay`, bad && `${bad} work on`].filter(Boolean);
  return { good, warn, bad, caption: parts.length ? parts.join(" · ") : "No muscles trained" };
}
