// ↑/↓ through the visible client rows, clamped at the ends.
export function moveSelection(ids: string[], current: string | null, key: string): string | null {
  if (!ids.length) return null;
  const i = current === null ? -1 : ids.indexOf(current);
  if (key === "ArrowDown") return i < 0 ? ids[0] : ids[Math.min(ids.length - 1, i + 1)];
  if (key === "ArrowUp") return i < 0 ? ids[0] : ids[Math.max(0, i - 1)];
  return current;
}

type KeyLike = { key: string; metaKey?: boolean; ctrlKey?: boolean; altKey?: boolean; shiftKey?: boolean; isComposing?: boolean; defaultPrevented?: boolean };

// Which client-list shortcut a key press is, given where focus is: "search" (the search box), "list" (a client row),
// "body" (nothing focused) or "other" (any other control). Enter is never taken: rows are real links.
export function listKeyAction(e: KeyLike, where: "search" | "list" | "body" | "other"): "search" | "move" | null {
  if (e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.isComposing || e.defaultPrevented) return null;
  if (e.key === "/" && (where === "body" || where === "list")) return "search";
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && (where === "search" || where === "list")) return "move";
  return null;
}

// Open on "Needs review" only when someone needs review and the selected client is one of them.
export function initialTab(clients: { id: string; status: string }[], selectedId: string | null): "review" | "all" {
  const review = clients.filter((c) => c.status === "review");
  if (!review.length) return "all";
  return selectedId === null || review.some((c) => c.id === selectedId) ? "review" : "all";
}
