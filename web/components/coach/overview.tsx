import Link from "next/link";
import { Activity, ArrowRight, CalendarCheck, ClipboardCheck, Upload, Users } from "lucide-react";

import { coachLinks } from "@/components/coach/coach-shell";
import { COACH_TZ, dayKey, type CoachOverview, type DayPoint, type RecentItem } from "@/lib/coach-overview";

const pct = (x: number | null) => (x === null ? "–" : `${Math.round(x * 100)}%`);

// Coach home: the week at a glance, form over the last 7 days, the month's training calendar, shortcuts and the latest workouts.
export function Overview({ o, token, coachName, returning = true }: { o: CoachOverview; token: string; coachName: string; returning?: boolean }) {
  const now = o.now;
  const links = coachLinks(token);
  const today = new Date(now).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: COACH_TZ });
  const firstReview = o.summaries.find((s) => s.status === "review");
  return (
    <>
      <header>
        <p className="text-sm text-zinc-500">{today}</p>
        <h1 className="mt-1 text-3xl font-bold tracking-tight text-zinc-50">
          {returning ? "Welcome back" : "Your dashboard"}, Coach {coachName}
        </h1>
      </header>

      <section aria-label="This week" className="mt-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Metric icon={Users} label="Active clients" value={`${o.activeClients}`} sub={`of ${o.summaries.length}`} />
        <Metric icon={CalendarCheck} label="Workouts this week" value={`${o.sessionsThisWeek}`} />
        <Metric icon={Activity} label="Clean reps this week" value={pct(o.cleanThisWeek)} />
        <Metric icon={ClipboardCheck} label="Need review" value={`${o.needReview}`} tone={o.needReview ? "review" : undefined} />
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:items-start">
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900">
          <div className="flex items-baseline justify-between gap-3 px-5 pt-5">
            <h2 className="text-base font-semibold text-zinc-100">Form quality</h2>
            <p className="text-xs text-zinc-500">Clean reps per day · last 7 days</p>
          </div>
          <FormChart days={o.days} />
          <dl className="grid grid-cols-3 border-t border-zinc-800 text-sm">
            <Foot label="Clean reps" value={pct(o.cleanThisWeek)} />
            <Foot label="Reps completed" value={pct(o.completionThisWeek)} />
            <Foot label="Best form" value={o.bestForm ? o.bestForm.name : "–"} />
          </dl>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-base font-semibold text-zinc-100">Training calendar</h2>
          <MonthCalendar counts={o.calendar} now={now} />
          <div className="mt-4 border-t border-zinc-800 pt-4">
            <p className="text-xs text-zinc-500">Today</p>
            {o.today.length ? (
              <ul className="mt-2 space-y-2">
                {o.today.slice(0, 3).map((r) => (
                  <li key={r.token}>
                    <Link href={`${links.clients}?c=${encodeURIComponent(r.clientId)}&s=${encodeURIComponent(r.token)}#session`} className="flex items-center gap-3 text-sm hover:text-zinc-50">
                      <span className="w-16 shrink-0 tabular-nums text-zinc-500">
                        {new Date(r.at).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: COACH_TZ })}
                      </span>
                      <span className="truncate text-zinc-200">
                        {r.clientName} · {r.title}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-zinc-500">No workouts yet today.</p>
            )}
          </div>
        </section>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-base font-semibold text-zinc-100">Quick actions</h2>
          <ul className="mt-3 space-y-1">
            <Action href={links.programs} icon={Upload} title="Upload a program" sub="Turn a PDF into days Brodie can run" />
            <Action href={`${links.programs}#assign`} icon={CalendarCheck} title="Assign the next workout" sub="Pick the day a client trains on their next call" />
            <Action
              href={firstReview ? `${links.clients}?c=${encodeURIComponent(firstReview.id)}` : links.clients}
              icon={ClipboardCheck}
              title="Review flagged sets"
              sub={firstReview ? `Start with ${firstReview.name}` : "Nothing waiting right now"}
            />
          </ul>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-base font-semibold text-zinc-100">Recent workouts</h2>
            <Link href={links.clients} className="text-xs text-zinc-400 hover:text-zinc-100">
              All clients
            </Link>
          </div>
          {o.recent.length ? (
            <ul className="mt-3 divide-y divide-zinc-800">
              {o.recent.map((r) => (
                <Recent key={r.token} r={r} href={`${links.clients}?c=${encodeURIComponent(r.clientId)}&s=${encodeURIComponent(r.token)}#session`} now={now} />
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-zinc-500">No workouts yet. When a client finishes a call with Brodie it shows up here.</p>
          )}
        </section>
      </div>
    </>
  );
}

function Metric({ icon: Icon, label, value, sub, tone }: { icon: typeof Users; label: string; value: string; sub?: string; tone?: "review" }) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm text-zinc-400">{label}</p>
        <span className="grid size-8 place-items-center rounded-full bg-zinc-800">
          <Icon className="size-4 text-zinc-300" aria-hidden />
        </span>
      </div>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${tone === "review" ? "text-red-300" : "text-zinc-50"}`}>
        {value}
        {sub ? <span className="ml-1 text-sm font-normal text-zinc-500">{sub}</span> : null}
      </p>
    </div>
  );
}

function Foot({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-5 py-3 [&:not(:first-child)]:border-l [&:not(:first-child)]:border-zinc-800">
      <dt className="text-xs text-zinc-500">{label}</dt>
      <dd className="mt-0.5 truncate text-lg font-semibold text-zinc-50">{value}</dd>
    </div>
  );
}

// Clean-rep % per day as a line; days without a workout leave a gap (no fake zero).
function FormChart({ days }: { days: DayPoint[] }) {
  const W = 600, H = 200, PX = 36, PT = 16, PB = 28;
  const x = (i: number) => PX + (i * (W - PX - 12)) / Math.max(1, days.length - 1);
  const y = (v: number) => PT + (1 - v) * (H - PT - PB);
  const segments: string[] = [];
  let cur: string[] = [];
  days.forEach((d, i) => {
    if (d.clean === null) {
      if (cur.length) segments.push(cur.join(" "));
      cur = [];
    } else cur.push(`${cur.length ? "L" : "M"}${x(i).toFixed(1)},${y(d.clean).toFixed(1)}`);
  });
  if (cur.length) segments.push(cur.join(" "));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 h-52 w-full" role="img" aria-label="Clean reps per day for the last 7 days">
      {[0, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line x1={PX} x2={W - 12} y1={y(v)} y2={y(v)} stroke="#27272a" strokeDasharray={v === 0 ? undefined : "3 4"} />
          <text x={PX - 8} y={y(v) + 4} textAnchor="end" fontSize="11" fill="#71717a">
            {Math.round(v * 100)}%
          </text>
        </g>
      ))}
      {segments.map((d, i) => (
        <path key={i} d={d} fill="none" stroke="#22c55e" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {days.map((d, i) => (
        <g key={d.key}>
          {d.clean !== null ? (
            <circle cx={x(i)} cy={y(d.clean)} r="4.5" fill="#09090b" stroke="#22c55e" strokeWidth="2.5">
              <title>{`${d.key}: ${Math.round(d.clean * 100)}% clean · ${d.sessions} workout${d.sessions === 1 ? "" : "s"}`}</title>
            </circle>
          ) : null}
          <text x={x(i)} y={H - 8} textAnchor="middle" fontSize="11" fill="#71717a">
            {d.label}
          </text>
        </g>
      ))}
    </svg>
  );
}

function MonthCalendar({ counts, now }: { counts: Record<string, number>; now: number }) {
  const todayKey = dayKey(now);
  const [y, m] = todayKey.split("-").map(Number);
  const first = new Date(Date.UTC(y, m - 1, 1));
  const daysIn = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const lead = first.getUTCDay();
  const month = first.toLocaleDateString("en-US", { month: "long", year: "numeric", timeZone: "UTC" });
  const cells: (number | null)[] = [...Array(lead).fill(null), ...Array.from({ length: daysIn }, (_, i) => i + 1)];
  return (
    <div className="mt-3">
      <p className="text-center text-sm font-medium text-zinc-300">{month}</p>
      <div className="mt-3 grid grid-cols-7 gap-y-1 text-center text-xs">
        {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => (
          <span key={i} className="pb-1 text-zinc-500">
            {d}
          </span>
        ))}
        {cells.map((d, i) => {
          if (d === null) return <span key={i} />;
          const key = `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
          const n = counts[key] ?? 0;
          const isToday = key === todayKey;
          return (
            <span key={i} className="flex flex-col items-center" title={n ? `${n} workout${n === 1 ? "" : "s"}` : undefined}>
              <span
                className={`grid size-7 place-items-center rounded-full tabular-nums ${
                  isToday ? "bg-zinc-50 font-semibold text-zinc-950" : n ? "text-zinc-100" : "text-zinc-500"
                }`}
              >
                {d}
              </span>
              <span className={`mt-0.5 size-1 rounded-full ${n ? "bg-green-500" : "bg-transparent"}`} />
            </span>
          );
        })}
      </div>
    </div>
  );
}

function Action({ href, icon: Icon, title, sub }: { href: string; icon: typeof Users; title: string; sub: string }) {
  return (
    <li>
      <Link href={href} className="group flex items-center gap-3 rounded-xl px-2 py-2.5 transition-colors hover:bg-zinc-800/60">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-zinc-800">
          <Icon className="size-4 text-zinc-200" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-zinc-100">{title}</span>
          <span className="block truncate text-xs text-zinc-500">{sub}</span>
        </span>
        <ArrowRight className="size-4 text-zinc-600 transition-colors group-hover:text-zinc-300" aria-hidden />
      </Link>
    </li>
  );
}

function Recent({ r, href, now }: { r: RecentItem; href: string; now: number }) {
  const mins = Math.max(0, Math.round((now - r.at) / 60000));
  const ago = mins < 60 ? `${mins}m` : mins < 1440 ? `${Math.round(mins / 60)}h` : `${Math.round(mins / 1440)}d`;
  const dot = r.tone === "review" ? "#ef4444" : r.tone === "good" ? "#22c55e" : "#52525b";
  return (
    <li>
      <Link href={href} className="flex items-center gap-3 py-2.5 transition-colors hover:text-zinc-50">
        <span className="grid size-9 shrink-0 place-items-center rounded-full bg-zinc-800 text-sm font-medium text-zinc-200">
          {r.clientName.charAt(0).toUpperCase()}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm text-zinc-100">
            <span className="font-medium">{r.clientName}</span> <span className="text-zinc-400">finished {r.title}</span>
          </span>
          <span className="flex items-center gap-1.5 text-xs text-zinc-500">
            <span className="size-1.5 rounded-full" style={{ background: dot }} aria-hidden />
            {r.detail}
          </span>
        </span>
        <span className="shrink-0 text-xs tabular-nums text-zinc-500">{ago}</span>
      </Link>
    </li>
  );
}
