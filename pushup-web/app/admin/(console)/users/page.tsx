import { requireAdmin } from "@/lib/admin";
import { adjustScore, setBan } from "../../actions";
import { ActionForm, btnCls, inputCls } from "../../_components/forms";
import { Mono, Pill, Section, Show, Table, Time } from "../../_components/ui";
import { load, searchUsers } from "../../_lib/data";

export default async function AdminUsersPage({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  await requireAdmin();
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.slice(0, 100) : "";
  const users = await load("users", () => searchUsers(q));

  return (
    <Section title="Users" aside="Search by display name, or exact phone (+1...) / email handle.">
      <form method="get" className="mb-3 flex gap-2">
        <input name="q" defaultValue={q} placeholder="Search users" className={`${inputCls} max-w-sm`} aria-label="Search users" />
        <button type="submit" className={btnCls}>
          Search
        </button>
      </form>
      <Show loaded={users}>
        {(list) => (
          <Table head={["User", "Rank / points", "Joined", "Status", "Ban / unban", "Adjust score"]} empty={!list.length}>
            {list.map((u) => (
              <tr key={u.id}>
                <td>
                  <p className="font-semibold">{u.display_name ?? "(no name)"}</p>
                  <Mono>{u.id}</Mono>
                </td>
                <td className="tabular-nums whitespace-nowrap">
                  {u.rank != null ? `#${u.rank}` : "unranked"} · {u.points ?? 0} pts
                </td>
                <td><Time at={u.joined_at} /></td>
                <td className="space-x-1">
                  {u.banned_at ? <Pill tone="bad">banned</Pill> : <Pill tone="good">active</Pill>}
                  {u.opted_out_at && <Pill>opted out</Pill>}
                  {u.ban_reason && <p className="mt-1 text-[11px] text-ink-2">{u.ban_reason}</p>}
                </td>
                <td className="min-w-64">
                  <ActionForm
                    action={setBan}
                    submitLabel={u.banned_at ? "Unban" : "Ban"}
                    danger={!u.banned_at}
                    confirm={`${u.banned_at ? "Unban" : "Ban"} ${u.display_name ?? u.id}?`}
                  >
                    <input type="hidden" name="user_id" value={u.id} />
                    <input type="hidden" name="ban" value={u.banned_at ? "0" : "1"} />
                  </ActionForm>
                </td>
                <td className="min-w-72">
                  <ActionForm
                    action={adjustScore}
                    submitLabel="Adjust"
                    confirm={`Adjust points for ${u.display_name ?? u.id}?`}
                  >
                    <input type="hidden" name="user_id" value={u.id} />
                    <input
                      name="points"
                      required
                      inputMode="numeric"
                      pattern="[+\-]?\d{1,6}"
                      placeholder="±pts"
                      className={`${inputCls} w-20`}
                      aria-label="Points delta"
                    />
                  </ActionForm>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Show>
    </Section>
  );
}
