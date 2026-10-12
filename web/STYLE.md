# Brodie style guide — Clean · Light

Read this before touching any UI. Components use the tokens below as Tailwind classes (`bg-surface`, `text-ink-3`,
`border-line` …). Never use raw `zinc-*`, `slate-*`, `white/…`, or hex colors in light-theme components; add a token
here instead. (Stage components — the heat map and the video players — keep their own dark styling.)

## Colors
| Token | Value | Use |
|---|---|---|
| `canvas` | #F3F1EC | page background (warm paper) |
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
| `idle` / `idle-soft` | #8A867F | not measured, not reached, inactive |

(`idle` rather than `none`: Tailwind already owns `bg-none`.)

Rules:
- Quality colors only when they mean quality. Grey (`idle`) means "not measured" — exercises Brodie has no form cues
  for (bicep curls, pull-ups) are never green.
- Every colored number gets a word next to it ("6 solid · 3 okay · 2 work on", "9/10" with a tooltip).
- One brand-orange element per screen. Other main actions use the dark (`bg-ink`) or outline button.

## Type (Geist only)
| Role | Classes |
|---|---|
| Page title | `text-[34px] font-semibold tracking-[-0.025em] leading-[1.05]` (coach pages: `text-[28px]`) |
| Section title | `text-base font-semibold` |
| Hero number | `text-[76px] font-semibold tracking-[-0.035em] leading-none tabular-nums` |
| Stat number | `text-[28px] font-semibold tracking-[-0.035em] leading-none tabular-nums` (34px on desktop KPIs) |
| Body | `text-sm text-ink`; secondary `text-sm text-ink-2` |
| Label | `text-[12.5px] font-medium text-ink-3` — sentence case, never uppercase or letter-spaced, never monospace |

No condensed or expanded font widths. Medium/semibold weights; bold only for the wordmark.

## Shape and space
- Cards `rounded-[14px] border border-line bg-surface`; buttons and inputs `rounded-[10px]`; chips `rounded-md`;
  stage panels `rounded-[18px]`.
- 4px grid; 8–12px gaps inside cards; 24–40px between sections.
- No gradients, glows or heavy shadows (the heat map keeps its own glow).

## Recipes
- Primary button (brand): `rounded-[10px] bg-brand px-4 py-2.5 text-sm font-semibold text-on-brand hover:brightness-95`
- Dark button: `rounded-[10px] bg-ink px-4 py-2.5 text-sm font-semibold text-canvas hover:opacity-90`
- Secondary button: `rounded-[10px] border border-line-strong px-4 py-2.5 text-sm font-semibold text-ink hover:bg-sunken`
- Input: `rounded-[10px] border border-line-strong bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-ink-3`
- Card: `rounded-[14px] border border-line bg-surface p-4`
- Stat card: card + label on top + stat number.
- Tabs: `rounded-lg px-2.5 py-1 text-xs font-semibold` — active `bg-surface text-ink`, inactive `text-ink-3 hover:text-ink`.
- Status pill: `rounded-full px-2.5 py-1 text-xs font-semibold` + `bg-bad-soft text-bad` / `bg-good-soft text-good` /
  `bg-idle-soft text-ink-2`.
- Stage panel: `rounded-[18px] bg-stage p-4 text-zinc-100` — what's inside keeps its dark styling.
- Set chip: `components/ui-kit/set-chip.tsx`. Muscle balance: `components/ui-kit/muscle-balance.tsx`.
  Logo: `components/ui-kit/brand.tsx`. Quality rules: `lib/quality.ts`.
