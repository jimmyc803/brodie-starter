# UI Revamp Phase 1 (Clean · Light + trainer landing page) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the whole web app to the approved "Clean · Light" system with one written style guide, make colored numbers self-explanatory, and turn `/` into a trainer landing page with an early-access form.

**Architecture:** Semantic color/shape tokens are defined once in `web/app/globals.css` (Tailwind v4 `@theme`) and documented in `web/STYLE.md`; components switch from raw `zinc-*`/hex classes to those tokens. Set/muscle quality rules move into one pure module (`web/lib/quality.ts`) shared by recap and coach views. Dark "stage" components (heat map, video players) keep their internal styling and sit on a `stage` panel. Early access = a new Supabase table + a validated server action.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind CSS v4, Geist font (already loaded via `next/font`), Supabase (service-role server client), Vitest (`npm test`), Playwright-core screenshots (scratchpad script).

**Spec:** `docs/superpowers/specs/2026-10-11-ui-revamp-design.md`

## Global Constraints

- Work in worktree `~/Desktop/Projects/bm-ui` on branch `jimmy-ui-revamp`; never edit `~/Desktop/Projects/brodie-starter` (another session uses it). Rebase on `origin/main` before the PR.
- Public repo: never commit `.env*`, keys, `data/`, `models/`. Before every commit run `git diff --cached --name-only` and abort on any of those.
- One font: Geist (`font-sans`). No condensed/expanded widths, no uppercase letter-spaced labels, no monospace labels.
- No purple. Brand color `#FF5A1F` only on the logo mark and the single primary action per screen.
- Green/amber/red only when they mean a quality; grey = not measured / not reached. Bicep curls (and any exercise with no form cues) are never green.
- Every colored number has a word next to it.
- No gradients or glows outside the heat map; cards radius 14px (`rounded-[14px]`), buttons/inputs 10px (`rounded-[10px]`), chips 6px (`rounded-md`).
- Heat map drawing, rep-review player, clip player and `/api/recap-image` rendering logic are not changed.
- Don't change data loading, the session contract or existing test expectations' text ("Every set hit its reps", "Not reached", "No reps counted this session", "Session incomplete").

## Review Focus

- Coach with 0 clients, client with 0 sessions, session with 0 reps: empty states must render in the light theme with readable text (Task 5 test).
- 50+ clients, long names, and ↑/↓ at the first/last row: list must not overflow and the selection must clamp, not wrap or crash (Task 5 `moveSelection` tests).
- Sets not reached and form-unchecked exercises (bicep curls, pull-ups): grey chip and honest tooltip, never green (Task 2 tests).
- Early access: same email in different case, bot-filled honeypot, missing Supabase env: dedupe, silent accept, friendly error — never a crash or a leaked error (Task 7 tests).
- Phone width 390px: recap and coach dashboard must not scroll horizontally (Task 9 screenshot check).

---

## File Structure

- `web/app/globals.css` — add Clean · Light tokens to `@theme` + `:root`; body defaults.
- `web/STYLE.md` — the style guide (tokens, type scale, shapes, rules, component recipes).
- `web/lib/quality.ts` — pure: `formChecked`, `setQuality`, `setSummary`, `muscleBalance`.
- `web/components/ui-kit/set-chip.tsx` — one set as a `9/10` chip with tooltip.
- `web/components/ui-kit/muscle-balance.tsx` — 3-segment bar + one caption line.
- `web/components/ui-kit/brand.tsx` — logo mark + wordmark.
- `web/components/site-header.tsx` — light header using `Brand`.
- `web/components/recap/*` — recap restyle (view, exercise card, rank badge).
- `web/components/coach/*` — dashboard, client list (table + keyboard), session detail.
- `web/lib/client-nav.ts` — pure keyboard selection helper.
- `web/app/c/[token]/program/*` — programs restyle.
- `db/migrations/20261011_early_access.sql`, `web/lib/early-access.ts`, `web/app/early-access-action.ts`, `web/components/landing/early-access-form.tsx` — early access.
- `web/app/page.tsx` — landing page.
- Tests: `web/tests/style-tokens.test.ts`, `web/tests/quality.test.ts`, `web/tests/client-nav.test.ts`, `web/tests/early-access.test.ts`, `web/tests/no-raw-palette.test.ts`.

---

### Task 1: Design tokens + STYLE.md

**Files:**
- Modify: `web/app/globals.css` (add to the `@theme inline` block and `:root`)
- Create: `web/STYLE.md`
- Test: `web/tests/style-tokens.test.ts`

**Interfaces:**
- Produces Tailwind utilities used by every later task: `bg-canvas bg-surface bg-sunken bg-stage text-ink text-ink-2 text-ink-3 border-line border-line-strong bg-brand text-on-brand text-good text-warn text-bad text-none bg-good-soft bg-warn-soft bg-bad-soft bg-none-soft` (and the same names with `border-`/`bg-`/`text-`/`fill-` prefixes).

- [ ] **Step 1: Write the failing test** — `web/tests/style-tokens.test.ts`

```ts
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.join(import.meta.dirname, "../app/globals.css"), "utf8");
const TOKENS: Record<string, string> = {
  canvas: "#f3f1ec", surface: "#ffffff", sunken: "#ece9e3", stage: "#0b0b0b",
  ink: "#141414", "ink-2": "#55524c", "ink-3": "#8a867f",
  line: "#14141414", "line-strong": "#14141426",
  brand: "#ff5a1f", "on-brand": "#ffffff",
  good: "#15803d", warn: "#a16207", bad: "#dc2626", none: "#8a867f",
  "good-soft": "#15803d14", "warn-soft": "#ca8a041a", "bad-soft": "#dc262612", "none-soft": "#14141410",
};

describe("Clean · Light tokens", () => {
  it.each(Object.entries(TOKENS))("defines --color-%s = %s", (name, value) => {
    expect(css.toLowerCase()).toContain(`--color-${name}: ${value}`);
  });
  it("documents every token in STYLE.md", () => {
    const md = readFileSync(path.join(import.meta.dirname, "../STYLE.md"), "utf8");
    for (const name of Object.keys(TOKENS)) expect(md).toContain(`\`${name}\``);
  });
});
```

- [ ] **Step 2: Run it, expect FAIL**

Run: `cd ~/Desktop/Projects/bm-ui/web && npx vitest run tests/style-tokens.test.ts`
Expected: FAIL (`--color-canvas` missing, STYLE.md missing).

- [ ] **Step 3: Add the tokens** — in `web/app/globals.css`, append inside the existing `@theme inline { ... }` block (before its closing `}`):

```css
  /* Clean · Light (web/STYLE.md). Components use these names, never raw zinc-* or hex. */
  --color-canvas: #f3f1ec;
  --color-surface: #ffffff;
  --color-sunken: #ece9e3;
  --color-stage: #0b0b0b;
  --color-ink: #141414;
  --color-ink-2: #55524c;
  --color-ink-3: #8a867f;
  --color-line: #14141414;
  --color-line-strong: #14141426;
  --color-brand: #ff5a1f;
  --color-on-brand: #ffffff;
  --color-good: #15803d;
  --color-warn: #a16207;
  --color-bad: #dc2626;
  --color-none: #8a867f;
  --color-good-soft: #15803d14;
  --color-warn-soft: #ca8a041a;
  --color-bad-soft: #dc262612;
  --color-none-soft: #14141410;
```

and at the end of the file add:

```css
@layer base {
  body {
    background: var(--color-canvas);
    color: var(--color-ink);
    font-family: var(--font-geist-sans), system-ui, sans-serif;
    letter-spacing: -0.005em;
  }
}
```

- [ ] **Step 4: Write `web/STYLE.md`**

```markdown
# Brodie style guide — Clean · Light

Read this before touching any UI. Components use the tokens below as Tailwind classes (`bg-surface`, `text-ink-3`,
`border-line` …). Never use raw `zinc-*`, `slate-*`, `white/…`, or hex colors in components; add a token here instead.

## Colors
| Token | Value | Use |
|---|---|---|
| `canvas` | #F3F1EC | page background |
| `surface` | #FFFFFF | cards, inputs, selected row |
| `sunken` | #ECE9E3 | sidebar, active tab / nav item |
| `stage` | #0B0B0B | dark panel behind the heat map and videos |
| `ink` | #141414 | primary text, numbers |
| `ink-2` | #55524C | secondary text |
| `ink-3` | #8A867F | labels, hints, units |
| `line` | #141414 @ 8% | hairlines, card borders |
| `line-strong` | #141414 @ 15% | input borders, outline buttons |
| `brand` / `on-brand` | #FF5A1F / #FFFFFF | logo mark and the ONE primary button per screen |
| `good` / `good-soft` | #15803D | quality: solid |
| `warn` / `warn-soft` | #A16207 | quality: okay / short |
| `bad` / `bad-soft` | #DC2626 | quality: work on |
| `none` / `none-soft` | #8A867F | not measured, not reached |

Rules: quality colors only when they mean quality. Grey means "not measured" — form-unchecked exercises (bicep curls,
pull-ups) are never green. Every colored number gets a word next to it. One brand-orange element per screen.

## Type (Geist only)
| Role | Classes |
|---|---|
| Page title | `text-[34px] font-semibold tracking-[-0.025em] leading-[1.05]` |
| Section title | `text-base font-semibold` |
| Hero number | `text-[76px] font-semibold tracking-[-0.035em] leading-none tabular-nums` |
| Stat number | `text-[28px] font-semibold tracking-[-0.035em] leading-none tabular-nums` (34px on desktop KPIs) |
| Body | `text-sm text-ink` / secondary `text-sm text-ink-2` |
| Label | `text-[12.5px] font-medium text-ink-3` (sentence case — never uppercase or letter-spaced) |

## Shape and space
Cards `rounded-[14px] border border-line bg-surface`; buttons and inputs `rounded-[10px]`; chips `rounded-md`.
4px grid; 8–12px gaps inside cards; 24–40px between sections. No shadows except the phone mockups; no gradients or
glows (the heat map keeps its own).

## Recipes
- Primary button: `rounded-[10px] bg-brand px-4 py-2.5 text-sm font-semibold text-on-brand hover:brightness-95`
- Secondary button: `rounded-[10px] border border-line-strong px-4 py-2.5 text-sm font-semibold text-ink hover:bg-sunken`
- Card: `rounded-[14px] border border-line bg-surface p-4`
- Stat card: card + label on top + stat number.
- Tabs: `rounded-lg px-2.5 py-1 text-xs font-semibold` — active `bg-sunken text-ink`, inactive `text-ink-3 hover:text-ink`.
- Stage panel (heat map, video): `rounded-[18px] bg-stage p-4` — content inside keeps its dark styling.
- Set chip: `components/ui-kit/set-chip.tsx`. Muscle balance: `components/ui-kit/muscle-balance.tsx`.
```

- [ ] **Step 5: Run the test, expect PASS**

Run: `npx vitest run tests/style-tokens.test.ts` → PASS.

- [ ] **Step 6: Commit**

```bash
git add web/app/globals.css web/STYLE.md web/tests/style-tokens.test.ts
git commit -m "web: Clean · Light design tokens + STYLE.md"
```

---

### Task 2: Quality rules + SetChip + MuscleBalance + Brand

**Files:**
- Create: `web/lib/quality.ts`, `web/components/ui-kit/set-chip.tsx`, `web/components/ui-kit/muscle-balance.tsx`, `web/components/ui-kit/brand.tsx`
- Modify: `web/components/site-header.tsx`
- Test: `web/tests/quality.test.ts`

**Interfaces:**
- Consumes: `faultyReps`, `setReached`, `topFaults`, `faultPrefix`, `type SetView`, `type SessionView` from `@/lib/contract`; `web/lib/generated/fault_cues.json`.
- Produces:
  - `type Quality = "good" | "warn" | "bad" | "none" | "skipped"`
  - `formChecked(exerciseKey: string): boolean`
  - `setQuality(set: SetView, exerciseKey: string): Quality`
  - `setSummary(set: SetView, exerciseKey: string): string`
  - `muscleBalance(view: SessionView): { good: number; warn: number; bad: number; caption: string }`
  - `<SetChip set={SetView} exerciseKey={string} />`, `<MuscleBalance view={SessionView} />`, `<Brand />`

- [ ] **Step 1: Write the failing tests** — `web/tests/quality.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { formChecked, muscleBalance, setQuality, setSummary } from "@/lib/quality";
import type { SessionView, SetView } from "@/lib/contract";

const set = (completed: number, planned: number, flagged: string[][] = []): SetView => ({
  set_number: 3, planned_reps: planned, completed_reps: completed,
  reps: Array.from({ length: completed }, (_, i) => ({ rep_number: i + 1, faults: flagged[i] ?? [] })),
});

describe("formChecked", () => {
  it("is true for exercises Brodie has form cues for", () => {
    expect(formChecked("squat")).toBe(true);
    expect(formChecked("pushup")).toBe(true);
  });
  it("is false for bicep curls, pull-ups and unknown keys", () => {
    expect(formChecked("bicep_curl")).toBe(false);
    expect(formChecked("pullup")).toBe(false);
    expect(formChecked("bench_press")).toBe(false);
  });
});

describe("setQuality", () => {
  it("good: all planned reps, clean", () => expect(setQuality(set(10, 10), "squat")).toBe("good"));
  it("warn: short of planned", () => expect(setQuality(set(9, 10), "squat")).toBe("warn"));
  it("warn: some flagged (clean 70%)", () =>
    expect(setQuality(set(10, 10, [["squats - shallow"], ["squats - shallow"], ["squats - shallow"]]), "squat")).toBe("warn"));
  it("bad: under half clean", () =>
    expect(setQuality(set(4, 4, [["a"], ["a"], ["a"]]), "squat")).toBe("bad"));
  it("skipped: set not reached", () => expect(setQuality(set(0, 10), "squat")).toBe("skipped"));
  it("none: form not checked, even when every rep is done", () => expect(setQuality(set(12, 12), "bicep_curl")).toBe("none"));
});

describe("setSummary", () => {
  it("names reps, flags and the top cue", () =>
    expect(setSummary(set(9, 10, [["squats - shallow"], ["squats - shallow"]]), "squat")).toMatch(/^Set 3 · 9 of 10 reps · 2 flagged: /));
  it("says clean when nothing is flagged", () => expect(setSummary(set(10, 10), "squat")).toBe("Set 3 · 10 of 10 reps · clean"));
  it("says form not checked for curls", () => expect(setSummary(set(12, 12), "bicep_curl")).toBe("Set 3 · 12 of 12 reps · form not checked"));
  it("says not reached", () => expect(setSummary(set(0, 10), "squat")).toBe("Set 3 · not reached"));
});

describe("muscleBalance", () => {
  const view = (colors: string[]) =>
    ({ muscles: colors.map((c, i) => ({ muscle: `m${i}`, score: 0, color: c, coverage: "primary" })) }) as unknown as SessionView;
  it("counts colors and writes one caption", () => {
    expect(muscleBalance(view(["green", "green", "yellow", "red", "gray"]))).toEqual({ good: 2, warn: 1, bad: 1, caption: "2 solid · 1 okay · 1 work on" });
  });
  it("drops zero groups from the caption", () => {
    expect(muscleBalance(view(["green"])).caption).toBe("1 solid");
  });
  it("handles a session with no trained muscles", () => {
    expect(muscleBalance(view(["gray"])).caption).toBe("No muscles trained");
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run tests/quality.test.ts` → FAIL (module missing).

- [ ] **Step 3: Implement `web/lib/quality.ts`**

```ts
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

export function muscleBalance(view: SessionView) {
  const n = (c: string) => view.muscles.filter((m) => m.color === c).length;
  const good = n("green"), warn = n("yellow"), bad = n("red");
  const parts = [good && `${good} solid`, warn && `${warn} okay`, bad && `${bad} work on`].filter(Boolean);
  return { good, warn, bad, caption: parts.length ? parts.join(" · ") : "No muscles trained" };
}
```

- [ ] **Step 4: Run, expect PASS** — `npx vitest run tests/quality.test.ts` → PASS.

- [ ] **Step 5: Create the components**

`web/components/ui-kit/set-chip.tsx`:

```tsx
import type { SetView } from "@/lib/contract";
import { setQuality, setSummary, type Quality } from "@/lib/quality";

const TONE: Record<Quality, string> = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  none: "bg-none-soft text-ink-2",
  skipped: "border border-dashed border-line-strong text-ink-3",
};

// One set: "9/10", colored by quality; hover/long-press shows the full sentence.
export function SetChip({ set, exerciseKey }: { set: SetView; exerciseKey: string }) {
  const q = setQuality(set, exerciseKey);
  const summary = setSummary(set, exerciseKey);
  return (
    <span title={summary} aria-label={summary} className={`inline-block min-w-11 rounded-md px-1.5 py-0.5 text-center text-xs font-semibold tabular-nums ${TONE[q]}`}>
      {q === "skipped" ? "–" : `${set.completed_reps}/${set.planned_reps}`}
    </span>
  );
}
```

`web/components/ui-kit/muscle-balance.tsx`:

```tsx
import type { SessionView } from "@/lib/contract";
import { muscleBalance } from "@/lib/quality";

// The heat map in one line: a thin 3-color bar and "6 solid · 3 okay · 2 work on".
export function MuscleBalance({ view }: { view: SessionView }) {
  const { good, warn, bad, caption } = muscleBalance(view);
  const total = good + warn + bad;
  return (
    <div>
      {total ? (
        <div className="flex h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden>
          <span className="bg-good" style={{ width: `${(good / total) * 100}%` }} />
          <span className="bg-warn" style={{ width: `${(warn / total) * 100}%` }} />
          <span className="bg-bad" style={{ width: `${(bad / total) * 100}%` }} />
        </div>
      ) : null}
      <p className="mt-2 text-[12.5px] font-medium text-ink-2">{caption}</p>
    </div>
  );
}
```

`web/components/ui-kit/brand.tsx`:

```tsx
import Link from "next/link";

export function Brand({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 text-base font-bold tracking-[-0.02em] text-ink">
      <span aria-hidden className="size-3.5 rounded-[4px] bg-brand" />
      Brodie
    </Link>
  );
}
```

Replace `web/components/site-header.tsx` with:

```tsx
import { Brand } from "@/components/ui-kit/brand";

// The one header every page shares: the Brodie mark on the left, where you are / actions on the right.
export function SiteHeader({ context, className = "" }: { context?: React.ReactNode; className?: string }) {
  return (
    <header className={`flex items-center justify-between gap-4 border-b border-line pb-4 ${className}`}>
      <Brand />
      {context ? <div className="flex min-w-0 shrink-0 items-center gap-2 text-sm text-ink-2">{context}</div> : null}
    </header>
  );
}

// Section heading used across pages: sentence case, quiet.
export function SectionHeading({ children, sub, as: Tag = "h2" }: { children: React.ReactNode; sub?: React.ReactNode; as?: "h2" | "h3" }) {
  return (
    <div className="mb-3">
      <Tag className="text-base font-semibold text-ink">{children}</Tag>
      {sub ? <p className="mt-0.5 text-sm text-ink-3">{sub}</p> : null}
    </div>
  );
}
```

- [ ] **Step 6: Typecheck + full tests** — `npx tsc --noEmit && npm test` → all pass.

- [ ] **Step 7: Commit**

```bash
git add web/lib/quality.ts web/components/ui-kit web/components/site-header.tsx web/tests/quality.test.ts
git commit -m "web: quality rules (grey for unchecked form), SetChip, MuscleBalance, Brand header"
```

---

### Task 3: Client recap restyle

**Files:**
- Modify: `web/app/r/[token]/page.tsx`, `web/components/recap/recap-view.tsx`, `web/components/recap/exercise-card.tsx`, `web/components/recap/rank-badge.tsx`, `web/components/rep-review/review-launcher.tsx` (button chrome only)
- Test: existing `npm test` + screenshot

**Interfaces:**
- Consumes: tokens (Task 1); `SetChip`, `MuscleBalance`, `SiteHeader` (Task 2); unchanged `Heatmap`, `ReviewLauncher` props.

- [ ] **Step 1: Page shell** — in `web/app/r/[token]/page.tsx` change the `<main>` className to `"flex-1 overflow-x-clip bg-canvas text-ink"`.

- [ ] **Step 2: Replace `RecapView`'s JSX** in `web/components/recap/recap-view.tsx`. Keep the imports, `formatDate` and the computed values; replace `Stat` and the returned tree with:

```tsx
function Stat({ value, suffix, label }: { value: string; suffix?: string; label: string }) {
  return (
    <div className="rounded-[14px] border border-line bg-surface px-3.5 py-3">
      <div className="tabular-nums">
        <span className="text-[28px] font-semibold leading-none tracking-[-0.035em]">{value}</span>
        {suffix ? <span className="text-base font-semibold text-ink-3">{suffix}</span> : null}
      </div>
      <div className="mt-1.5 text-[12.5px] font-medium text-ink-3">{label}</div>
    </div>
  );
}

export function RecapView({ view, clips }: { view: SessionView; clips?: ExerciseClip[] }) {
  const stats = sessionStats(view);
  const date = formatDate(view.session.started_at);
  const subline = [view.day?.title, date].filter(Boolean).join(" · ");
  const clean = stats.cleanRate === null ? null : Math.round(stats.cleanRate * 100);

  return (
    <div className="mx-auto w-full max-w-xl px-4 pb-12 pt-5 sm:px-6 sm:pt-8">
      <SiteHeader context={`Coach ${view.coach.name}`} />

      <div className="mt-7">
        <p className="text-[12.5px] font-medium text-ink-3">{subline}</p>
        <h1 className="mt-1 text-[34px] font-semibold leading-[1.05] tracking-[-0.025em] text-balance">
          {view.client.name}&apos;s workout
        </h1>
      </div>

      <div className="mt-6 flex items-end gap-3">
        <span className="text-[76px] font-semibold leading-none tracking-[-0.035em] tabular-nums">{stats.completed}</span>
        <span className="pb-2 leading-tight">
          <span className="block text-[12.5px] font-medium text-ink-3">of {stats.planned}</span>
          <span className="block text-[15px] font-semibold">reps counted</span>
        </span>
      </div>

      <section aria-label="Session stats" className="mt-4 grid grid-cols-3 gap-2">
        <Stat value={String(stats.setsDone)} suffix={`/${stats.setsPlanned}`} label="sets" />
        <Stat value={clean === null ? "–" : String(clean)} suffix={clean === null ? undefined : "%"} label="clean reps" />
        <Stat value={stats.minutes === null ? "–" : String(stats.minutes)} label="minutes" />
      </section>

      {stats.endedEarly ? (
        <p className="mt-3 text-sm text-ink-2">
          {stats.completed === 0 ? "Call ended before any reps were counted." : "Call ended before the last set."}
        </p>
      ) : null}

      <div className="mt-3">
        <RankBadge r={sessionRank(view)} />
      </div>

      <div className="mt-3">
        <ReviewLauncher mode="client" clientName={view.client.name} muscles={view.muscles.filter((m) => m.coverage !== "none").map((m) => m.muscle)} />
      </div>

      <section className="mt-10">
        <SectionHeading sub="Estimated from the exercises you did">Muscles worked</SectionHeading>
        <MuscleBalance view={view} />
        <div className="mt-3 rounded-[18px] bg-stage p-4 text-zinc-100 sm:p-6">
          <Heatmap details={muscleDetails(view)} order={revealOrder(view)} clips={clips} review={{ mode: "client", clientName: view.client.name }} />
        </div>
      </section>

      <section className="mt-10">
        <SectionHeading sub="Each box is one set · reps done / planned">What you did</SectionHeading>
        <div className="space-y-2.5">
          {view.exercises.map((ex) => (
            <ExerciseCard key={ex.exercise_key} exercise={ex} />
          ))}
        </div>
      </section>

      <footer className="mt-10 space-y-2 border-t border-line pt-6 text-xs leading-relaxed text-ink-3">
        <p>
          Estimated coverage based on the exercises completed — not a measurement of muscle activation. Coaching
          feedback, not medical advice.
        </p>
        <p>Reps counted by camera; a few may be missed.</p>
      </footer>
    </div>
  );
}
```

Add the import: `import { MuscleBalance } from "@/components/ui-kit/muscle-balance";`. (`text-zinc-100` on the stage panel is the one allowed raw class: the heat map inside is a stage component.)

- [ ] **Step 3: Replace `web/components/recap/exercise-card.tsx`** with:

```tsx
import { completedReps, plannedReps, topFaults, type ExerciseView } from "@/lib/contract";
import { formChecked } from "@/lib/quality";
import { SetChip } from "@/components/ui-kit/set-chip";

export function ExerciseCard({ exercise }: { exercise: ExerciseView }) {
  const done = completedReps(exercise);
  const planned = plannedReps(exercise);
  const checked = formChecked(exercise.exercise_key);
  const faults = topFaults(exercise.sets.flatMap((s) => s.reps));

  return (
    <article className="rounded-[14px] border border-line bg-surface px-4 py-3">
      <header className="flex items-baseline justify-between gap-3">
        <h3 className="text-[15px] font-semibold">{exercise.name}</h3>
        <p className="shrink-0 tabular-nums text-sm">
          <span className="font-semibold">{done}</span>
          <span className="text-ink-3">/{planned} reps</span>
        </p>
      </header>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {exercise.sets.map((s) => (
          <SetChip key={s.set_number} set={s} exerciseKey={exercise.exercise_key} />
        ))}
      </div>
      <p className="mt-2 text-[12.5px] text-ink-2">
        {!checked
          ? "Reps counted by camera · form not checked"
          : faults.length
            ? faults.map(([cue, n]) => `${cue} ×${n}`).join(" · ")
            : "No form flags"}
      </p>
    </article>
  );
}
```

- [ ] **Step 4: Restyle `RankBadge`** — in `web/components/recap/rank-badge.tsx` make these exact class swaps (logic unchanged): section `rounded-2xl border border-zinc-800 bg-zinc-900 px-5 py-4` → `rounded-[14px] border border-line bg-surface px-4 py-3.5`; `text-sm text-zinc-400` → `text-[12.5px] font-medium text-ink-3`; `text-xs tabular-nums text-zinc-500` → `text-[12.5px] tabular-nums text-ink-3`; `mt-1 text-2xl font-bold tracking-tight` → `mt-1 text-[19px] font-semibold tracking-[-0.02em]`; `outline-white` → `outline-ink`; `mt-2 text-xs text-zinc-500` → `mt-2 text-xs text-ink-3`.

- [ ] **Step 5: ReviewLauncher chrome** — in `web/components/rep-review/review-launcher.tsx` change only the `<button>` and its two text spans:
  - button: `group flex w-full items-center justify-between gap-3 rounded-[14px] border border-line bg-surface px-4 py-3 text-left transition hover:bg-sunken`
  - title span: `block text-sm font-semibold text-ink`
  - sub span: `block text-xs text-ink-3`
  - round play icon: `grid size-9 shrink-0 place-items-center rounded-full bg-brand text-sm text-on-brand transition group-hover:scale-105`

- [ ] **Step 6: Verify** — `npx tsc --noEmit && npm test` pass; start `npx next dev -p 3141` in `web/`, screenshot `/r/demo` at 390×844 (full page) and compare with the mockup: light page, stage-panel heat map, chips `10/10`, curls grey with "form not checked".

- [ ] **Step 7: Commit** — `git add web/app/r web/components/recap web/components/rep-review/review-launcher.tsx && git commit -m "web: recap in Clean · Light (stat cards, muscle balance, set chips, stage heat map)"`

---

### Task 4: Keyboard selection helper

**Files:**
- Create: `web/lib/client-nav.ts`
- Test: `web/tests/client-nav.test.ts`

**Interfaces:**
- Produces: `moveSelection(ids: string[], current: string | null, key: string): string | null`

- [ ] **Step 1: Failing test** — `web/tests/client-nav.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { moveSelection } from "@/lib/client-nav";

const ids = ["a", "b", "c"];
describe("moveSelection", () => {
  it("moves down and up", () => {
    expect(moveSelection(ids, "a", "ArrowDown")).toBe("b");
    expect(moveSelection(ids, "c", "ArrowUp")).toBe("b");
  });
  it("clamps at both ends", () => {
    expect(moveSelection(ids, "c", "ArrowDown")).toBe("c");
    expect(moveSelection(ids, "a", "ArrowUp")).toBe("a");
  });
  it("starts at the first row when nothing (or a hidden row) is selected", () => {
    expect(moveSelection(ids, null, "ArrowDown")).toBe("a");
    expect(moveSelection(ids, "zzz", "ArrowDown")).toBe("a");
  });
  it("returns null for an empty list and ignores other keys", () => {
    expect(moveSelection([], null, "ArrowDown")).toBeNull();
    expect(moveSelection(ids, "b", "x")).toBe("b");
  });
});
```

- [ ] **Step 2: Run, expect FAIL** — `npx vitest run tests/client-nav.test.ts`.

- [ ] **Step 3: Implement `web/lib/client-nav.ts`**

```ts
// ↑/↓ through the visible client rows, clamped at the ends.
export function moveSelection(ids: string[], current: string | null, key: string): string | null {
  if (!ids.length) return null;
  const i = current === null ? -1 : ids.indexOf(current);
  if (key === "ArrowDown") return i < 0 ? ids[0] : ids[Math.min(ids.length - 1, i + 1)];
  if (key === "ArrowUp") return i < 0 ? ids[0] : ids[Math.max(0, i - 1)];
  return current;
}
```

- [ ] **Step 4: PASS** — rerun the test.

- [ ] **Step 5: Commit** — `git add web/lib/client-nav.ts web/tests/client-nav.test.ts && git commit -m "web: clamped keyboard selection for the client list"`

---

### Task 5: Coach dashboard restyle (table, tabs, keyboard, KPIs)

**Files:**
- Modify: `web/app/c/[token]/page.tsx`, `web/components/coach/dashboard.tsx`, `web/components/coach/client-list.tsx`, `web/components/coach/session-detail.tsx`, `web/lib/coach-status.ts` (add two fields)
- Test: `web/tests/coach-status.test.ts` (extend), existing `web/tests/session-detail.test.ts`

**Interfaces:**
- Consumes: `moveSelection` (Task 4), `SetChip`, `MuscleBalance`, `SiteHeader` (Task 2), tokens.
- Produces: `ClientSummary` gains `reps: string | null` (e.g. `"90/110"`) and `cleanPct: number | null` (0–100) from the latest session.

- [ ] **Step 1: Failing test** — append to `web/tests/coach-status.test.ts`:

```ts
import { summarizeClient } from "@/lib/coach-status";
import { sampleSessionView } from "@/lib/session-view";

describe("summary numbers for the client table", () => {
  it("exposes the latest session's reps and clean %", () => {
    const s = summarizeClient({ id: "x", name: "Ryan", sessions: [sampleSessionView()] }, Date.parse(sampleSessionView().session.started_at));
    expect(s.reps).toMatch(/^\d+\/\d+$/);
    expect(s.cleanPct).toBeGreaterThanOrEqual(0);
    expect(s.cleanPct).toBeLessThanOrEqual(100);
  });
  it("is null with no sessions", () => {
    const s = summarizeClient({ id: "x", name: "New", sessions: [] });
    expect(s.reps).toBeNull();
    expect(s.cleanPct).toBeNull();
  });
});
```

(If `describe`/`expect`/`it` are not yet imported at the top of that file, add `import { describe, expect, it } from "vitest";`.)

- [ ] **Step 2: FAIL** — `npx vitest run tests/coach-status.test.ts`.

- [ ] **Step 3: Implement** — in `web/lib/coach-status.ts` add `reps: string | null; cleanPct: number | null;` to `ClientSummary`, and in `summarizeClient` compute once after `latest`:

```ts
  const latestStats = latest ? sessionStats(latest) : null;
  const reps = latestStats ? `${latestStats.completed}/${latestStats.planned}` : null;
  const cleanPct = latestStats?.cleanRate == null ? null : Math.round(latestStats.cleanRate * 100);
```

then add `reps, cleanPct` to every returned object literal (5 returns).

- [ ] **Step 4: PASS** — rerun; `npm test` all green.

- [ ] **Step 5: Replace `web/components/coach/client-list.tsx`** with a table + tabs + keyboard version:

```tsx
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { ClientStatus, ClientSummary } from "@/lib/coach-status";
import { moveSelection } from "@/lib/client-nav";

const TABS: { key: ClientStatus | "all"; label: string }[] = [
  { key: "review", label: "Needs review" },
  { key: "all", label: "All" },
  { key: "inactive", label: "Inactive" },
];
const DOT: Record<ClientStatus, string> = { review: "bg-bad", on_track: "bg-good", inactive: "bg-none" };

// The coach's roster as a compact table: search ("/" focuses), status tabs, ↑/↓ to move, Enter to open.
export function ClientList({ clients, base, selectedId }: { clients: ClientSummary[]; base: string; selectedId: string | null }) {
  const router = useRouter();
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const reviewCount = clients.filter((c) => c.status === "review").length;
  const [tab, setTab] = useState<ClientStatus | "all">(reviewCount ? "review" : "all");
  const [cursor, setCursor] = useState<string | null>(selectedId);
  const q = query.trim().toLowerCase();
  const shown = clients.filter((c) => (tab === "all" || c.status === tab) && (!q || c.name.toLowerCase().includes(q)));
  const href = (id: string) => `${base}?c=${encodeURIComponent(id)}`;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement;
      if (e.key === "/" && !typing) { e.preventDefault(); search.current?.focus(); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (typing && e.target !== search.current) return;
        e.preventDefault();
        setCursor((c) => moveSelection(shown.map((s) => s.id), c, e.key));
      }
      if (e.key === "Enter" && cursor && shown.some((s) => s.id === cursor)) router.push(href(cursor));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <nav aria-label="Clients" className="rounded-[14px] border border-line bg-sunken/60">
      <div className="p-3">
        <label className="flex items-center justify-between gap-2 rounded-[10px] border border-line-strong bg-surface px-3 py-2">
          <input
            ref={search}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${clients.length} ${clients.length === 1 ? "client" : "clients"}`}
            aria-label="Search clients"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-3 focus:outline-none"
          />
          <kbd className="rounded-[5px] border border-line-strong px-1.5 text-[11px] text-ink-3">/</kbd>
        </label>
        <div className="mt-2 flex gap-1" role="group" aria-label="Filter clients">
          {TABS.map((t) => {
            const n = t.key === "all" ? clients.length : clients.filter((c) => c.status === t.key).length;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                aria-pressed={active}
                onClick={() => setTab(t.key)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors ${active ? "bg-surface text-ink" : "text-ink-3 hover:text-ink"}`}
              >
                {t.label} · {n}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)_56px_44px_10px] gap-2 px-5 pb-1 text-[12px] font-medium text-ink-3">
        <span>Client · last session</span><span className="text-right">Reps</span><span className="text-right">Clean</span><span />
      </div>
      {shown.length === 0 ? <p className="px-5 py-8 text-center text-sm text-ink-3">No clients match.</p> : null}
      <ul className="max-h-[70vh] overflow-y-auto px-2 pb-2">
        {shown.map((c) => {
          const active = c.id === selectedId;
          const focused = c.id === cursor && !active;
          return (
            <li key={c.id}>
              <Link
                href={href(c.id)}
                aria-current={active ? "page" : undefined}
                onFocus={() => setCursor(c.id)}
                className={`grid grid-cols-[minmax(0,1fr)_56px_44px_10px] items-center gap-2 rounded-[10px] px-3 py-2.5 transition-colors ${
                  active ? "bg-surface shadow-[0_0_0_1px_var(--color-line)]" : focused ? "bg-surface/70" : "hover:bg-surface/60"
                } ${c.status === "inactive" && !active ? "opacity-60" : ""}`}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ink">{c.name}</span>
                  <span className="block truncate text-xs text-ink-3">{c.detail}</span>
                </span>
                <span className="text-right text-[13.5px] font-semibold tabular-nums text-ink">{c.reps ?? "–"}</span>
                <span className="text-right text-[13.5px] font-semibold tabular-nums text-ink">{c.cleanPct === null ? "–" : `${c.cleanPct}%`}</span>
                <span className={`size-[7px] rounded-full ${DOT[c.status]}`} aria-label={c.status.replace("_", " ")} />
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="border-t border-line px-5 py-2 text-[12px] text-ink-3">↑ ↓ to move · Enter to open</p>
    </nav>
  );
}
```

- [ ] **Step 6: Restyle `web/components/coach/dashboard.tsx`** (logic unchanged):
  - `STATUS_LABEL` classNames: review `bg-bad-soft text-bad`, on_track `bg-good-soft text-good`, inactive `bg-none-soft text-ink-2`.
  - `SiteHeader context`: replace the Programs link with
    ```tsx
    <>
      <span className="hidden text-ink-3 sm:inline">Coach {view.coach.name}</span>
      <Link className="rounded-[10px] border border-line-strong px-3.5 py-2 text-sm font-semibold text-ink hover:bg-sunken" href={programsHref}>Programs</Link>
      <Link className="rounded-[10px] bg-brand px-3.5 py-2 text-sm font-semibold text-on-brand hover:brightness-95" href={programsHref}>Upload program</Link>
    </>
    ```
  - header: `h1` → `text-[28px] font-semibold tracking-[-0.025em] text-ink` with text `Clients`; the sub line `text-sm text-ink-2`; review count span `text-bad`.
  - empty states: `rounded-[14px] border border-dashed border-line-strong p-8 text-center text-ink-2`.
  - grid: `lg:grid-cols-[minmax(0,340px)_minmax(0,1fr)]`.
  - `ClientHeader` section: `rounded-[14px] border border-line bg-surface p-5 sm:p-6`; avatar `bg-sunken text-ink-2`; `h2` `text-[26px] font-semibold tracking-[-0.025em] text-ink`; status pill `rounded-full px-2.5 py-1 text-xs font-semibold`; each `dl` tile `rounded-[10px] bg-sunken/60 px-4 py-3`, `dt` `text-[12.5px] font-medium text-ink-3`, `dd` text `text-sm font-semibold text-ink`, "Change" link `text-xs text-ink-3 hover:text-ink`; session switcher active `border-ink/30 bg-sunken text-ink`, inactive `border-line text-ink-2 hover:border-line-strong`, inner date `font-semibold`, rest `text-ink-3`.

- [ ] **Step 7: Restyle `web/components/coach/session-detail.tsx`** (text content unchanged so `session-detail.test.ts` still passes):
  - section `scroll-mt-4 rounded-[14px] border border-line bg-surface`; header sub `text-[12.5px] font-medium text-ink-3`; `h2` `text-[26px] font-semibold tracking-[-0.025em] text-ink`; "Open client recap" link `rounded-[10px] border border-line-strong px-4 py-2 text-sm font-semibold text-ink hover:bg-sunken`.
  - Replace the `<dl>` KPI strip with four stat cards in `grid grid-cols-2 gap-2 px-5 sm:grid-cols-4 sm:px-6` where `Figure` becomes `rounded-[14px] border border-line px-4 py-3`, `dt` `text-[12.5px] font-medium text-ink-3`, number `text-[34px] font-semibold leading-none tracking-[-0.035em] text-ink`, sub `text-lg font-semibold text-ink-3`. The fourth card is:
    ```tsx
    <div className="rounded-[14px] border border-line px-4 py-3">
      <dt className="text-[12.5px] font-medium text-ink-3">Muscles</dt>
      <dd className="mt-3"><MuscleBalance view={view} /></dd>
    </div>
    ```
    and delete the now-unused `Dot` component and `colorOf`/`Color` imports if unused.
  - `NeedsALook`: neutral box `rounded-[14px] border border-line bg-canvas px-4 py-3 text-sm text-ink-2`; success box `rounded-[14px] bg-good-soft px-4 py-3 text-sm text-good`; list title `text-sm font-semibold text-ink`, count `text-ink-3`; dot `bg-bad`/`bg-warn` via `className={f.faulty / Math.max(1, f.completed) >= 0.5 ? "bg-bad" : "bg-warn"}` instead of inline style; row text `text-ink-2`, exercise name `font-semibold text-ink`.
  - Heat map block: wrap `<Heatmap …/>` in `<div className="rounded-[18px] bg-stage p-4 text-zinc-100">…</div>`; headings `mb-3 text-[12.5px] font-medium text-ink-3`.
  - `ExerciseTable`: container `overflow-x-auto rounded-[14px] border border-line`; thead `bg-canvas text-left text-[12.5px] text-ink-3`; rows `border-t border-line`; name `font-semibold text-ink`; replace the set `<span>`s with `<SetChip key={s.set_number} set={s} exerciseKey={ex.exercise_key} />` (keep the `Not reached` text in the cues column for unreached exercises); reps `text-ink`, `/planned` `text-ink-3`; cues `text-ink-2`; when `!formChecked(ex.exercise_key)` and reached, cues cell shows `Reps only · form not checked`; `Clean` text `text-good`, `Not reached` `text-ink-3`. Delete the local `setColor`.
  - footnote: `mt-3 text-xs text-ink-3`, text `Each box is one set: reps done / planned. Hover a box for details.`

- [ ] **Step 8: Page shell** — `web/app/c/[token]/page.tsx`: `<main>` className `"flex-1 bg-canvas text-ink"`; `Loading` skeleton blocks `bg-sunken`.

- [ ] **Step 9: Verify** — `npx tsc --noEmit && npm test` all pass; screenshot `/c/demo` at 1440×900 and 390×844: table readable, no horizontal scroll at 390, ↑/↓ moves the highlight, `/` focuses search.

- [ ] **Step 10: Commit** — `git add web/app/c/[token]/page.tsx web/components/coach web/lib/coach-status.ts web/tests/coach-status.test.ts && git commit -m "web: coach dashboard in Clean · Light — client table, tabs, keyboard nav, KPI cards"`

---

### Task 6: Programs page restyle

**Files:**
- Modify: `web/app/c/[token]/program/page.tsx`, `web/app/c/[token]/program/forms.tsx`

- [ ] **Step 1: Mechanical class map** — apply exactly these replacements in both files (strings are unique enough to replace all occurrences):

| From | To |
|---|---|
| `min-h-screen bg-zinc-950 px-4 pb-12 pt-5 text-zinc-100` | `min-h-screen bg-canvas px-4 pb-12 pt-5 text-ink` |
| `rounded-2xl border border-zinc-800 bg-zinc-900` | `rounded-[14px] border border-line bg-surface` |
| `rounded-xl border border-zinc-800 bg-zinc-950/40` | `rounded-[10px] border border-line bg-canvas` |
| `rounded-2xl border border-dashed border-zinc-800` | `rounded-[14px] border border-dashed border-line-strong` |
| `divide-zinc-800` | `divide-line` |
| `text-zinc-50` / `text-zinc-100` / `text-zinc-200` | `text-ink` |
| `text-zinc-400` | `text-ink-2` |
| `text-zinc-500` | `text-ink-3` |
| `hover:text-zinc-100` | `hover:text-ink` |
| `bg-green-500/10 text-green-300` | `bg-good-soft text-good` |
| `bg-zinc-800 text-zinc-400` | `bg-none-soft text-ink-2` |
| `border-yellow-400/20 bg-yellow-400/10 px-4 py-3 text-sm text-yellow-100` | `border-line bg-warn-soft px-4 py-3 text-sm text-warn` |
| `text-red-400` | `text-bad` |
| `text-green-400` | `text-good` |
| `text-3xl font-bold tracking-tight` | `text-[34px] font-semibold tracking-[-0.025em]` |

In `forms.tsx` set:
```ts
const control = 'mt-2 block w-full rounded-[10px] border border-line-strong bg-surface p-3 text-sm text-ink file:mr-3 file:rounded-md file:border-0 file:bg-sunken file:px-3 file:py-1 file:text-ink disabled:opacity-60';
const button = 'mt-5 rounded-[10px] bg-brand px-5 py-2.5 text-sm font-semibold text-on-brand transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-40';
```
Only the upload button keeps brand orange; for the assign form use a second constant `buttonSecondary = 'mt-5 rounded-[10px] bg-ink px-5 py-2.5 text-sm font-semibold text-canvas transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40'` and use it on `AssignForm`'s button (one brand element per screen).

- [ ] **Step 2: Verify** — `grep -n "zinc-\|yellow-\|green-\|red-" "web/app/c/[token]/program/"*.tsx` prints nothing; `npm test` passes; screenshot `/c/<demo coach token>/program` at 1440×900.

- [ ] **Step 3: Commit** — `git add "web/app/c/[token]/program" && git commit -m "web: programs page in Clean · Light"`

---

### Task 7: Early access — table, validation, server action

**Files:**
- Create: `db/migrations/20261011_early_access.sql`, `web/lib/early-access.ts`, `web/app/early-access-action.ts`
- Test: `web/tests/early-access.test.ts`

**Interfaces:**
- Produces:
  - `type EarlyAccessInput = { name: string; email: string; coach_type: "online" | "in_person" | "both"; client_count: "1-10" | "11-30" | "31-100" | "100+"; note: string }`
  - `parseEarlyAccess(form: FormData): { ok: true; value: EarlyAccessInput } | { ok: false; message: string } | { ok: "bot" }`
  - `type EarlyAccessState = { ok: boolean; message: string }`
  - `joinEarlyAccess(_prev: EarlyAccessState, form: FormData): Promise<EarlyAccessState>` (server action)

- [ ] **Step 1: Migration** — `db/migrations/20261011_early_access.sql`

```sql
-- Trainer leads from the landing page. Apply after db/schema.sql. RLS on, no policies: only the service role writes.
create table if not exists early_access (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  name         text not null check (length(name) between 1 and 120),
  email        text not null check (length(email) between 3 and 254),
  coach_type   text not null check (coach_type in ('online', 'in_person', 'both')),
  client_count text not null check (client_count in ('1-10', '11-30', '31-100', '100+')),
  note         text not null default '' check (length(note) <= 1000),
  source       text not null default 'landing'
);
create unique index if not exists early_access_email_idx on early_access (lower(email));
alter table early_access enable row level security;
```

- [ ] **Step 2: Failing tests** — `web/tests/early-access.test.ts`

```ts
import { describe, expect, it } from "vitest";
import { parseEarlyAccess } from "@/lib/early-access";

const form = (over: Record<string, string> = {}) => {
  const f = new FormData();
  const base = { name: "Tristan", email: "Coach@Example.com ", coach_type: "online", client_count: "11-30", note: "", website: "" };
  for (const [k, v] of Object.entries({ ...base, ...over })) f.set(k, v);
  return f;
};

describe("parseEarlyAccess", () => {
  it("accepts a valid form and normalizes the email", () => {
    const r = parseEarlyAccess(form());
    expect(r).toEqual({ ok: true, value: { name: "Tristan", email: "coach@example.com", coach_type: "online", client_count: "11-30", note: "" } });
  });
  it("rejects a bad email with a friendly message", () => {
    expect(parseEarlyAccess(form({ email: "nope" }))).toEqual({ ok: false, message: "Enter a valid email." });
  });
  it("rejects an empty name", () => {
    expect(parseEarlyAccess(form({ name: "  " }))).toEqual({ ok: false, message: "Enter your name." });
  });
  it("rejects values outside the choices", () => {
    expect(parseEarlyAccess(form({ coach_type: "gym" })).ok).toBe(false);
    expect(parseEarlyAccess(form({ client_count: "5" })).ok).toBe(false);
  });
  it("flags bots that fill the hidden website field", () => {
    expect(parseEarlyAccess(form({ website: "http://spam" }))).toEqual({ ok: "bot" });
  });
  it("trims and caps the note", () => {
    const r = parseEarlyAccess(form({ note: "x".repeat(2000) }));
    expect(r.ok === true && r.value.note.length).toBe(1000);
  });
});
```

- [ ] **Step 3: FAIL** — `npx vitest run tests/early-access.test.ts`.

- [ ] **Step 4: Implement `web/lib/early-access.ts`**

```ts
// Validation for the landing page early-access form (db/migrations/20261011_early_access.sql).
export const COACH_TYPES = ["online", "in_person", "both"] as const;
export const CLIENT_COUNTS = ["1-10", "11-30", "31-100", "100+"] as const;

export type EarlyAccessInput = {
  name: string;
  email: string;
  coach_type: (typeof COACH_TYPES)[number];
  client_count: (typeof CLIENT_COUNTS)[number];
  note: string;
};

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;
const str = (f: FormData, k: string) => (typeof f.get(k) === "string" ? (f.get(k) as string) : "");

export function parseEarlyAccess(f: FormData): { ok: true; value: EarlyAccessInput } | { ok: false; message: string } | { ok: "bot" } {
  if (str(f, "website").trim()) return { ok: "bot" }; // honeypot: hidden from people, filled by bots
  const name = str(f, "name").trim().slice(0, 120);
  const email = str(f, "email").trim().toLowerCase();
  const coach_type = str(f, "coach_type");
  const client_count = str(f, "client_count");
  if (!name) return { ok: false, message: "Enter your name." };
  if (email.length > 254 || !EMAIL.test(email)) return { ok: false, message: "Enter a valid email." };
  if (!(COACH_TYPES as readonly string[]).includes(coach_type)) return { ok: false, message: "Choose how you coach." };
  if (!(CLIENT_COUNTS as readonly string[]).includes(client_count)) return { ok: false, message: "Choose how many clients you have." };
  return {
    ok: true,
    value: { name, email, coach_type: coach_type as EarlyAccessInput["coach_type"], client_count: client_count as EarlyAccessInput["client_count"], note: str(f, "note").trim().slice(0, 1000) },
  };
}
```

- [ ] **Step 5: PASS** — rerun the test.

- [ ] **Step 6: Server action** — `web/app/early-access-action.ts`

```ts
"use server";

import { parseEarlyAccess } from "@/lib/early-access";
import { hasSupabase } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

export type EarlyAccessState = { ok: boolean; message: string };
const THANKS = "You're on the list. We'll email you when your spot opens.";

export async function joinEarlyAccess(_prev: EarlyAccessState, form: FormData): Promise<EarlyAccessState> {
  const parsed = parseEarlyAccess(form);
  if (parsed.ok === "bot") return { ok: true, message: THANKS };
  if (!parsed.ok) return { ok: false, message: parsed.message };
  if (!hasSupabase()) return { ok: false, message: "Sign-ups are paused right now. Email us instead." };
  const { error } = await supabaseServer().from("early_access").insert({ ...parsed.value, source: "landing" });
  if (error && error.code !== "23505") return { ok: false, message: "Something went wrong. Please try again." }; // 23505 = already signed up
  return { ok: true, message: THANKS };
}
```

- [ ] **Step 7: Apply the migration to the beat-muse project** — confirm `web/.env.local`'s `SUPABASE_URL` host is `tqfilmqvbhrywjstmyhu.supabase.co`, then:

```bash
cd ~/Desktop/Projects/bm-ui && supabase db query --project-ref tqfilmqvbhrywjstmyhu -f db/migrations/20261011_early_access.sql   # check `supabase db query --help` for the exact flags first
```

If the CLI refuses, give Jimmy the SQL file to paste into the Supabase SQL editor and wait. Verify with a REST insert+delete of a test row using the service key (never print the key).

- [ ] **Step 8: Commit** — `git add db/migrations/20261011_early_access.sql web/lib/early-access.ts web/app/early-access-action.ts web/tests/early-access.test.ts && git commit -m "Early access: leads table, validated server action with honeypot + email dedupe"`

---

### Task 8: Trainer landing page

**Files:**
- Create: `web/components/landing/early-access-form.tsx`
- Modify: `web/app/page.tsx`, `web/app/layout.tsx` (metadata description only)

**Interfaces:**
- Consumes: `joinEarlyAccess`, `EarlyAccessState` (Task 7), `COACH_TYPES`, `CLIENT_COUNTS`, `Brand`.

- [ ] **Step 1: Form component** — `web/components/landing/early-access-form.tsx`

```tsx
"use client";

import { useActionState } from "react";

import { joinEarlyAccess, type EarlyAccessState } from "@/app/early-access-action";

const field = "mt-1.5 block w-full rounded-[10px] border border-line-strong bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-3 focus:border-ink/40 focus:outline-none";
const label = "text-[12.5px] font-medium text-ink-2";

export function EarlyAccessForm() {
  const [state, action, pending] = useActionState<EarlyAccessState, FormData>(joinEarlyAccess, { ok: false, message: "" });
  if (state.ok) return <p role="status" className="rounded-[14px] bg-good-soft p-6 text-center text-sm font-semibold text-good">{state.message}</p>;
  return (
    <form action={action} className="grid gap-4 sm:grid-cols-2">
      <label className="block"><span className={label}>Name</span><input name="name" required maxLength={120} autoComplete="name" className={field} /></label>
      <label className="block"><span className={label}>Email</span><input name="email" type="email" required maxLength={254} autoComplete="email" className={field} /></label>
      <label className="block"><span className={label}>How do you coach?</span>
        <select name="coach_type" required defaultValue="" className={field}>
          <option value="" disabled>Choose one</option>
          <option value="online">Online</option><option value="in_person">In person</option><option value="both">Both</option>
        </select>
      </label>
      <label className="block"><span className={label}>How many clients?</span>
        <select name="client_count" required defaultValue="" className={field}>
          <option value="" disabled>Choose one</option>
          <option value="1-10">1–10</option><option value="11-30">11–30</option><option value="31-100">31–100</option><option value="100+">100+</option>
        </select>
      </label>
      <label className="block sm:col-span-2"><span className={label}>Anything we should know? (optional)</span>
        <textarea name="note" rows={3} maxLength={1000} className={field} />
      </label>
      {/* honeypot: hidden from people and screen readers */}
      <input name="website" tabIndex={-1} autoComplete="off" aria-hidden className="hidden" />
      <div className="flex flex-wrap items-center gap-3 sm:col-span-2">
        <button disabled={pending} className="rounded-[10px] bg-brand px-5 py-2.5 text-sm font-semibold text-on-brand transition hover:brightness-95 disabled:opacity-50">
          {pending ? "Sending…" : "Get early access"}
        </button>
        {state.message ? <p role="alert" className="text-sm text-bad">{state.message}</p> : <p className="text-xs text-ink-3">Free during early access. No spam.</p>}
      </div>
    </form>
  );
}
```

- [ ] **Step 2: Replace `web/app/page.tsx`**

```tsx
import Link from "next/link";

import { EarlyAccessForm } from "@/components/landing/early-access-form";
import { SiteHeader } from "@/components/site-header";

const STEPS = [
  { title: "Upload your program", body: "The PDF you already use. Brodie reads the days, exercises, sets and reps." },
  { title: "Your client FaceTimes Brodie", body: "Brodie counts every rep on camera, cues form out loud and talks them through rest." },
  { title: "You see how it went", body: "A recap with a muscle heat map for the client, and a triage inbox for you." },
];
const FEATURES = [
  { title: "Triage inbox", body: "Clients who need you come first: flagged sets, short sessions, missed workouts." },
  { title: "Form flags with clips", body: "Tap a muscle to watch the reps behind it. Brodie notes what it cued." },
  { title: "Built for big rosters", body: "Search, filters and keyboard navigation for coaches with dozens of clients." },
];
const FAQ = [
  { q: "What does my client need?", a: "An iPhone with FaceTime. No app to install, no account to make." },
  { q: "Is the video private?", a: "Recaps are private links. Workout footage is stored privately and only shown to you and your client." },
  { q: "What does it cost?", a: "Free during early access. We'll talk pricing with you before anything changes." },
];

export default function Home() {
  return (
    <main className="flex-1 bg-canvas text-ink">
      <div className="mx-auto w-full max-w-5xl px-4 pb-20 pt-5 sm:px-6 sm:pt-8">
        <SiteHeader
          context={
            <>
              <Link href="/c/demo" className="hidden text-ink-2 hover:text-ink sm:inline">Coach demo</Link>
              <a href="#early-access" className="rounded-[10px] bg-brand px-3.5 py-2 text-sm font-semibold text-on-brand hover:brightness-95">Get early access</a>
            </>
          }
        />

        <section className="mt-16 max-w-2xl sm:mt-24">
          <p className="text-[12.5px] font-medium text-ink-3">For online coaches and busy trainers</p>
          <h1 className="mt-2 text-[40px] font-semibold leading-[1.03] tracking-[-0.03em] text-balance sm:text-[56px]">
            Eyes on every rep, even when you&apos;re not there.
          </h1>
          <p className="mt-5 text-lg leading-relaxed text-ink-2">
            Your client FaceTimes Brodie, an AI coach that runs your program, counts reps on camera and cues form out loud.
            You get a recap of every set and an inbox of who needs you.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <a href="#early-access" className="rounded-[10px] bg-ink px-5 py-3 text-sm font-semibold text-canvas hover:opacity-90">Join the early access list</a>
            <Link href="/r/demo" className="rounded-[10px] border border-line-strong px-5 py-3 text-sm font-semibold text-ink hover:bg-sunken">See a client recap</Link>
          </div>
        </section>

        <ol className="mt-20 grid gap-3 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="rounded-[14px] border border-line bg-surface p-5">
              <span className="text-[12.5px] font-medium text-ink-3">Step {i + 1}</span>
              <h2 className="mt-1 text-[17px] font-semibold">{s.title}</h2>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{s.body}</p>
            </li>
          ))}
        </ol>

        <section className="mt-20">
          <h2 className="text-[26px] font-semibold tracking-[-0.025em]">Built for coaches with a lot of clients</h2>
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="rounded-[14px] border border-line bg-surface p-5">
                <h3 className="font-semibold">{f.title}</h3>
                <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{f.body}</p>
              </div>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-3 text-sm">
            <Link href="/c/demo" className="font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">Open the coach dashboard demo →</Link>
            <Link href="/r/demo" className="font-semibold text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">Open a client recap →</Link>
          </div>
        </section>

        <section id="early-access" className="mt-20 scroll-mt-8 rounded-[18px] border border-line bg-surface p-6 sm:p-8">
          <h2 className="text-[26px] font-semibold tracking-[-0.025em]">Get early access</h2>
          <p className="mt-1.5 max-w-xl text-sm text-ink-2">We&apos;re onboarding a small group of coaches. Tell us about your roster and we&apos;ll set you up.</p>
          <div className="mt-6"><EarlyAccessForm /></div>
        </section>

        <section className="mt-20 grid gap-6 sm:grid-cols-3">
          {FAQ.map((f) => (
            <div key={f.q}>
              <h3 className="font-semibold">{f.q}</h3>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-2">{f.a}</p>
            </div>
          ))}
        </section>

        <footer className="mt-20 border-t border-line pt-6 text-xs text-ink-3">© Brodie for Coaches · Coaching feedback, not medical advice.</footer>
      </div>
    </main>
  );
}
```

(Hero button is `bg-ink`, not brand, so the header "Get early access" stays the one brand element above the fold; the form button is brand inside its own section.)

- [ ] **Step 3: Metadata** — in `web/app/layout.tsx` set `description: "AI form coaching over FaceTime for online coaches: your client works out with Brodie, you get a recap of every rep."`.

- [ ] **Step 4: Verify** — `npx tsc --noEmit && npm test`; dev server: submit the form with a real-looking test email → success message; submit again with the same email in caps → success (deduped); delete the test row via REST with the service key afterwards. Screenshot `/` at 390×844 and 1440×900.

- [ ] **Step 5: Commit** — `git add web/app/page.tsx web/app/layout.tsx web/components/landing && git commit -m "web: trainer landing page with early-access form"`

---

### Task 9: Raw-palette guard, full check, PR

**Files:**
- Create: `web/tests/no-raw-palette.test.ts`
- Modify: any remaining file the guard flags (`web/components/heatmap/legend.tsx` stays: it renders on the stage panel)

- [ ] **Step 1: Guard test** — `web/tests/no-raw-palette.test.ts`

```ts
import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

// Light-theme files must use STYLE.md tokens. Stage components (dark panels for heat map and video) and lab pages are exempt.
const ROOT = path.join(import.meta.dirname, "..");
const EXEMPT = [/components[\\/]heatmap[\\/]/, /components[\\/]rep-review[\\/](?!review-launcher)/, /components[\\/]lab[\\/]/, /app[\\/]lab[\\/]/, /app[\\/]clips[\\/]/, /app[\\/]api[\\/]/, /components[\\/]ui[\\/]/];
const RAW = /\b(?:bg|text|border|divide|ring|from|to|placeholder|outline)-(?:zinc|slate|neutral|gray|stone|green|red|yellow|amber)-\d{2,3}\b/g;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = path.join(dir, n);
    return statSync(p).isDirectory() ? files(p) : /\.tsx?$/.test(n) ? [p] : [];
  });
}

it("light-theme files use tokens, not raw palette classes", () => {
  const offenders = [...files(path.join(ROOT, "app")), ...files(path.join(ROOT, "components"))]
    .filter((f) => !EXEMPT.some((r) => r.test(f)))
    .flatMap((f) => {
      const text = readFileSync(f, "utf8").replace(/bg-stage[^"]*text-zinc-100/g, "");
      return (text.match(RAW) ?? []).map((m) => `${path.relative(ROOT, f)}: ${m}`);
    });
  expect(offenders).toEqual([]);
});
```

- [ ] **Step 2: Run** — `npx vitest run tests/no-raw-palette.test.ts`; fix each offender with the Task 6 class map until it passes (e.g. `app/not-found.tsx` or `components/coming-soon.tsx` if present).

- [ ] **Step 3: Full verification** — `npm test`, `npx tsc --noEmit`, `npm run build` all pass; screenshots at 390×844 and 1440×900 for `/`, `/r/demo`, `/c/demo`, programs page; confirm no horizontal scroll at 390 (`document.documentElement.scrollWidth <= 390`).

- [ ] **Step 4: Commit** (guard + fixes) — `git add -A web && git diff --cached --name-only` (check no env/keys) `&& git commit -m "web: guard against raw palette classes; finish token sweep"`

- [ ] **Step 5: Rebase + PR** — `git fetch origin && git rebase origin/main` (resolve conflicts keeping teammates' logic, re-run Step 3), `git push -u origin jimmy-ui-revamp`, `gh pr create` titled "web: Clean · Light redesign + trainer landing page" with screenshots listed and the test results; end the body with the Claude Code attribution line.
