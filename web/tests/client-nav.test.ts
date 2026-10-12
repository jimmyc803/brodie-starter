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

import { initialTab, listKeyAction } from "@/lib/client-nav";

describe("listKeyAction", () => {
  const k = (key: string, mods: Partial<Record<"metaKey" | "ctrlKey" | "altKey" | "shiftKey" | "isComposing" | "defaultPrevented", boolean>> = {}) => ({ key, ...mods });
  it("moves with arrows only from the search box or the list, never the rest of the page", () => {
    expect(listKeyAction(k("ArrowDown"), "search")).toBe("move");
    expect(listKeyAction(k("ArrowUp"), "list")).toBe("move");
    expect(listKeyAction(k("ArrowDown"), "body")).toBeNull();
    expect(listKeyAction(k("ArrowDown"), "other")).toBeNull();
  });
  it("never takes Enter (rows are real links)", () => {
    for (const w of ["search", "list", "body", "other"] as const) expect(listKeyAction(k("Enter"), w)).toBeNull();
  });
  it("focuses search on / unless the user is typing somewhere", () => {
    expect(listKeyAction(k("/"), "body")).toBe("search");
    expect(listKeyAction(k("/"), "list")).toBe("search");
    expect(listKeyAction(k("/"), "search")).toBeNull();
    expect(listKeyAction(k("/"), "other")).toBeNull();
  });
  it("ignores modifier combos, IME composition and handled events", () => {
    expect(listKeyAction(k("ArrowDown", { metaKey: true }), "list")).toBeNull();
    expect(listKeyAction(k("/", { ctrlKey: true }), "body")).toBeNull();
    expect(listKeyAction(k("ArrowDown", { isComposing: true }), "search")).toBeNull();
    expect(listKeyAction(k("ArrowDown", { defaultPrevented: true }), "list")).toBeNull();
  });
});

describe("initialTab", () => {
  const c = (id: string, status: "review" | "on_track" | "inactive") => ({ id, status });
  it("opens Needs review when someone needs review and nothing else is selected", () => {
    expect(initialTab([c("a", "review"), c("b", "on_track")], null)).toBe("review");
    expect(initialTab([c("a", "review")], "a")).toBe("review");
  });
  it("opens All when the selected client isn't in Needs review", () => {
    expect(initialTab([c("a", "review"), c("b", "on_track")], "b")).toBe("all");
  });
  it("opens All when nobody needs review", () => {
    expect(initialTab([c("b", "on_track")], null)).toBe("all");
  });
});
