import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";
import { expect, it } from "vitest";

// Light-theme files must use STYLE.md tokens. Stage components (dark panels for the heat map and video) and lab pages are exempt.
const ROOT = path.join(import.meta.dirname, "..");
const EXEMPT = [
  /components[\\/]heatmap[\\/]/,
  /components[\\/]rep-review[\\/](?!review-launcher)/,
  /components[\\/]lab[\\/]/,
  /app[\\/]lab[\\/]/,
  /app[\\/]clips[\\/]/,
  /app[\\/]api[\\/]/,
  /components[\\/]ui[\\/]/,
];
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
