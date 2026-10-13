import type { SessionView } from "@/lib/contract";
import { muscleBalance } from "@/lib/quality";

// The heat map in one line: a thin 3-color bar and "6 solid · 3 okay · 2 work on".
export function MuscleBalance({ view, className = "" }: { view: SessionView; className?: string }) {
  const { good, warn, bad, caption } = muscleBalance(view);
  const total = good + warn + bad;
  return (
    <div className={className}>
      {total ? (
        <div className="flex h-1.5 overflow-hidden rounded-full bg-sunken" aria-hidden>
          <span className="bg-good" style={{ width: `${(good / total) * 100}%` }} />
          <span className="bg-warn" style={{ width: `${(warn / total) * 100}%` }} />
          <span className="bg-bad" style={{ width: `${(bad / total) * 100}%` }} />
        </div>
      ) : null}
      <p className="mt-2 text-[12.5px] font-medium text-ink-2">{caption}</p>
    </div>
  );
}
