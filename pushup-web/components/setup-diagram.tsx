/** Side-view setup illustration: lamp in front, athlete, phone in landscape 6-8 ft to the side, field of view. */
export function SetupDiagram() {
  const ink = "#f6f6f3";
  const accent = "#d4ff3a";
  const dim = "#8e8e88";
  const limb = { stroke: ink, strokeWidth: 7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, fill: "none" };
  return (
    <figure className="card overflow-hidden">
      <svg
        viewBox="0 0 360 200"
        role="img"
        aria-label="Side view: phone on the floor 6 to 8 feet to your side, in landscape, filming you head to feet, with light in front of you"
        className="w-full"
      >
        <defs>
          <linearGradient id="fov" x1="1" y1="0" x2="0" y2="0">
            <stop offset="0" stopColor={accent} stopOpacity="0.35" />
            <stop offset="1" stopColor={accent} stopOpacity="0.03" />
          </linearGradient>
          <radialGradient id="lamp" cx="0.5" cy="0.5" r="0.5">
            <stop offset="0" stopColor="#fff6c8" stopOpacity="0.55" />
            <stop offset="1" stopColor="#fff6c8" stopOpacity="0" />
          </radialGradient>
        </defs>
        {/* field of view */}
        <path d="M300 152 L18 92 L18 160 Z" fill="url(#fov)" />
        <path d="M300 152 L18 92 M300 152 L18 160" stroke={accent} strokeWidth="1.5" strokeDasharray="5 4" />
        {/* lamp */}
        <circle cx="38" cy="34" r="34" fill="url(#lamp)" />
        <circle cx="38" cy="34" r="9" fill="#fff6c8" />
        <text x="58" y="30" fontSize="11" fontWeight="700" fill={ink}>LIGHT IN FRONT</text>
        <text x="58" y="44" fontSize="10" fill={dim}>never a window behind you</text>
        {/* floor */}
        <line x1="8" y1="160" x2="352" y2="160" stroke="rgb(255 255 255 / 0.2)" strokeWidth="2" />
        {/* athlete in plank */}
        <path d="M62 124 L180 151" {...limb} />
        <path d="M180 151 L214 158" {...limb} />
        <path d="M62 124 L64 160" {...limb} strokeWidth={6} />
        <circle cx="46" cy="118" r="10" fill={ink} />
        {/* phone, landscape, on the floor */}
        <g transform="translate(300 140)">
          <rect x="0" y="0" width="40" height="20" rx="4" fill={accent} />
          <rect x="4" y="4" width="32" height="12" rx="2" fill="#0a0b05" />
          <circle cx="7" cy="10" r="2" fill={accent} />
        </g>
        <text x="320" y="128" textAnchor="middle" fontSize="11" fontWeight="700" fill={accent}>PHONE</text>
        <text x="320" y="116" textAnchor="middle" fontSize="10" fill={dim}>landscape</text>
        {/* distance */}
        <path d="M214 180 L300 180" stroke={ink} strokeWidth="1.5" />
        <path d="M214 175 v10 M300 175 v10" stroke={ink} strokeWidth="1.5" />
        <text x="257" y="196" textAnchor="middle" fontSize="12" fontWeight="700" fill={ink}>6–8 FT TO YOUR SIDE</text>
      </svg>
    </figure>
  );
}
