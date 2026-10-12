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
