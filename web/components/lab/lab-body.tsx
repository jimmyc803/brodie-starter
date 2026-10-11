import { SHAPES, VIEWBOX, type BodySide } from "@/lib/body/shapes";
import { BODY_BASE, BODY_STROKE } from "@/lib/body/svg";
import { mixOklch } from "@/lib/color";
import type { Fills } from "@/lib/body/variants";

// One body side for the design lab. "glow" adds a radial gradient per muscle (lit from inside) and a blurred halo
// behind the colored muscles, strength per muscle from fills[m].glow.
export function LabBody({
  side,
  fills,
  glow = false,
  id,
  className,
}: {
  side: BodySide;
  fills: Fills;
  glow?: boolean;
  id: string; // unique per rendered body, for SVG gradient/filter ids
  className?: string;
}) {
  const shapes = SHAPES[side];
  return (
    <svg viewBox={`-6 -6 ${VIEWBOX.width + 12} ${VIEWBOX.height + 12}`} className={className} role="img" aria-label={`${side} body`}>
      {glow ? (
        <defs>
          <filter id={`${id}-halo`} x="-30%" y="-30%" width="160%" height="160%">
            <feGaussianBlur stdDeviation="3" />
          </filter>
          {shapes.map((s, i) => {
            const f = s.muscle ? fills[s.muscle] : undefined;
            if (!f || !f.glow) return null;
            return (
              <radialGradient key={i} id={`${id}-g${i}`} cx="50%" cy="45%" r="65%">
                <stop offset="0%" stopColor={mixOklch(f.fill, "#ffffff", 0.35 * f.glow)} />
                <stop offset="100%" stopColor={mixOklch(f.fill, "#000000", 0.25)} />
              </radialGradient>
            );
          })}
        </defs>
      ) : null}
      {glow ? (
        <g filter={`url(#${id}-halo)`}>
          {shapes.map((s, i) => {
            const f = s.muscle ? fills[s.muscle] : undefined;
            return f && f.glow ? <polygon key={i} points={s.points} fill={f.fill} opacity={0.75 * f.glow} /> : null;
          })}
        </g>
      ) : null}
      {shapes.map((s, i) => {
        const f = s.muscle ? fills[s.muscle] : undefined;
        const fill = !f ? BODY_BASE : glow && f.glow ? `url(#${id}-g${i})` : f.fill;
        return <polygon key={i} points={s.points} fill={fill} stroke={BODY_STROKE} strokeWidth={0.5} strokeLinejoin="round" />;
      })}
    </svg>
  );
}
