import { requireAdmin } from "@/lib/admin";
import { adjustScore, setBan, setTeam } from "../../actions";
import { ActionForm, btnCls, inputCls } from "../../_components/forms";
import { Mono, Pill, Section, Show, Table, Time } from "../../_components/ui";
import { load, searchUsers } from "../../_lib/data";

export default async function AdminUsersPage({ searchParams }: { searchParams: Promise<{ q?: string | string[] }> }) {
  await requireAdmin();
  const sp = await searchParams;
  const q = typeof sp.q === "string" ? sp.q.slice(0, 100) : "";
  const users = await load("users", () => searchUsers(q));

  return (
    <Section
      title="Users"
      aside="Search by display name, or exact phone (+1...) / email handle. An adjustment moves valid reps with the points unless you type your own reps delta (0 = points only)."
    >
      <form method="get" className="mb-3 flex gap-2">
        <input name="q" defaultValue={q} placeholder="Search users" className={`${inputCls} max-w-sm`} aria-label="Search users" />
        <button type="submit" className={btnCls}>
          Search
        </button>
      </form>
      <Show loaded={users}>
        {(list) => (
          <Table
            head={[
              "User",
              "Rank / points / reps",
              "Joined",
              "Status",
              "Ban / unban",
              "Adjust score + reps",
              "Team / test account",
            ]}
            empty={!list.length}
          >
            {list.map((u) => (
              <tr key={u.id}>
                <td>
                  <p className="font-semibold">{u.display_name ?? "(no name)"}</p>
                  <Mono>{u.id}</Mono>
                </td>
                <td className="tabular-nums whitespace-nowrap">
                  {u.rank != null ? `#${u.rank}` : "unranked"} · {u.points ?? 0} pts
                  <p className="text-[11px] text-ink-2">{u.valid_reps ?? 0} valid reps</p>
                </td>
                <td><Time at={u.joined_at} /></td>
                <td className="space-x-1">
                  {u.banned_at ? <Pill tone="bad">banned</Pill> : <Pill tone="good">active</Pill>}
                  {u.opted_out_at && <Pill>opted out</Pill>}
                  {u.is_team && <Pill>team · no cap · first in line</Pill>}
                  {u.ban_reason && <p className="mt-1 text-[11px] text-ink-2">{u.ban_reason}</p>}
                </td>
                <td className="min-w-64">
                  <ActionForm
                    action={setBan}
                    submitLabel={u.banned_at ? "Unban" : "Ban"}
                    danger={!u.banned_at}
                    reason={false}
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
                    reason={false}
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
                    <input
                      name="reps"
                      inputMode="numeric"
                      pattern="[+\-]?\d{1,6}"
                      placeholder="±reps"
                      title="Blank: valid reps move with the points. 0: change points only."
                      className={`${inputCls} w-20`}
                      aria-label="Valid reps delta (blank = same as points)"
                    />
                  </ActionForm>
                </td>
                <td className="min-w-64">
                  <ActionForm
                    action={setTeam}
                    submitLabel={u.is_team ? "Unmark team" : "Mark team"}
                    confirm={
                      u.is_team
                        ? `Count ${u.display_name ?? u.id} in metrics again and put their daily call cap back?`
                        : `Exclude ${u.display_name ?? u.id} from metrics and lift their daily call cap? (D-38)`
                    }
                  >
                    <input type="hidden" name="user_id" value={u.id} />
                    <input type="hidden" name="team" value={u.is_team ? "0" : "1"} />
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
