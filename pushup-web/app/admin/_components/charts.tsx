import type { DualPoint, FunnelStep, Point, ShareRow } from "../_lib/metrics";
import { formatPct } from "../_lib/metrics";

/**
 * Dependency-free charts for the admin console. Shapes are SVG stretched to the container (so they fill any width,
 * phone included); every label is HTML so it never scales. Hover a bar for its exact value (<title>).
 */

const fmtInt = new Intl.NumberFormat("en-US");
export const n = (v: number) => fmtInt.format(v);

export function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: "accent" }) {
  return (
    <div className="rounded-lg border border-hairline bg-canvas p-2.5">
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink-2">{label}</dt>
      <dd className={`mt-0.5 font-display text-3xl leading-none tabular-nums ${tone === "accent" ? "text-accent" : "text-ink"}`}>
        {value}
      </dd>
      {hint ? <dd className="mt-1 text-[11px] text-ink-2">{hint}</dd> : null}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; className: string }[] }) {
  return (
    <ul className="flex flex-wrap gap-3 text-[11px] text-ink-2">
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1">
          <span aria-hidden className={`inline-block size-2.5 rounded-sm ${i.className}`} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/** First / middle / last x labels: enough to orient without crowding a phone screen. */
function XAxis({ labels }: { labels: string[] }) {
  if (!labels.length) return null;
  const picks = labels.length <= 3 ? labels : [labels[0], labels[Math.floor((labels.length - 1) / 2)], labels[labels.length - 1]];
  return (
    <div className="mt-1 flex justify-between gap-2 text-[10px] text-ink-2 tabular-nums">
      {picks.map((l, i) => (
        <span key={`${l}-${i}`}>{l}</span>
      ))}
    </div>
  );
}

function Frame({
  max,
  empty,
  label,
  children,
  height = "h-36",
}: {
  max: number;
  empty: boolean;
  label: string;
  children: React.ReactNode;
  height?: string;
}) {
  return (
    <figure className="min-w-0">
      <div className={`relative ${height} border-b border-l border-hairline`}>
        <span className="absolute -top-0.5 left-1 text-[10px] text-ink-2 tabular-nums">{empty ? "" : n(max)}</span>
        <div aria-hidden className="absolute inset-x-0 top-0 border-t border-dashed border-hairline" />
        <svg
          role="img"
          aria-label={label}
          className="absolute inset-0 h-full w-full overflow-visible"
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
        >
          {children}
        </svg>
        {empty ? (
          <p className="absolute inset-0 grid place-items-center text-xs text-ink-2">No data yet</p>
        ) : null}
      </div>
    </figure>
  );
}

/** Vertical bars. With `value2` (≤ value) a darker bar is drawn inside each bar (e.g. accepted within connected). */
export function BarChart({
  data,
  label,
  unit = "",
  unit2 = "",
  barClass = "fill-pink",
  bar2Class = "fill-accent",
  height,
}: {
  data: (Point | DualPoint)[];
  label: string;
  unit?: string;
  unit2?: string;
  barClass?: string;
  bar2Class?: string;
  height?: string;
}) {
  const max = Math.max(0, ...data.map((d) => d.value));
  const empty = max === 0;
  const slot = data.length ? 100 / data.length : 100;
  const gap = Math.min(slot * 0.2, 1.2);
  const h = (v: number) => (max > 0 ? (v / max) * 96 : 0);
  return (
    <div>
      <Frame max={max} empty={empty} label={label} height={height}>
        {data.map((d, i) => {
          const x = i * slot + gap / 2;
          const w = Math.max(slot - gap, 0.2);
          const v2 = "value2" in d ? d.value2 : null;
          const tip = `${d.label}: ${n(d.value)}${unit}${v2 != null ? `, ${n(v2)}${unit2}` : ""}`;
          return (
            <g key={d.key}>
              <title>{tip}</title>
              {/* full-height hit area so hover works on short bars too */}
              <rect x={i * slot} y={0} width={slot} height={100} className="fill-transparent" />
              <rect x={x} y={100 - h(d.value)} width={w} height={h(d.value)} className={barClass} />
              {v2 != null && v2 > 0 ? (
                <rect x={x} y={100 - h(Math.min(v2, d.value))} width={w} height={h(Math.min(v2, d.value))} className={bar2Class} />
              ) : null}
            </g>
          );
        })}
      </Frame>
      <XAxis labels={data.map((d) => d.label)} />
    </div>
  );
}

/** Area + line, for running totals. */
export function LineChart({ data, label, unit = "" }: { data: Point[]; label: string; unit?: string }) {
  const max = Math.max(0, ...data.map((d) => d.value));
  const empty = max === 0;
  const xs = (i: number) => (data.length > 1 ? (i / (data.length - 1)) * 100 : 50);
  const ys = (v: number) => 100 - (max > 0 ? (v / max) * 96 : 0);
  const pts = data.map((d, i) => `${xs(i).toFixed(2)},${ys(d.value).toFixed(2)}`).join(" ");
  return (
    <div>
      <Frame max={max} empty={empty} label={label}>
        {data.length && !empty ? (
          <>
            <polygon points={`0,100 ${pts} 100,100`} className="fill-accent/15" />
            <polyline
              points={pts}
              fill="none"
              strokeWidth={2}
              vectorEffect="non-scaling-stroke"
              strokeLinejoin="round"
              className="stroke-accent"
            />
            {data.map((d, i) => (
              <g key={d.key}>
                <title>{`${d.label}: ${n(d.value)}${unit}`}</title>
                <rect x={xs(i) - 50 / Math.max(data.length, 1)} y={0} width={100 / Math.max(data.length, 1)} height={100} className="fill-transparent" />
              </g>
            ))}
          </>
        ) : null}
      </Frame>
      <XAxis labels={data.map((d) => d.label)} />
    </div>
  );
}

/** Horizontal bars with value and share; HTML only, so it reflows on any width. */
export function ShareBars({ rows, empty = "No data yet" }: { rows: ShareRow[]; empty?: string }) {
  if (!rows.length || rows.every((r) => r.value === 0)) return <p className="py-3 text-xs text-ink-2">{empty}</p>;
  const max = Math.max(...rows.map((r) => r.value));
  return (
    <ul className="space-y-1.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2 text-xs">
          <span className="truncate font-semibold" title={r.label}>
            {r.label}
          </span>
          <span className="h-3 rounded-sm bg-surface-2">
            <span className="block h-full rounded-sm bg-pink" style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="tabular-nums text-ink-2">
            {n(r.value)} · {formatPct(r.share)}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Funnel: bar width relative to the largest step; shows conversion from the previous step and from the top. */
export function Funnel({ steps }: { steps: FunnelStep[] }) {
  const max = Math.max(0, ...steps.map((s) => s.value));
  return (
    <ol className="space-y-1.5">
      {steps.map((s, i) => (
        <li key={s.label} className="text-xs">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-semibold">
              {i + 1}. {s.label}
            </span>
            <span className="tabular-nums text-ink-2">
              <strong className="text-ink">{n(s.value)}</strong>
              {s.ofPrev != null ? ` · ${formatPct(s.ofPrev)} of prev` : ""}
            </span>
          </div>
          <div className="mt-0.5 h-4 rounded-sm bg-surface-2">
            <div
              className={`h-full rounded-sm ${i === steps.length - 1 ? "bg-accent" : "bg-pink"}`}
              style={{ width: `${max > 0 ? Math.max((s.value / max) * 100, s.value > 0 ? 1 : 0) : 0}%` }}
            />
          </div>
        </li>
      ))}
    </ol>
  );
}
