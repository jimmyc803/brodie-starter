// The heat map body as a plain SVG string, for the recap PNG and the dashboard thumbnails. Same drawing as the web
// heat map (lib/body/neon.ts). Pure: no React, no I/O.
import { neonLayers, type Fills } from "@/lib/body/neon";
import { VIEWBOX, type BodySide } from "@/lib/body/shapes";
import { COLORS, type Color } from "@/lib/contract";

export { BODY_BASE, BODY_STROKE } from "@/lib/body/neon";

// The flat contract color for a category (legend dots, labels).
export function fillFor(color: Color | undefined): string {
  return COLORS[color ?? "gray"];
}

const PAD = 6; // room for the glow halo around the body

export function bodySvg(side: BodySide, fills: Fills, opts: { width?: number; glow?: boolean; id?: string } = {}): string {
  const glow = opts.glow ?? true;
  const id = opts.id ?? `b${side}`;
  const vw = 100 + PAD * 2;
  const vh = VIEWBOX.height + PAD * 2;
  const w = opts.width ?? 300;
  const h = Math.round((w * vh) / vw);
  const L = neonLayers(side, fills, id, glow);
  const defs = glow
    ? `<defs><filter id="${id}-halo" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3"/></filter>${L.gradients
        .map(
          (g) =>
            `<radialGradient id="${g.id}" cx="50%" cy="45%" r="65%"><stop offset="0%" stop-color="${g.inner}"/><stop offset="100%" stop-color="${g.outer}"/></radialGradient>`,
        )
        .join("")}</defs>`
    : "";
  const halo = glow
    ? `<g filter="url(#${id}-halo)">${L.halo.map((p) => `<polygon points="${p.points}" fill="${p.fill}" opacity="${p.opacity.toFixed(2)}"/>`).join("")}</g>`
    : "";
  const shapes = L.shapes
    .map((s) => `<polygon points="${s.points}" fill="${s.fill}" stroke="#18181b" stroke-width="0.5" stroke-linejoin="round"/>`)
    .join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="${-PAD} ${-PAD} ${vw} ${vh}">${defs}${halo}${shapes}</svg>`;
}

export function bodySvgDataUri(...args: Parameters<typeof bodySvg>): string {
  return `data:image/svg+xml;base64,${Buffer.from(bodySvg(...args)).toString("base64")}`;
}
