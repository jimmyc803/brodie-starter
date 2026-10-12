import { requireAdmin } from "@/lib/admin";
import { setConfigValue } from "../../actions";
import { ActionForm, inputCls } from "../../_components/forms";
import { Section, Show } from "../../_components/ui";
import { getConfig, load } from "../../_lib/data";

export default async function AdminConfigPage() {
  await requireAdmin();
  const cfg = await load("config", getConfig);
  return (
    <Section title="Competition config" aside="Values are JSON. Type changes are rejected. Every save is audited.">
      <Show loaded={cfg}>
        {(c) => (
          <ul className="divide-y divide-hairline/50">
            {Object.entries(c).map(([key, value]) => {
              const json = JSON.stringify(value, null, Array.isArray(value) || (value && typeof value === "object") ? 2 : 0);
              return (
                <li key={key} className="grid gap-2 py-2 lg:grid-cols-[14rem_1fr]">
                  <div>
                    <p className="font-mono text-xs font-semibold text-ink">{key}</p>
                    <p className="font-mono text-[11px] text-ink-2 break-all">{JSON.stringify(value)}</p>
                  </div>
                  <ActionForm
                    action={setConfigValue}
                    submitLabel="Save"
                    confirm={`Change ${key} on the live competition?`}
                    className="grid gap-2 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-start"
                  >
                    <input type="hidden" name="key" value={key} />
                    <textarea
                      name="value"
                      required
                      defaultValue={json}
                      rows={Math.min(6, json.split("\n").length)}
                      className={`${inputCls} font-mono`}
                      aria-label={`${key} value (JSON)`}
                    />
                  </ActionForm>
                </li>
              );
            })}
          </ul>
        )}
      </Show>
    </Section>
  );
}
