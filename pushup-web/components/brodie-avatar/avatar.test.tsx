import * as React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import AvatarLabPage from "../../app/avatar-lab/page";
import { Avatar, avatarParts } from "./index";

const muscles = ["chest", "triceps", "delts", "core"] as const;

function musclePaths(markup: string, muscle: string): string[] {
  return Array.from(markup.matchAll(new RegExp(`<path data-muscle="${muscle}" d="([^"]+)"`, "g")), (match) => match[1]);
}

describe("avatarParts", () => {
  it("grows each muscle monotonically across all ten levels", () => {
    for (const muscle of muscles) {
      for (let level = 1; level < 10; level += 1) {
        expect(avatarParts(level + 1)[muscle]).toBeGreaterThan(avatarParts(level)[muscle]);
      }
    }
  });

  it("clamps out-of-range levels and handles non-finite input", () => {
    for (const level of [-Infinity, -100, 0, NaN]) {
      expect(avatarParts(level)).toEqual(avatarParts(1));
    }
    for (const level of [11, 100, Infinity]) {
      expect(avatarParts(level)).toEqual(avatarParts(10));
    }
    for (const muscle of muscles) {
      expect(avatarParts(4.5)[muscle]).toBeGreaterThan(avatarParts(4)[muscle]);
      expect(avatarParts(4.5)[muscle]).toBeLessThan(avatarParts(5)[muscle]);
    }
  });
});

describe("Avatar", () => {
  it.each(["flex", "idle"] as const)("changes all four muscle paths but preserves head and legs in %s pose", (pose) => {
    const first = renderToStaticMarkup(<Avatar level={1} pose={pose} />);
    const last = renderToStaticMarkup(<Avatar level={10} pose={pose} />);
    for (const muscle of muscles) {
      const startPaths = musclePaths(first, muscle);
      const endPaths = musclePaths(last, muscle);
      expect(startPaths).toHaveLength(muscle === "core" ? 1 : 2);
      expect(endPaths).toHaveLength(startPaths.length);
      startPaths.forEach((path, index) => expect(endPaths[index]).not.toBe(path));
    }
    for (const part of ["head", "legs", "shorts"]) {
      const pattern = new RegExp(`<g data-part="${part}"[^>]*>[\\s\\S]*?</g>`);
      const firstPart = first.match(pattern)?.[0];
      expect(firstPart).toBeTruthy();
      expect(last.match(pattern)?.[0]).toBe(firstPart);
    }
  });

  it("renders deterministic standalone SVG with defaults and custom options", () => {
    const defaults = renderToStaticMarkup(<Avatar level={3} />);
    expect(defaults).toContain('width="96" height="96"');
    expect(defaults).toContain('fill="#D4FF3A"');
    expect(defaults).toBe(renderToStaticMarkup(<Avatar level={3} />));
    const custom = renderToStaticMarkup(<Avatar level={3} size={240} accent="#FF8855" pose="idle" />);
    expect(custom).toContain('width="240" height="240"');
    expect(custom).toContain('fill="#FF8855"');
    expect(custom).toContain("rotate(65 30 86)");
    expect(custom).not.toMatch(/class=|<image|<foreignObject|<style|<script|NaN|Infinity/);
    expect(renderToStaticMarkup(<Avatar level={-2} />)).toBe(renderToStaticMarkup(<Avatar level={1} />));
    expect(renderToStaticMarkup(<Avatar level={20} />)).toBe(renderToStaticMarkup(<Avatar level={10} />));
  });
});

describe("avatar lab", () => {
  it("renders all ten levels using the shared avatar in both poses", () => {
    const markup = renderToStaticMarkup(<AvatarLabPage />);
    expect(markup.match(/<figure /g)).toHaveLength(10);
    expect(markup.match(/<svg /g)).toHaveLength(20);
    for (let level = 1; level <= 10; level += 1) {
      expect(markup).toContain(`<figcaption>Level ${level}</figcaption>`);
      expect(markup).toContain(renderToStaticMarkup(<Avatar level={level} size={160} />));
    }
  });
});
