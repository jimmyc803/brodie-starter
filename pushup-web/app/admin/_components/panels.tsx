"use client";

import { useActionState } from "react";
import { INITIAL, JsonBlock, ReasonInput, Result, btnCls, dangerBtnCls, inputCls, type AdminAction } from "./forms";

function rec(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : {};
}

function pick(obj: Record<string, unknown>, keys: string[]): unknown {
  for (const k of keys) if (obj[k] !== undefined && obj[k] !== null) return obj[k];
  return undefined;
}

function show(v: unknown): string {
  if (v === undefined) return "n/a";
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") return String(v);
  return JSON.stringify(v);
}

function ConfirmBox({ label }: { label: string }) {
  return (
    <label className="flex items-center gap-2 text-xs font-semibold text-ink-2">
      <input type="checkbox" name="confirm" value="yes" required className="accent-[#d4ff3a]" />
      {label}
    </label>
  );
}

// ------------------------------------------------------------------ broadcast: preview -> confirm

export function BroadcastPanel({ preview, send }: { preview: AdminAction; send: AdminAction }) {
  const [pState, previewAction, pPending] = useActionState(preview, INITIAL);
  const [sState, sendAction, sPending] = useActionState(send, INITIAL);
  const pData = rec(pState.data);
  const previewedBody = typeof pData.body === "string" ? pData.body : null;
  const result = rec(pData.result);
  const recipients = pick(result, ["recipients", "recipient_count", "count"]);

  return (
    <div className="space-y-4">
      <form action={previewAction} className="space-y-2">
        <textarea
          name="body"
          required
          maxLength={1000}
          rows={4}
          defaultValue={previewedBody ?? ""}
          placeholder="Message to every opted-in competitor"
          className={inputCls}
          aria-label="Broadcast message"
        />
        <button type="submit" className={btnCls} disabled={pPending}>
          {pPending ? "Previewing..." : "Preview (dry run)"}
        </button>
        <Result state={pState} />
      </form>

      {pState.ok && previewedBody !== null && (
        <section className="space-y-2 rounded-lg border border-accent/60 bg-surface-2 p-3">
          <p className="text-xs font-bold uppercase tracking-widest text-ink-2">
            Preview · recipients: <span className="text-accent">{show(Array.isArray(recipients) ? recipients.length : recipients)}</span>
          </p>
          <p className="whitespace-pre-wrap rounded-md bg-canvas p-2 text-sm">{show(result.preview ?? previewedBody)}</p>
          <details className="text-xs text-ink-2">
            <summary className="cursor-pointer">Raw dispatcher response</summary>
            <JsonBlock value={pState.data} />
          </details>
          <form action={sendAction} className="flex flex-wrap items-center gap-2">
            <input type="hidden" name="body" value={previewedBody} />
            <div className="min-w-48 flex-1">
              <ReasonInput />
            </div>
            <ConfirmBox label="Send this exact text to all recipients" />
            <button type="submit" className={dangerBtnCls} disabled={sPending}>
              {sPending ? "Sending..." : "Send broadcast"}
            </button>
          </form>
          <Result state={sState} />
          {sState.ok && <JsonBlock value={sState.data} />}
        </section>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ rejudge: dry-run diff -> apply

export function RejudgePanel({ dryRun, apply }: { dryRun: AdminAction; apply: AdminAction }) {
  const [dState, dryAction, dPending] = useActionState(dryRun, INITIAL);
  const [aState, applyAction, aPending] = useActionState(apply, INITIAL);
  const dData = rec(dState.data);
  const thresholds = typeof dData.thresholds === "string" ? dData.thresholds : "";

  return (
    <div className="space-y-4">
      <form action={dryAction} className="space-y-2">
        <textarea
          name="thresholds"
          rows={6}
          defaultValue={thresholds}
          placeholder='Optional thresholds override JSON, e.g. {"min_elbow_deg": 95}. Empty = current config.'
          className={`${inputCls} font-mono`}
          aria-label="Thresholds JSON"
        />
        <button type="submit" className={btnCls} disabled={dPending}>
          {dPending ? "Running..." : "Dry run (diff only)"}
        </button>
        <Result state={dState} />
      </form>
      {dState.ok && (
        <section className="space-y-2 rounded-lg border border-accent/60 bg-surface-2 p-3">
          <p className="text-xs font-bold uppercase tracking-widest text-ink-2">Dry-run diff</p>
          <JsonBlock value={dData.result} />
          <form action={applyAction} className="flex flex-wrap items-center gap-2">
            <input type="hidden" name="thresholds" value={thresholds} />
            <div className="min-w-48 flex-1">
              <ReasonInput />
            </div>
            <ConfirmBox label="Apply these changes to live scores" />
            <button type="submit" className={dangerBtnCls} disabled={aPending}>
              {aPending ? "Applying..." : "Apply rejudge"}
            </button>
          </form>
          <Result state={aState} />
          {aState.ok && <JsonBlock value={aState.data} />}
        </section>
      )}
    </div>
  );
}
