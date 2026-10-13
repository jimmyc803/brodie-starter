import Link from "next/link";
import { requireAdmin } from "@/lib/admin";
import { BarChart, Funnel, Kpi, Legend, LineChart, ShareBars, n } from "../../_components/charts";
import { Mono, Section, Show, Table, Time } from "../../_components/ui";
import { RetentionSection } from "../../_components/retention";
import { getMetrics, getRetention, load } from "../../_lib/data";
import { formatPct, shapeMetrics, shapeRetention } from "../../_lib/metrics";

export const dynamic = "force-dynamic";

function TeamToggle({ includeTeam, teamAccounts }: { includeTeam: boolean; teamAccounts: number }) {
  const opt = (on: boolean, label: string) => (
    <Link
      href={on ? "/admin/metrics?team=1" : "/admin/metrics"}
      aria-current={includeTeam === on ? "page" : undefined}
      className={`rounded px-2 py-1 font-semibold ${includeTeam === on ? "bg-accent text-on-accent" : "text-ink-2 hover:text-accent"}`}
    >
      {label}
    </Link>
  );
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <span className="inline-flex rounded-md border border-hairline p-0.5">
        {opt(false, "Players only")}
        {opt(true, "Include team")}
      </span>
      <span className="text-ink-2">
        {n(teamAccounts)} team account{teamAccounts === 1 ? "" : "s"}; mark them on{" "}
        <Link href="/admin/users" className="font-semibold text-accent hover:underline">
          Users
        </Link>
        .
      </span>
    </div>
  );
}

export default async function AdminMetricsPage({ searchParams }: { searchParams: Promise<{ team?: string | string[] }> }) {
  await requireAdmin();
  const sp = await searchParams;
  const includeTeam = sp.team === "1";
  const [raw, retention] = await Promise.all([
    load("metrics", () => getMetrics(includeTeam)),
    load("retention", () => getRetention(includeTeam)),
  ]);

  return (
    <>
      <Show loaded={raw}>
        {(data) => {
          // Shape against the instant the RPC computed for, so hour buckets line up with its data.
          const m = shapeMetrics(data, Date.parse(data.generated_at));
          const k = m.kpis;
          const v = m.virality;
          return (
            <>
              <Section
                title="Growth"
                aside={
                  <>
                    as of <Time at={m.generatedAt} /> · reload for fresh numbers
                  </>
                }
              >
                <TeamToggle includeTeam={m.includeTeam} teamAccounts={m.teamAccounts} />
                <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                  <Kpi label="Joined" value={n(k.joined)} hint={`+${n(k.joinedToday)} today (ET)`} tone="accent" />
                  <Kpi label="Called" value={n(k.calledUsers)} hint={`${formatPct(k.joinToCall)} of joined`} />
                  <Kpi label="Called today" value={n(k.dauToday)} hint="players with a call (ET day)" />
                  <Kpi label="Valid reps" value={n(k.validReps)} hint={`${n(k.scoredUsers)} players scored`} />
                  <Kpi
                    label="Calls connected"
                    value={n(k.callsConnected)}
                    hint={`${n(k.callsAccepted)} accepted · ${n(k.callsCounted)} counted`}
                  />
                  <Kpi label="Referred signups" value={n(v.referred)} hint={`${formatPct(v.referredShare)} of signups`} />
                  <Kpi
                    label="K-factor"
                    value={v.kFactor == null ? "-" : v.kFactor.toFixed(2)}
                    hint="referred signups per player"
                  />
                  <Kpi label="Pending joins" value={n(k.pendingJoins)} hint="texted JOIN, no YES yet" />
                  <Kpi label="Opted out" value={n(k.optedOut)} hint="STOP" />
                  <Kpi label="Banned" value={n(k.banned)} />
                </dl>
              </Section>

              <div className="grid gap-6 lg:grid-cols-2">
                <Section title="Signups per day (ET)" aside={`${n(m.signupsDaily.reduce((s, p) => s + p.value, 0))} in range`}>
                  <BarChart data={m.signupsDaily} label="Signups per day" unit=" signups" />
                </Section>
                <Section title="Total players" aside={`${n(k.joined)} now`}>
                  <LineChart data={m.signupsCumulative} label="Cumulative signups" unit=" players" />
                </Section>
                <Section title="Signups per hour" aside="last 48 h, ET">
                  <BarChart data={m.signupsHourly} label="Signups per hour" unit=" signups" height="h-28" />
                </Section>
                <Section title="Calls per hour" aside="last 48 h, ET">
                  <BarChart data={m.callsHourly} label="Calls per hour" unit=" calls" height="h-28" barClass="fill-blue" />
                </Section>
                <Section title="Calls per day (ET)" aside={<Legend items={[{ label: "connected", className: "bg-pink" }, { label: "accepted", className: "bg-accent" }]} />}>
                  <BarChart data={m.callsDaily} label="Calls per day" unit=" connected" unit2=" accepted" />
                </Section>
                <Section title="Valid reps per day (ET)">
                  <BarChart data={m.repsDaily} label="Valid reps per day" unit=" reps" barClass="fill-good" />
                </Section>
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <Section title="Funnel" aside="all time">
                  <Funnel steps={m.funnel} />
                  <p className="mt-2 text-[11px] text-ink-2">
                    Visits are one per browser tab session; taps count every tap. People who text JOIN without the site
                    skip the first two steps, so a step can exceed the one before it.
                  </p>
                </Section>
                <Section
                  title="Site visits per day (ET)"
                  aside={<Legend items={[{ label: "visits", className: "bg-pink" }, { label: "JOIN taps", className: "bg-accent" }]} />}
                >
                  <BarChart data={m.visitsDaily} label="Site visits per day" unit=" visits" unit2=" JOIN taps" />
                </Section>
              </div>

              <Section title="Virality">
                <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <Kpi label="Referred signups" value={n(v.referred)} hint={`${formatPct(v.referredShare)} of signups`} tone="accent" />
                  <Kpi label="Players who invited" value={n(v.activeReferrers)} hint="at least one friend joined" />
                  <Kpi label="Longest invite chain" value={n(v.maxDepth)} hint="A invited B invited C = 2" />
                  <Kpi label="2nd+ generation" value={n(v.secondGen)} hint="joined via someone who was invited" />
                </dl>
                <div className="mt-4 grid gap-6 lg:grid-cols-2">
                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">How players found us</h3>
                    <ShareBars rows={v.sources} />
                  </div>
                  <div>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Where site visits came from</h3>
                    <ShareBars rows={v.visitSources} />
                  </div>
                </div>
                <h3 className="mt-4 mb-2 text-xs font-bold uppercase tracking-widest text-ink-2">Top inviters</h3>
                <Table head={["#", "Player", "Friends joined", "…who called"]} empty={!v.topReferrers.length}>
                  {v.topReferrers.map((r, i) => (
                    <tr key={r.userId}>
                      <td className="tabular-nums">{i + 1}</td>
                      <td>
                        <p className="font-semibold">{r.name}</p>
                        <Mono>{r.userId}</Mono>
                      </td>
                      <td className="tabular-nums">{n(r.referred)}</td>
                      <td className="tabular-nums">{n(r.referredCalled)}</td>
                    </tr>
                  ))}
                </Table>
              </Section>
            </>
          );
        }}
      </Show>
      <Show loaded={retention}>{(r) => <RetentionSection view={shapeRetention(r)} />}</Show>
    </>
  );
}
