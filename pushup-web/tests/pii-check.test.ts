import { describe, expect, it } from "vitest";
import { findPii } from "../scripts/pii-lib.mjs";
import { checkUrls } from "../scripts/pii-check.mjs";

describe("findPii", () => {
  it("flags phones and emails", () => {
    expect(findPii("call 555-123-4567 now").map((h) => h.kind)).toContain("phone");
    expect(findPii("(555) 123-4567")).not.toHaveLength(0);
    expect(findPii("+15551234567")).not.toHaveLength(0);
    expect(findPii("mail me a.b@example.com")).toEqual([{ kind: "email", sample: "a.b@example.com" }]);
  });
  it("passes clean content", () => {
    expect(findPii("<p>Ana 1234 points, 42 valid reps, 2026-10-12T20:00:00Z</p>")).toEqual([]);
  });
});

describe("checkUrls", () => {
  it("reports failing urls", async () => {
    const pages: Record<string, string> = { "http://a": "clean", "http://b": "x +15551234567 y" };
    const fake = (async (u: string) => ({ text: async () => pages[u] })) as unknown as typeof fetch;
    const f = await checkUrls(["http://a", "http://b"], fake);
    expect(f).toHaveLength(1);
    expect(f[0].url).toBe("http://b");
  });
});
