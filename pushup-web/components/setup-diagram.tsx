export function SetupDiagram() {
  return (
    <figure className="rounded-xl border border-hairline bg-surface p-3">
      <svg
        viewBox="0 0 320 150"
        role="img"
        aria-label="Side view: phone on the floor 6 to 8 feet to the side, landscape, filming you head to feet"
        className="w-full"
      >
        <line x1="10" y1="120" x2="310" y2="120" stroke="#555" strokeWidth="2" />
        {/* person */}
        <circle cx="45" cy="86" r="8" fill="#f5f5f4" />
        <path d="M56 94 L140 112" stroke="#f5f5f4" strokeWidth="6" strokeLinecap="round" fill="none" />
        <path d="M140 112 L165 119" stroke="#f5f5f4" strokeWidth="6" strokeLinecap="round" fill="none" />
        <path d="M70 98 L70 119" stroke="#f5f5f4" strokeWidth="6" strokeLinecap="round" fill="none" />
        {/* phone, landscape */}
        <rect x="262" y="104" width="30" height="15" rx="3" fill="#d4ff3a" />
        <line x1="262" y1="111" x2="170" y2="100" stroke="#d4ff3a" strokeWidth="1.5" strokeDasharray="4 3" />
        <line x1="262" y1="111" x2="30" y2="80" stroke="#d4ff3a" strokeWidth="1.5" strokeDasharray="4 3" />
        {/* distance */}
        <line x1="165" y1="136" x2="262" y2="136" stroke="#b4b4b0" strokeWidth="1.5" />
        <text x="213" y="132" textAnchor="middle" fontSize="11" fill="#b4b4b0">
          6–8 ft
        </text>
        <text x="277" y="98" textAnchor="middle" fontSize="10" fill="#d4ff3a">
          phone (landscape)
        </text>
        {/* light */}
        <circle cx="30" cy="20" r="9" fill="#d4ff3a" />
        <text x="46" y="24" fontSize="10" fill="#b4b4b0">
          light in front, not behind you
        </text>
      </svg>
      <figcaption className="mt-1 text-sm text-ink-2">
        Phone on the floor, to your side, tilted to see you from head to feet.
      </figcaption>
    </figure>
  );
}
