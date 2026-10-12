import { requireAdmin } from "@/lib/admin";
import { setVoid } from "../../actions";
import { ActionForm, btnCls, inputCls } from "../../_components/forms";
import { Mono, Pill, Section, Show, Table, Time } from "../../_components/ui";
import { load, recentCalls } from "../../_lib/data";

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function AdminCallsPage({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  await requireAdmin();
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.trim().slice(0, 200) : "";
  const filter = !q ? {} : UUID_RE.test(q) ? { userId: q.toLowerCase() } : { callId: q };
  const calls = await load("calls", () => recentCalls(filter));

  return (
    <Section title="Recent calls" aside="Latest 50. Filter by call id or user id.">
      <form method="get" className="mb-3 flex gap-2">
        <input name="q" defaultValue={q} placeholder="Call id or user id" className={`${inputCls} max-w-sm`} aria-label="Filter calls" />
        <button type="submit" className={btnCls}>
          Filter
        </button>
      </form>
      <Show loaded={calls}>
        {(list) => (
          <Table head={["Call", "User", "Connected", "Decision", "Reps (ok/rej)", "Pts", "Liveness", "Void / unvoid"]} empty={!list.length}>
            {list.map((c) => (
              <tr key={c.call_id} className={c.void ? "opacity-70" : undefined}>
                <td>
                  <Mono>{c.call_id}</Mono>
                  <p className="text-[11px] text-ink-2">{c.line_id ?? ""}</p>
                </td>
                <td>{c.display_name ?? <Mono>{c.user_id ?? "-"}</Mono>}</td>
                <td><Time at={c.connected_at} /></td>
                <td>
                  <Pill tone={c.decision === "accept" ? "good" : "neutral"}>{c.decision}</Pill>
                  {c.reject_reason && <p className="text-[11px] text-ink-2">{c.reject_reason}</p>}
                  {c.counted_toward_cap && <p className="text-[11px] text-ink-2">counts toward cap</p>}
                </td>
                <td className="tabular-nums">
                  {c.valid_reps}/{c.rejected_reps}
                </td>
                <td className="tabular-nums font-semibold">{c.points}</td>
                <td>{c.liveness_result ?? "-"}</td>
                <td className="min-w-72">
                  {c.void && (
                    <p className="mb-1">
                      <Pill tone="bad">void</Pill> <span className="text-[11px] text-ink-2">{c.void_reason}</span>
                    </p>
                  )}
                  {c.decision === "accept" && (
                    <ActionForm
                      action={setVoid}
                      submitLabel={c.void ? "Unvoid" : "Void"}
                      danger={!c.void}
                      confirm={`${c.void ? "Unvoid" : "Void"} call ${c.call_id}?`}
                    >
                      <input type="hidden" name="call_id" value={c.call_id} />
                      <input type="hidden" name="void" value={c.void ? "0" : "1"} />
                    </ActionForm>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Show>
    </Section>
  );
}
