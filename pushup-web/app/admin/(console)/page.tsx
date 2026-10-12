import { requireAdmin } from "@/lib/admin";
import { removeQueueEntry } from "../actions";
import { ActionForm } from "../_components/forms";
import { Mono, Pill, Section, Show, Table, Time } from "../_components/ui";
import { displayNames, getQueueView, load } from "../_lib/data";

export default async function AdminQueuePage() {
  await requireAdmin();
  const view = await load("queue view", getQueueView);
  const names = view.ok
    ? await load("names", () => displayNames(view.data.lines.map((l) => l.user_id ?? "")))
    : null;
  const nameOf = (id: string | null) => (id && names?.ok ? (names.data.get(id) ?? id) : (id ?? "-"));

  return (
    <>
      <Section
        title="Lines"
        aside={view.ok && view.data.avg_cycle_s != null ? `avg cycle ${Math.round(view.data.avg_cycle_s)}s` : undefined}
      >
        <Show loaded={view}>
          {(v) => (
            <Table head={["Line", "State", "User", "Call", "Claimed until", "In call since", "Offline until"]} empty={!v.lines.length}>
              {v.lines.map((l) => (
                <tr key={l.line_id}>
                  <td className="font-semibold">{l.line_id}</td>
                  <td>
                    <Pill tone={l.state === "idle" ? "good" : l.state === "offline" ? "bad" : "neutral"}>{l.state}</Pill>
                  </td>
                  <td>{nameOf(l.user_id)}</td>
                  <td>{l.call_id ? <Mono>{l.call_id}</Mono> : "-"}</td>
                  <td><Time at={l.claimed_until} /></td>
                  <td><Time at={l.in_call_since} /></td>
                  <td><Time at={l.offline_until} /></td>
                </tr>
              ))}
            </Table>
          )}
        </Show>
      </Section>

      <Section title="Queue" aside={view.ok ? `${view.data.queue.length} active` : undefined}>
        <Show loaded={view}>
          {(v) => (
            <Table head={["#", "Name", "Status", "Entered", "Calls today", "Remove (reason required)"]} empty={!v.queue.length}>
              {v.queue.map((q) => (
                <tr key={q.queue_id}>
                  <td className="tabular-nums">{q.position ?? "-"}</td>
                  <td className="font-semibold">
                    {q.display_name ?? "(no name)"} <Mono>{q.user_id}</Mono>
                  </td>
                  <td>
                    <Pill tone={q.status === "notified" ? "good" : "neutral"}>{q.status}</Pill>
                  </td>
                  <td><Time at={q.entered_at} /></td>
                  <td className="tabular-nums">{q.calls_today}</td>
                  <td className="min-w-72">
                    <ActionForm
                      action={removeQueueEntry}
                      submitLabel="Remove"
                      danger
                      confirm={`Remove ${q.display_name ?? "this user"} from the queue?`}
                    >
                      <input type="hidden" name="queue_id" value={q.queue_id} />
                    </ActionForm>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Show>
      </Section>
    </>
  );
}
