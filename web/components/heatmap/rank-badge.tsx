"use client";

import { useId } from "react";

import { mixOklch } from "@/lib/color";
import type { Rank } from "@/lib/ranks";

// The graphic for a rank: a flexing Brodie on a shield, tinted the tier color. The bicep and limbs grow with the tier,
// so the ladder reads as Brodie getting more jacked. The top tier (god form) is white with a gold crown and aura.
export function RankBadge({ rank, className }: { rank: Rank; className?: string }) {
  const gid = "rb" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const i = rank.tier; // 1..8
  const bulge = 8 + i * 1.6; // bicep radius grows with jackedness
  const armW = 9 + i * 1.1; // limb thickness
  const god = rank.tier === RANKS_TOP;
  const light = mixOklch(rank.color, "#ffffff", 0.28);
  const dark = mixOklch(rank.color, "#000000", 0.34);
  const GOLD = "#facc15";

  return (
    <svg viewBox="0 0 100 124" className={className} role="img" aria-label={`${rank.name} badge`} preserveAspectRatio="xMidYMid meet">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={light} />
          <stop offset="1" stopColor={dark} />
        </linearGradient>
      </defs>

      {god ? (
        <g opacity="0.9">
          <circle cx="50" cy="60" r="42" fill="none" stroke={GOLD} strokeWidth="1.4" opacity="0.5" />
          {Array.from({ length: 12 }, (_, k) => {
            const a = (k * 30 * Math.PI) / 180;
            return (
              <line
                key={k}
                x1={(50 + Math.cos(a) * 44).toFixed(1)}
                y1={(60 + Math.sin(a) * 44).toFixed(1)}
                x2={(50 + Math.cos(a) * 52).toFixed(1)}
                y2={(60 + Math.sin(a) * 52).toFixed(1)}
                stroke={GOLD}
                strokeWidth="1.6"
                opacity="0.6"
              />
            );
          })}
        </g>
      ) : null}

      {/* shield */}
      <path d="M50 8 L86 20 V60 C86 90 68 108 50 116 C32 108 14 90 14 60 V20 Z" fill="#0f1013" stroke={`url(#${gid})`} strokeWidth="2.4" />
      <path d="M50 8 L86 20 V60 C86 90 68 108 50 116 C32 108 14 90 14 60 V20 Z" fill={`url(#${gid})`} opacity={god ? 0.14 : 0.1} />

      {god ? <path d="M38 20 L44 28 L50 18 L56 28 L62 20 L60 33 L40 33 Z" fill={GOLD} stroke={dark} strokeWidth="1" /> : null}

      {/* flexing arm: upper arm + bicep bulge + forearm + fist */}
      <g stroke={dark} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round">
        <rect x="26" y={72 - armW / 2} width="34" height={armW} rx={armW / 2} fill={`url(#${gid})`} />
        <circle cx="56" cy="70" r={bulge} fill={`url(#${gid})`} />
        <rect x={60 - armW / 2} y="42" width={armW} height="34" rx={armW / 2} fill={`url(#${gid})`} />
        <rect x={60 - armW / 2 - 1} y="34" width={armW + 2} height="12" rx="4" fill={`url(#${gid})`} />
      </g>
    </svg>
  );
}

const RANKS_TOP = 8;
