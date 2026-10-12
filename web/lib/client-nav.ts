// ↑/↓ through the visible client rows, clamped at the ends.
export function moveSelection(ids: string[], current: string | null, key: string): string | null {
  if (!ids.length) return null;
  const i = current === null ? -1 : ids.indexOf(current);
  if (key === "ArrowDown") return i < 0 ? ids[0] : ids[Math.min(ids.length - 1, i + 1)];
  if (key === "ArrowUp") return i < 0 ? ids[0] : ids[Math.max(0, i - 1)];
  return current;
}
