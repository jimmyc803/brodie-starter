import * as React from "react";
import type { JSX } from "react";
import { avatarParts } from "./parts";

export { avatarParts } from "./parts";

export function Avatar({
  level,
  size = 96,
  accent = "#D4FF3A",
  pose = "flex",
}: {
  level: number;
  size?: number;
  accent?: string;
  pose?: "flex" | "idle";
}): JSX.Element {
  const parts = avatarParts(level);
  const chestWidth = 17 * parts.chest;
  const chestDepth = 13 * parts.chest;
  const armWidth = 8 * parts.triceps;
  const shoulderWidth = 10 * parts.delts;
  const coreWidth = 13 * parts.core;
  const coreDepth = 22 * parts.core;
  const skin = "#D59670";
  const highlight = "#F0B58B";
  const outline = "#292335";

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox="0 0 200 200"
      role="img"
      aria-label={`Brodie athlete, ${pose} pose`}
      fill="none"
      stroke={outline}
      strokeWidth={3}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <ellipse cx={100} cy={186} rx={48} ry={5} fill="#343444" stroke="none" />
      <g data-part="legs" fill={skin}>
        <path d="M 78 147 L 96 147 L 94 177 L 79 177 Z" />
        <path d="M 104 147 L 122 147 L 121 177 L 106 177 Z" />
        <path d="M 79 173 L 94 173 L 95 184 L 70 184 Q 67 177 79 173 Z" fill="#F3EFE5" />
        <path d="M 106 173 L 121 173 Q 133 177 130 184 L 105 184 Z" fill="#F3EFE5" />
      </g>
      <path data-part="torso" d="M 79 78 Q 100 70 121 78 L 120 134 L 80 134 Z" fill={skin} />
      {([-1, 1] as const).map((side) => (
        <g key={side} transform={`translate(100 0) scale(${side} 1)`}>
          <g transform={pose === "idle" ? "rotate(65 30 86)" : undefined}>
            <path data-part="forearms" d="M 47 94 Q 60 88 60 69 L 59 58 Q 53 52 48 59 L 46 78 L 39 84 Z" fill={skin} />
            <path
              data-muscle="triceps"
              d={`M 29 80 Q 39 ${78 - armWidth} 50 82 Q ${53 + armWidth} ${88 + armWidth} 43 ${94 + armWidth} Q ${30 - armWidth} 106 29 80 Z`}
              fill={skin}
            />
            <path d="M 49 64 L 59 66 L 59 73 L 48 71 Z" fill={accent} />
          </g>
          <path
            data-muscle="delts"
            d={`M 22 77 Q 31 ${77 - shoulderWidth} ${32 + shoulderWidth} 81 Q ${36 + shoulderWidth} 99 26 99 Q 20 91 22 77 Z`}
            fill={highlight}
          />
        </g>
      ))}
      <path
        data-muscle="core"
        d={`M ${100 - coreWidth} 105 Q 100 101 ${100 + coreWidth} 105 L ${100 + coreWidth - 2} ${105 + coreDepth} Q 100 ${110 + coreDepth} ${102 - coreWidth} ${105 + coreDepth} Z`}
        fill={highlight}
      />
      <path d="M 100 109 L 100 131 M 93 116 L 107 116 M 94 124 L 106 124" stroke="#A56851" strokeWidth={2} />
      {([-1, 1] as const).map((side) => (
        <g key={side} transform={`translate(100 0) scale(${side} 1)`}>
          <path
            data-muscle="chest"
            d={`M 2 81 Q ${chestWidth} 73 ${chestWidth + 3} 87 Q ${chestWidth + 7} ${89 + chestDepth} 5 ${88 + chestDepth} Q 0 ${88 + chestDepth} 2 81 Z`}
            fill={highlight}
          />
        </g>
      ))}
      <g data-part="shorts">
        <path d="M 80 134 L 120 134 L 124 156 L 104 156 L 100 146 L 96 156 L 76 156 Z" fill="#44445C" />
        <path d="M 81 135 L 119 135" stroke={accent} strokeWidth={5} />
      </g>
      <g data-part="head">
        <path d="M 91 66 L 91 79 Q 100 85 109 79 L 109 66" fill={skin} />
        <path d="M 78 43 Q 71 40 73 51 Q 74 57 80 56 M 122 43 Q 129 40 127 51 Q 126 57 120 56" fill={skin} />
        <path d="M 79 33 Q 80 16 100 17 Q 120 16 121 33 L 120 55 Q 118 72 100 75 Q 82 72 80 55 Z" fill={highlight} />
        <path d="M 79 32 Q 76 17 88 16 L 94 11 L 99 16 Q 117 10 121 27 L 119 35 L 110 26 Q 94 34 79 32 Z" fill="#493746" />
        <path d="M 79 32 Q 100 37 121 32 L 121 41 Q 100 46 79 41 Z" fill={accent} />
        <path d="M 87 50 L 91 50 M 109 50 L 113 50" />
        <path d="M 100 51 L 98 57 L 102 57" stroke="#A56851" strokeWidth={2} />
        <path d="M 92 62 Q 100 69 108 62" strokeWidth={2} />
      </g>
    </svg>
  );
}
