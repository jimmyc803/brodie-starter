type P = { className?: string };
const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2.25,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const BoltIcon = ({ className }: P) => (
  <svg {...base} className={className} fill="currentColor" stroke="none">
    <path d="M13.5 2 4 13.5h6.5L9.5 22 20 9.5h-6.5L13.5 2Z" />
  </svg>
);
export const FlameIcon = ({ className }: P) => (
  <svg {...base} className={className} fill="currentColor" stroke="none">
    <path d="M12 2c.6 3.2-1.4 4.9-2.9 6.6C7.6 10.3 6 12 6 14.8 6 18.8 8.8 22 12 22s6-3 6-7c0-2.6-1.2-4.4-2.4-5.6-.2 1.6-.9 2.8-2.1 3.3.5-3.6-.3-7.6-1.5-10.7Z" />
  </svg>
);
export const ArrowUpIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M12 19V5M5 12l7-7 7 7" />
  </svg>
);
export const ArrowDownIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M12 5v14M19 12l-7 7-7-7" />
  </svg>
);
export const ArrowRightIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M5 12h14M12 5l7 7-7 7" />
  </svg>
);
export const MessageIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 9.4 9.4 0 0 1-3.6-.7L3 21l1.6-4.6A8 8 0 0 1 3 11.5 8.6 8.6 0 0 1 12 3a8.6 8.6 0 0 1 9 8.5Z" />
  </svg>
);
export const SearchIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </svg>
);
export const CheckIcon = ({ className }: P) => (
  <svg {...base} className={className} strokeWidth={3}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </svg>
);
export const XIcon = ({ className }: P) => (
  <svg {...base} className={className} strokeWidth={3}>
    <path d="M6 6l12 12M18 6 6 18" />
  </svg>
);
export const CrownIcon = ({ className }: P) => (
  <svg {...base} className={className} fill="currentColor" stroke="none">
    <path d="M3 7.5 7.5 11 12 4l4.5 7L21 7.5 19 18H5L3 7.5ZM5 20h14v1.5H5z" />
  </svg>
);
export const PhoneIcon = ({ className }: P) => (
  <svg {...base} className={className}>
    <rect x="6" y="2.5" width="12" height="19" rx="2.5" />
    <path d="M10.5 18.5h3" />
  </svg>
);
