import { requireAdmin } from "@/lib/admin";
import { JsonBlock } from "../../_components/forms";
import { Mono, Pill, Section, Show, Table, Time } from "../../_components/ui";
import { HEARTBEAT_STALE_MS, getDispatcherHealth, getFailedMessages, getHeartbeats, load } from "../../_lib/data";

/** Flags whose value means a fallback/unverified mode (SPEC §12: no silent fallbacks). */
const FALLBACK: Record<string, string[]> = {
  MESSAGING_PROVIDER: ["mock"],
  HANGUP_MODE: ["unverified"],
  CALLER_ID_SOURCE: ["claim_window"],
};

export default async function AdminHealthPage() {
  const { email } = await requireAdmin();
  const [health, beats, failed] = await Promise.all([
    load("dispatcher /health", () => getDispatcherHealth(email)),
    load("heartbeats", () => getHeartbeats()),
    load("failed messages", getFailedMessages),
  ]);
  const flags = health.ok && health.data.flags && typeof health.data.flags === "object"
    ? (health.data.flags as Record<string, unknown>)
    : null;

  return (
    <>
      <Section title="Dispatcher">
        <Show loaded={health}>
          {(h) => (
            <div className="space-y-2">
              <div className="flex flex-wrap gap-2">
                <Pill tone={h.ok === true ? "good" : "bad"}>ok: {String(h.ok)}</Pill>
                <Pill tone={h.db === true || h.db === "ok" ? "good" : "bad"}>db: {String(h.db)}</Pill>
                <Pill>provider: {String(h.provider)}</Pill>
              </div>
              {flags && (
                <Table head={["Flag", "Value"]}>
                  {Object.entries(flags).map(([k, v]) => (
                    <tr key={k}>
                      <td className="font-mono">{k}</td>
                      <td>
                        <Pill tone={FALLBACK[k]?.includes(String(v)) ? "bad" : "neutral"}>{String(v)}</Pill>
                        {FALLBACK[k]?.includes(String(v)) && <span className="ml-2 text-[11px] text-bad">fallback mode</span>}
                      </td>
                    </tr>
                  ))}
                </Table>
              )}
              {h.line_states !== undefined && <JsonBlock value={h.line_states} />}
            </div>
          )}
        </Show>
      </Section>

      <Section title="Heartbeats" aside={`stale after ${HEARTBEAT_STALE_MS / 60_000} min`}>
        <Show loaded={beats}>
          {(list) => (
            <Table head={["Component", "Last beat", "Status", "Detail"]} empty={!list.length}>
              {list.map((b) => {
                const stale = b.stale;
                return (
                  <tr key={b.component}>
                    <td className="font-semibold">{b.component}</td>
                    <td><Time at={b.at} /></td>
                    <td><Pill tone={stale ? "bad" : "good"}>{stale ? "stale" : "ok"}</Pill></td>
                    <td><Mono>{b.detail == null ? "" : JSON.stringify(b.detail)}</Mono></td>
                  </tr>
                );
              })}
            </Table>
          )}
        </Show>
      </Section>

      <Section title="Recent failed outbound messages">
        <Show loaded={failed}>
          {(list) => (
            <Table head={["Id", "Template", "Attempts", "Error", "Created"]} empty={!list.length}>
              {list.map((m) => (
                <tr key={m.id}>
                  <td className="tabular-nums">{m.id}</td>
                  <td>{m.template ?? "-"}</td>
                  <td className="tabular-nums">{m.attempts ?? 0}</td>
                  <td className="text-bad">{m.last_error ?? "-"}</td>
                  <td><Time at={m.created_at} /></td>
                </tr>
              ))}
            </Table>
          )}
        </Show>
      </Section>
    </>
  );
}
