"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";

import { deleteClientAction, renameClientAction, type ManageClientState } from "@/app/c/[token]/clients/actions";

// Rename / Remove for one client, next to their name in the client header (approved coaches only).
export function ManageClient({ token, clientId, name, base }: { token: string; clientId: string; name: string; base: string }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [removing, startRemove] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [state, rename, saving] = useActionState<ManageClientState, FormData>(async (prev, form) => {
    const res = await renameClientAction(token, clientId, prev, form);
    if (res.ok) setEditing(false);
    return res;
  }, { ok: false, message: "" });

  function remove() {
    if (!window.confirm(`Remove ${name}? Their workouts and recaps are deleted too, and their link stops working.`)) return;
    setError(null);
    startRemove(async () => {
      const res = await deleteClientAction(token, clientId);
      if (res.ok) router.push(base);
      else setError(res.message);
    });
  }

  if (editing)
    return (
      <form action={rename} className="flex w-full flex-wrap items-center gap-2">
        <input
          name="name"
          defaultValue={name}
          required
          maxLength={60}
          autoFocus
          autoComplete="off"
          aria-label="Client name"
          className="min-w-0 flex-1 rounded-md border border-line-strong bg-canvas px-3 py-1.5 text-sm text-ink focus:border-ink/40 focus:outline-none"
        />
        <button disabled={saving} className="rounded-full bg-ink px-3.5 py-1.5 text-sm font-medium text-canvas disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
        <button type="button" onClick={() => setEditing(false)} className="px-1 text-sm text-ink-2 hover:text-ink">
          Cancel
        </button>
        {state.message && !state.ok ? (
          <p role="alert" className="w-full text-xs text-bad">
            {state.message}
          </p>
        ) : null}
      </form>
    );
  return (
    <div className="ml-auto flex items-center gap-3 text-xs text-ink-3">
      <button type="button" onClick={() => setEditing(true)} className="hover:text-ink">
        Rename
      </button>
      <button type="button" onClick={remove} disabled={removing} className="hover:text-bad disabled:opacity-50">
        {removing ? "Removing…" : "Remove"}
      </button>
      {error ? (
        <span role="alert" className="text-bad">
          {error}
        </span>
      ) : null}
    </div>
  );
}
