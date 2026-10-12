import { requireAdmin } from "@/lib/admin";
import { rejudgeApply, rejudgeDryRun } from "../../actions";
import { RejudgePanel } from "../../_components/panels";
import { Section } from "../../_components/ui";

export default async function AdminRejudgePage() {
  await requireAdmin();
  return (
    <Section title="Rejudge" aside="Dry run shows the diff; apply re-scores stored reps with the same thresholds.">
      <RejudgePanel dryRun={rejudgeDryRun} apply={rejudgeApply} />
    </Section>
  );
}
