# UI revamp: "Clean · Light"

Approved direction: the "Clean · Light" mockup (2026-10-11). Goal: the web app looks intentionally designed (not "vibecoded"),
calm and smooth, easy to navigate for a coach with many clients, and every page follows one written style system.

## What Jimmy asked for
- Light theme first (dark later, same tokens).
- No purple. One brand color: signal orange, used only for the logo mark and the single main action on a screen.
- Clean, smooth type: one font (Geist), normal width, medium weights; no stretched/condensed display type, no spaced
  uppercase mono labels.
- The heat map drawing stays exactly as it is (neon body on a dark stage panel).
- Colored numbers must explain themselves, without clutter.

## Style system (lives in `web/STYLE.md` + tokens in `web/app/globals.css`)
Semantic Tailwind tokens, so components never use raw `zinc-*`/hex again:

| Token | Light value | Use |
|---|---|---|
| `canvas` | #F3F1EC | page background (warm paper) |
| `surface` | #FFFFFF | cards, selected list row, inputs |
| `sunken` | #ECE9E3 | sidebar, active tab/nav chip |
| `ink` / `ink-2` / `ink-3` | #141414 / #55524C / #8A867F | text: primary / secondary / labels & hints |
| `line` / `line-strong` | #14141414 / #14141426 | hairlines, card borders / input borders |
| `brand` (+ `on-brand`) | #FF5A1F (+ #FFFFFF) | logo mark, the one primary button |
| `good` / `warn` / `bad` / `none` | #15803D / #A16207 / #DC2626 / #8A867F | data meaning only; each has a `-soft` tint for chips |
| `stage` | #0B0B0B | the dark panel behind the heat map and video |

Type scale (Geist): display 34/600, title 26/600, hero number 76/600, stat number 28–34/600, body 14/400–500,
label 12.5/500 `ink-3` sentence case. Numbers use tabular figures and slight negative tracking.
Shape: cards radius 14px, buttons/inputs 10px, chips 6px; 1px `line` borders; no gradients, glows (outside the heat map),
or pill-everything. Spacing on a 4px grid; sections 24–40px apart.

Rules: green/amber/red only when they mean a quality; one brand-orange element per screen; every colored number has a
word next to it; grey = "not measured" (never green for unchecked form).

## Clarity fixes (not more clutter)
- **Muscles 6 · 3 · 2** → one thin 3-segment bar with a single caption line: "6 solid · 3 okay · 2 work on".
- **Set chips** show `9/10`; tooltip/tap: "Set 3 · 9 of 10 reps · 2 flagged: Sink lower". Colors: green = all reps clean,
  amber = short or a few flagged, red = many flagged, grey = form not checked (bicep curls).
- A single small legend line where chips first appear: "Each box is one set · reps done / planned".

## Pages (all existing; layout changes, data/logic untouched)
1. **Recap `/r/[token]`** (phone-first): header, hero reps number, 3 stat cards, rank card, heat map on `stage` panel,
   tap-a-muscle card with Watch (existing players restyled, not rewritten), "What you did" exercise list.
2. **Coach dashboard `/c/[token]`**: top nav (Clients · Programs, brand Upload button); left column = search (`/` focuses),
   tabs Needs review / All / Inactive, compact sortable table (client, last session, reps, clean %, status dot),
   ↑/↓ moves selection, Enter opens; right = selected client: header, 4 KPI cards, "Needs a look" + exercises/sets.
3. **Programs `/c/[token]/program`** and **home `/`**: restyled with the same tokens.
4. Heat map, rep-review player, clip player, recap PNG (`/api/recap-image`): drawing/overlay logic unchanged; only the
   surrounding chrome uses tokens. The PNG keeps its own dark look (it's a share image).

## Phase 1 addition: trainer landing page + early access (approved 2026-10-11)
The product is now real (post-hackathon) and the first customers are **online coaches**, plus in-person trainers with
many clients. The home page `/` becomes a landing page that sells to them and collects leads.
- Sections: hero ("Eyes on every rep, even when you're not there." + sub-line + **Get early access** brand button and
  "See a client recap" link) → how it works (3 steps: upload your program → client FaceTimes Brodie → you get a recap and a
  triage inbox) → product shots (real recap + coach dashboard, as live links/screens, not fake images) → "Built for coaches
  with lots of clients" (triage inbox, form flags, rep clips) → early-access form → short FAQ (privacy, what the client
  needs: an iPhone + FaceTime, pricing "free during early access").
- **Early-access form**: name, email, coaching type (online / in person / both), roughly how many clients, optional
  note. Server action → Supabase table `early_access` (new migration: id, created_at, name, email, coach_type,
  client_count, note, source) via service role; RLS on with no policies like every other table. Validation server-side,
  honeypot field against bots, email de-duplicated (upsert on lower(email)). Success state in place; no emails sent yet.
- Nothing else on the backend changes in Phase 1.

## Out of scope (Phase 1)
Dark theme (tokens make it a later swap), coach accounts/auth, add-client, client onboarding/consent, mark-reviewed,
coach notes (Phase 2, separate spec), new data/contract changes beyond `early_access`.

## Risks
- Stanley/Ryan are merging into `web/` in parallel; work on branch `jimmy-ui-revamp`, rebase often, keep their logic.
- Many files touched → do it page by page, build + tests + 390px/1440px screenshots after each.

## Done when
Every page uses tokens only (no `zinc-*` left), build + tests pass, screenshots at 390×844 and 1440×900 match the mockup,
and `web/STYLE.md` describes the system so future work stays consistent.
