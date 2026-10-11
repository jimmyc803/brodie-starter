// Small color helpers: mix colors in OKLCH (perceptual, so red -> yellow passes through orange, not muddy brown).
type Lch = [number, number, number];

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const toGamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.replace(/./g, "$&$&") : h, 16);
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}

function rgbToHex([r, g, b]: [number, number, number]): string {
  return "#" + [r, g, b].map((c) => Math.round(clamp01(c) * 255).toString(16).padStart(2, "0")).join("");
}

function hexToOklch(hex: string): Lch {
  const [r, g, b] = hexToRgb(hex).map(toLinear);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
  const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
  const B = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
  return [L, Math.hypot(A, B), (Math.atan2(B, A) * 180) / Math.PI];
}

function oklchToHex([L, C, H]: Lch): string {
  const a = C * Math.cos((H * Math.PI) / 180);
  const b = C * Math.sin((H * Math.PI) / 180);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s;
  const g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s;
  const bl = -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s;
  return rgbToHex([toGamma(r), toGamma(g), toGamma(bl)]);
}

// Mix two colors in OKLCH, t = 0 -> a, t = 1 -> b, hue along the shorter arc.
export function mixOklch(a: string, b: string, t: number): string {
  const [l1, c1, h1raw] = hexToOklch(a);
  const [l2, c2, h2raw] = hexToOklch(b);
  // A gray/white/black has no real hue: keep the other color's hue so mixing toward gray never drifts to blue.
  const NEUTRAL = 0.03;
  const h1 = c1 < NEUTRAL ? h2raw : h1raw;
  const h2 = c2 < NEUTRAL ? h1raw : h2raw;
  let dh = h2 - h1;
  if (dh > 180) dh -= 360;
  if (dh < -180) dh += 360;
  const k = clamp01(t);
  return oklchToHex([l1 + (l2 - l1) * k, c1 + (c2 - c1) * k, h1 + dh * k]);
}

// A color ramp through stops [[position 0..1, hex], ...] sorted by position.
export function ramp(stops: [number, string][], x: number): string {
  if (x <= stops[0][0]) return stops[0][1];
  for (let i = 1; i < stops.length; i++) {
    const [p1, c1] = stops[i - 1];
    const [p2, c2] = stops[i];
    if (x <= p2) return mixOklch(c1, c2, (x - p1) / (p2 - p1 || 1));
  }
  return stops[stops.length - 1][1];
}
