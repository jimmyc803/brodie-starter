"use client";

import { useActionState, useState } from "react";
import type { ActionResult } from "@/lib/admin";

export type AdminAction = (prev: ActionResult, fd: FormData) => Promise<ActionResult>;

export const INITIAL: ActionResult = { ok: false, status: 0 };

export const inputCls =
  "w-full rounded-md border border-hairline bg-canvas px-2 py-1.5 text-sm text-ink placeholder:text-ink-2/60 focus:border-accent focus:outline-none";
export const btnCls =
  "rounded-md bg-accent px-3 py-1.5 text-sm font-bold text-on-accent hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";
export const ghostBtnCls =
  "rounded-md border border-hairline px-3 py-1.5 text-sm font-semibold text-ink hover:border-accent disabled:opacity-50";
export const dangerBtnCls =
  "rounded-md bg-bad px-3 py-1.5 text-sm font-bold text-canvas hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50";

export function Result({ state }: { state: ActionResult }) {
  if (state.status === 0) return null;
  return (
    <p role="status" className={`text-xs font-semibold ${state.ok ? "text-accent" : "text-bad"}`}>
      {state.ok ? state.message : state.error}
    </p>
  );
}

export function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-96 overflow-auto rounded-md border border-hairline bg-canvas p-2 text-xs leading-snug text-ink-2">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function ReasonInput({ id }: { id?: string }) {
  return (
    <input
      id={id}
      name="reason"
      required
      minLength={3}
      maxLength={500}
      placeholder="Reason (required, audited)"
      className={inputCls}
      aria-label="Reason"
    />
  );
}

/**
 * Generic mutating form: renders `children` inputs plus a reason field. With `confirm`, the first click arms an
 * inline confirmation instead of submitting. The server re-validates everything regardless.
 */
export function ActionForm({
  action,
  children,
  submitLabel,
  confirm,
  danger,
  reason = true,
  className = "flex flex-wrap items-center gap-2",
}: {
  action: AdminAction;
  children?: React.ReactNode;
  submitLabel: string;
  confirm?: string;
  danger?: boolean;
  reason?: boolean;
  className?: string;
}) {
  const [state, formAction, pending] = useActionState(action, INITIAL);
  const [armed, setArmed] = useState(false);
  const cls = danger ? dangerBtnCls : btnCls;
  return (
    <form
      action={formAction}
      onSubmit={(e) => {
        // Implicit (Enter-key) submission must not bypass the confirmation step.
        if (confirm && !armed) {
          e.preventDefault();
          setArmed(true);
          return;
        }
        setArmed(false);
      }}
      className="space-y-1"
    >
      <div className={className}>
        {children}
        {reason && (
          <div className="min-w-48 flex-1">
            <ReasonInput />
          </div>
        )}
        {confirm && !armed ? (
          <button type="button" className={cls} onClick={() => setArmed(true)} disabled={pending}>
            {submitLabel}
          </button>
        ) : (
          <button type="submit" className={cls} disabled={pending}>
            {pending ? "Working..." : confirm ? "Confirm" : submitLabel}
          </button>
        )}
        {confirm && armed && (
          <button type="button" className={ghostBtnCls} onClick={() => setArmed(false)}>
            Cancel
          </button>
        )}
      </div>
      {confirm && armed && <p className="text-xs font-semibold text-accent">{confirm}</p>}
      <Result state={state} />
    </form>
  );
}
