import { requireAdmin } from "@/lib/admin";
import { drawRaffle } from "../../actions";
import { RafflePanel } from "../../_components/panels";
import { Section } from "../../_components/ui";

export default async function AdminRafflePage() {
  await requireAdmin();
  return (
    <Section title="Raffle draw" aside="Deterministic for a given seed. Every draw is written to the audit log.">
      <RafflePanel draw={drawRaffle} />
    </Section>
  );
}
