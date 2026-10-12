function Frame({ title, ok, children }: { title: string; ok: boolean; children: React.ReactNode }) {
  return (
    <figure className="rounded-xl border border-hairline bg-surface p-3">
      <svg viewBox="0 0 200 100" role="img" aria-label={title} className="w-full">
        <line x1="5" y1="85" x2="195" y2="85" stroke="#555" strokeWidth="2" />
        {children}
      </svg>
      <figcaption className={`mt-1 text-sm font-semibold ${ok ? "text-accent" : "text-bad"}`}>
        {ok ? "Counts: " : "Does not count: "}
        {title}
      </figcaption>
    </figure>
  );
}

const body = { stroke: "#f5f5f4", strokeWidth: 5, strokeLinecap: "round" as const, fill: "none" };

export function RepIllustrations() {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Frame title="straight line, chest down, full lockout" ok>
        <circle cx="35" cy="48" r="7" fill="#f5f5f4" />
        <path d="M45 56 L150 78" {...body} />
        <path d="M150 78 L175 83" {...body} />
        <path d="M60 60 L60 82" {...body} />
        <path d="M60 82 L72 82" {...body} />
      </Frame>
      <Frame title="arms fully locked at the top" ok>
        <circle cx="35" cy="30" r="7" fill="#f5f5f4" />
        <path d="M45 38 L150 70" {...body} />
        <path d="M150 70 L175 83" {...body} />
        <path d="M62 43 L62 82" {...body} />
      </Frame>
      <Frame title="knees on the floor" ok={false}>
        <circle cx="35" cy="42" r="7" fill="#f5f5f4" />
        <path d="M45 50 L125 72" {...body} />
        <path d="M125 72 L150 82 L175 82" {...body} />
        <path d="M60 55 L60 82" {...body} />
      </Frame>
      <Frame title="hips sagging" ok={false}>
        <circle cx="35" cy="38" r="7" fill="#f5f5f4" />
        <path d="M45 46 L110 76 L175 70" {...body} />
        <path d="M60 52 L60 82" {...body} />
      </Frame>
      <Frame title="hips piked up" ok={false}>
        <circle cx="35" cy="55" r="7" fill="#f5f5f4" />
        <path d="M45 62 L105 28 L175 82" {...body} />
        <path d="M60 58 L60 82" {...body} />
      </Frame>
      <Frame title="half rep, chest stays high" ok={false}>
        <circle cx="35" cy="34" r="7" fill="#f5f5f4" />
        <path d="M45 42 L150 70 L175 83" {...body} />
        <path d="M60 47 L70 66 L62 82" {...body} />
      </Frame>
    </div>
  );
}
