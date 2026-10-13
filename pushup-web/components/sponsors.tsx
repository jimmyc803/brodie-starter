import Image from "next/image";
import chert from "@/assets/sponsor-chert.png";
import seraphim from "@/assets/sponsor-seraphim.png";

/** Y Combinator mark, drawn as SVG so it stays crisp at any size. */
function YcLogo({ className = "" }: { className?: string }) {
  return (
    <svg viewBox="0 0 48 48" role="img" aria-label="Y Combinator" className={className}>
      <rect width="48" height="48" fill="#ff6600" />
      <path d="M15 12.5h4.6l4.4 9.2 4.4-9.2H33l-6.8 13.1v9.9h-4.4v-9.9z" fill="#fff" />
    </svg>
  );
}

/** "Sponsored by" panel: Chert (backed by Y Combinator) and Seraphim Labs. */
export function Sponsors() {
  return (
    <section aria-labelledby="sponsors" className="space-y-5">
      <h2 id="sponsors" className="font-display text-4xl uppercase sm:text-5xl">
        Sponsored by
      </h2>
      <ul className="grid gap-4 md:grid-cols-2">
        <li className="card flex flex-col items-start gap-5 p-5 sm:flex-row sm:items-center sm:gap-7 sm:p-7">
          <Image
            src={chert}
            alt="Chert logo"
            width={144}
            height={144}
            className="size-24 shrink-0 border-2 border-ink bg-white sm:size-36"
          />
          <div className="min-w-0 space-y-3">
            <p className="font-display text-5xl leading-none uppercase sm:text-7xl">Chert</p>
            <p className="inline-flex items-center gap-3 border-2 border-ink bg-canvas px-3 py-2 font-mono text-xs font-bold tracking-wide uppercase sm:text-base">
              <YcLogo className="size-8 shrink-0 sm:size-11" />
              Backed by Y&nbsp;Combinator
            </p>
          </div>
        </li>
        <li className="card flex flex-col items-start gap-5 p-5 sm:flex-row sm:items-center sm:gap-7 sm:p-7">
          <Image
            src={seraphim}
            alt="Seraphim Labs logo"
            width={144}
            height={144}
            className="size-24 shrink-0 border-2 border-ink sm:size-36"
          />
          <p className="min-w-0 font-display text-5xl leading-none uppercase sm:text-7xl">
            Seraphim <span className="text-accent">Labs</span>
          </p>
        </li>
      </ul>
    </section>
  );
}
