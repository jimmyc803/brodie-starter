"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";

import { addClientAction, type AddClientState } from "@/app/c/[token]/clients/actions";

// "+ Add client": a one-field form that opens the new client once they're created.
export function AddClient({ token, base }: { token: string; base: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [state, action, pending] = useActionState<AddClientState, FormData>(addClientAction.bind(null, token), { ok: false, message: "" });
  useEffect(() => {
    if (state.ok && state.clientId) router.push(`${base}?c=${encodeURIComponent(state.clientId)}`);
  }, [state, base, router]);

  if (!open)
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="w-full rounded-lg border border-dashed border-line-strong px-3 py-2 text-sm text-ink-2 transition-colors hover:border-ink/40 hover:text-ink"
      >
        + Add client
      </button>
    );
  return (
    <form action={action} className="rounded-lg border border-line bg-canvas p-3">
      <label htmlFor="new-client" className="text-xs text-ink-2">
        Client name
      </label>
      <input
        id="new-client"
        name="name"
        required
        maxLength={60}
        autoFocus
        autoComplete="off"
        placeholder="e.g. Alex Kim"
        className="mt-1 w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-ink/40 focus:outline-none"
      />
      <div className="mt-2 flex gap-2">
        <button disabled={pending} className="rounded-full bg-ink px-4 py-1.5 text-sm font-medium text-canvas disabled:opacity-50">
          {pending ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="px-2 text-sm text-ink-2 hover:text-ink">
          Cancel
        </button>
      </div>
      {state.message && !state.ok ? (
        <p role="alert" className="mt-2 text-xs text-bad">
          {state.message}
        </p>
      ) : null}
    </form>
  );
}
