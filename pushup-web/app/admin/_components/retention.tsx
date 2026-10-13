import { BarChart, Kpi, Legend, ShareBars, n } from "./charts";
import { Mono, Section, Table, Time } from "./ui";
import { SMALL_N, formatFrac, type Frac, type RetentionCell, type RetentionView } from "../_lib/metrics";

/** A rate with its n; tiny bases are greyed out and titled so nobody over-reads "100%" of one person. */
function Rate({ f, partial }: { f: Frac; partial?: boolean }) {
  if (f.den === 0) return <span className="text-ink-2">-</span>;
  const small = f.den < SMALL_N;
  return (
    <span
      className={`tabular-nums whitespace-nowrap ${small ? "text-ink-2" : "font-semibold"}`}
      title={small ? `Small sample: only ${f.den} ${f.den === 1 ? "person" : "people"}` : undefined}
    >
      {formatFrac(f)}
      {partial ? <span className="text-ink-2"> so far</span> : null}
    </span>
  );
}

function Cell({ c }: { c: RetentionCell }) {
  if (c.state === "na") return <span className="text-ink-2" title="This day hasn't happened yet">not yet</span>;
  return (
    <>
      <Rate f={c.called} partial={c.state === "partial"} />
      <span className="block text-[10px] text-ink-2 tabular-nums">active {formatFrac(c.active)}</span>
    </>
  );
}

function Pooled({ label, f, hint }: { label: string; f: Frac; hint: string }) {
  return (
    <Kpi
      label={label}
      value={f.den > 0 && f.pct != null ? `${Math.round(f.pct * 100)}%` : "-"}
      hint={f.den > 0 ? `${n(f.num)} of ${n(f.den)} · ${hint}` : hint}
    />
  );
}

export function RetentionSection({ view }: { view: RetentionView }) {
  const { pooled, engaged } = view;
  return (
    <Section title="Retention" aside="from our own calls and texts; ET days">
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Pooled label="Came back (ever)" f={pooled.returned} hint="called on a later day" />
        <Pooled label="D1 return" f={pooled.d1} hint="called the next day" />
        <Pooled label="D3 return" f={pooled.d3} hint="called on day 3" />
        <Pooled label="D7 return" f={pooled.d7} hint="called on day 7" />
      </dl>
      <p className="mt-2 text-[11px] text-ink-2">
        Dk = called on exactly the k-th ET day after joining (pooled over cohorts whose day k is over). &ldquo;Active&rdquo;
        also counts a text to Brodie. Grey = fewer than {SMALL_N} people. FaceTime attempts that never connect (busy
        line) leave no record, so they are not counted anywhere.
      </p>

      <h3 className="mt-4 mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Cohorts by join day</h3>
      <Table head={["Joined", "n", "Came back", "D1", "D3", "D7"]} empty={!view.cohorts.length}>
        {view.cohorts.map((c) => (
          <tr key={c.key}>
            <td className="whitespace-nowrap font-semibold">{c.label}</td>
            <td className="tabular-nums">{n(c.n)}</td>
            <td><Rate f={c.returned} /></td>
            <td><Cell c={c.d1} /></td>
            <td><Cell c={c.d3} /></td>
            <td><Cell c={c.d7} /></td>
          </tr>
        ))}
      </Table>

      <div className="mt-4 grid gap-6 lg:grid-cols-2">
        <div>
          <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-bold uppercase tracking-widest text-ink-2">Callers per day (ET)</h3>
            <Legend
              items={[
                { label: "returning", className: "bg-accent" },
                { label: "first-time", className: "bg-pink" },
              ]}
            />
          </div>
          <BarChart data={view.callersDaily} label="Callers per day" unit=" callers" unit2=" returning" />
        </div>
        <div>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Calls per player</h3>
          <ShareBars rows={view.callsPerUser} />
        </div>
        <div>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Current streak</h3>
          <ShareBars rows={view.streaks} />
        </div>
        <div>
          <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Days with a scoring call</h3>
          <ShareBars rows={view.qualifiedDays} />
        </div>
      </div>

      <h3 className="mt-4 mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">
        Engaged but not calling: {n(engaged.n)}
      </h3>
      <p className="mb-2 text-[11px] text-ink-2">Texted Brodie in the last 24 h but had no connected call in that time.</p>
      <Table head={["Player", "Last text"]} empty={!engaged.users.length}>
        {engaged.users.map((u) => (
          <tr key={u.userId}>
            <td>
              <p className="font-semibold">{u.name}</p>
              <Mono>{u.userId}</Mono>
            </td>
            <td><Time at={u.lastTextAt} /></td>
          </tr>
        ))}
      </Table>
    </Section>
  );
}
