// The heat map body as a plain SVG string: the single renderer behind the web heat map's look and the recap PNG,
// so the FaceTime/iMessage image matches the web page. Pure: no React, no I/O.
import { COLORS, type Color, type MuscleKey } from "@/lib/contract";
import { SHAPES, VIEWBOX, type BodySide } from "@/lib/body/shapes";

export const BODY_BASE = "#3f3f46"; // unscored parts (head, knees)
export const BODY_STROKE = "#18181b";

export function fillFor(color: Color | undefined): string {
  return COLORS[color ?? "gray"];
}

export function bodySvg(
  side: BodySide,
  colors: Partial<Record<MuscleKey, Color>>,
  opts: { width?: number; selected?: MuscleKey | null } = {},
): string {
  const w = opts.width ?? 300;
  const h = (w * VIEWBOX.height) / VIEWBOX.width;
  const polys = SHAPES[side]
    .map((s) => {
      const fill = s.muscle ? fillFor(colors[s.muscle]) : BODY_BASE;
      const sel = s.muscle && s.muscle === opts.selected;
      return `<polygon points="${s.points}" fill="${fill}" stroke="${sel ? "#ffffff" : BODY_STROKE}" stroke-width="${sel ? 1.2 : 0.5}" stroke-linejoin="round"/>`;
    })
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${VIEWBOX.width} ${VIEWBOX.height}">${polys}</svg>`;
}

export function bodySvgDataUri(...args: Parameters<typeof bodySvg>): string {
  return `data:image/svg+xml;base64,${Buffer.from(bodySvg(...args)).toString("base64")}`;
}
