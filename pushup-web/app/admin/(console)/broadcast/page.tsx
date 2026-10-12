import { requireAdmin } from "@/lib/admin";
import { previewBroadcast, sendBroadcast } from "../../actions";
import { BroadcastPanel } from "../../_components/panels";
import { Section } from "../../_components/ui";

export default async function AdminBroadcastPage() {
  await requireAdmin();
  return (
    <Section title="Broadcast" aside="Preview first (dry run). Sending requires a reason and confirmation; quiet hours apply.">
      <BroadcastPanel preview={previewBroadcast} send={sendBroadcast} />
    </Section>
  );
}
