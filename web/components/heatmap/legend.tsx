import { fillFor } from "@/lib/body/svg";
import type { Color } from "@/lib/contract";

const ITEMS: [Color, string][] = [
  ["green", "Solid"],
  ["yellow", "Room to improve"],
  ["red", "Needs work"],
  ["gray", "Not trained this session"],
];

export function HeatmapLegend({ className }: { className?: string }) {
  return (
    <ul className={`flex flex-wrap justify-center gap-x-4 gap-y-1 text-xs text-zinc-400 ${className ?? ""}`}>
      {ITEMS.map(([c, label]) => (
        <li key={c} className="flex items-center gap-1.5">
          <span className="size-2.5 rounded-full" style={{ background: fillFor(c) }} />
          {label}
        </li>
      ))}
    </ul>
  );
}
