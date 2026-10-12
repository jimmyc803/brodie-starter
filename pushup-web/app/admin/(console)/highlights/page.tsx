import { requireAdmin } from "@/lib/admin";
import { Mono, Section, Show, Table, Time } from "../../_components/ui";
import { getHighlights, load } from "../../_lib/data";

export default async function AdminHighlightsPage() {
  await requireAdmin();
  const h = await load("highlights", () => getHighlights());
  return (
    <Show loaded={h}>
      {(d) => (
        <>
          <Section title={`Top scorers · ${d.date} (ET)`}>
            <Table head={["#", "Name", "Points", "Valid reps", "Calls"]} empty={!d.topScorers.length}>
              {d.topScorers.map((t, i) => (
                <tr key={t.display_name}>
                  <td className="tabular-nums">{i + 1}</td>
                  <td className={i === 0 ? "font-bold text-accent" : "font-semibold"}>{t.display_name}</td>
                  <td className="tabular-nums">{t.points}</td>
                  <td className="tabular-nums">{t.valid_reps}</td>
                  <td className="tabular-nums">{t.calls}</td>
                </tr>
              ))}
            </Table>
          </Section>
          <Section title={`Best single calls · ${d.date} (ET)`}>
            <Table head={["#", "Name", "Points", "Valid reps", "Connected", "Call"]} empty={!d.bestCalls.length}>
              {d.bestCalls.map((c, i) => (
                <tr key={c.call_id}>
                  <td className="tabular-nums">{i + 1}</td>
                  <td className={i === 0 ? "font-bold text-accent" : "font-semibold"}>{c.display_name}</td>
                  <td className="tabular-nums">{c.points}</td>
                  <td className="tabular-nums">{c.valid_reps}</td>
                  <td><Time at={c.connected_at} /></td>
                  <td>
                    <a href={`/r/${encodeURIComponent(c.call_id)}`} className="hover:text-accent">
                      <Mono>{c.call_id}</Mono>
                    </a>
                  </td>
                </tr>
              ))}
            </Table>
          </Section>
        </>
      )}
    </Show>
  );
}
