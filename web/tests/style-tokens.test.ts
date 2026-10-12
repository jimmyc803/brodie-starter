import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(path.join(import.meta.dirname, "../app/globals.css"), "utf8");
const TOKENS: Record<string, string> = {
  canvas: "#f3f1ec", surface: "#ffffff", sunken: "#ece9e3", stage: "#0b0b0b",
  ink: "#141414", "ink-2": "#55524c", "ink-3": "#8a867f",
  line: "#14141414", "line-strong": "#14141426",
  brand: "#ff5a1f", "on-brand": "#ffffff",
  good: "#15803d", warn: "#a16207", bad: "#dc2626", idle: "#8a867f",
  "good-soft": "#15803d14", "warn-soft": "#ca8a041a", "bad-soft": "#dc262612", "idle-soft": "#14141410",
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
