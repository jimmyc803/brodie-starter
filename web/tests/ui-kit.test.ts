import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { RankBadge } from "@/components/recap/rank-badge";
import { SetChip } from "@/components/ui-kit/set-chip";
import { RANKS } from "@/lib/ranks";

describe("SetChip", () => {
  it("gives screen readers and tappers the full sentence, not just 9/10", () => {
    const set = { set_number: 3, planned_reps: 10, completed_reps: 9, reps: Array.from({ length: 9 }, (_, i) => ({ rep_number: i + 1, faults: [] as string[] })) };
    const html = renderToStaticMarkup(createElement(SetChip, { set, exerciseKey: "squat" }));
    expect(html).toContain('class="sr-only">Set 3 · 9 of 10 reps · clean');
    expect(html).toContain("<button");
  });
});

describe("RankBadge", () => {
  it("prints the rank name in ink (rank colors are unreadable as text on white) with a color swatch", () => {
    const rank = RANKS[RANKS.length - 3];
    const html = renderToStaticMarkup(createElement(RankBadge, { r: { rank, next: null, skipped: false, score: 0.9 } as never }));
    const name = html.match(/<p[^>]*>[^<]*<span[^>]*><\/span>[^<]*/)?.[0] ?? html.slice(html.indexOf(rank.name) - 300, html.indexOf(rank.name));
    expect(name).not.toMatch(/style="color:/);
    expect(html).toContain(`background:${rank.color}`);
  });
});
