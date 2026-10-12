"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { AddClient } from "@/components/coach/add-client";
import type { ClientStatus, ClientSummary } from "@/lib/coach-status";
import { initialTab, listKeyAction, moveSelection } from "@/lib/client-nav";

const TABS: { key: ClientStatus | "all"; label: string }[] = [
  { key: "review", label: "Needs review" },
  { key: "all", label: "All" },
  { key: "inactive", label: "Inactive" },
];
const DOT: Record<ClientStatus, string> = { review: "bg-bad", on_track: "bg-good", inactive: "bg-idle" };
const COLS = "grid grid-cols-[minmax(0,1fr)_56px_44px_10px] items-center gap-2";

// The coach's roster as a compact table: search ("/" focuses), status tabs, ↑/↓ to move, Enter to open.
export function ClientList({
  clients,
  base,
  selectedId,
  addToken,
}: {
  clients: ClientSummary[];
  base: string;
  selectedId: string | null;
  addToken?: string; // the coach link, when this coach may add clients (never on the public demo)
}) {
  const nav = useRef<HTMLElement>(null);
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState<ClientStatus | "all">(() => initialTab(clients, selectedId));
  const q = query.trim().toLowerCase();
  const shown = clients.filter((c) => (tab === "all" || c.status === tab) && (!q || c.name.toLowerCase().includes(q)));
  const href = (id: string) => `${base}?c=${encodeURIComponent(id)}`;

  // Shortcuts only where they can't collide: "/" from the page or the list, ↑/↓ from the search box or a row.
  // ↑/↓ move real focus between row links, so the row scrolls into view and Enter is the link's own.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as Element | null;
      const row = t instanceof HTMLElement && nav.current?.contains(t) ? t.closest<HTMLElement>("[data-client-id]") : null;
      const where = t === search.current ? "search" : row ? "list" : !t || t === document.body ? "body" : "other";
      const action = listKeyAction(e, where);
      if (!action) return;
      e.preventDefault();
      if (action === "search") return search.current?.focus();
      const ids = [...(nav.current?.querySelectorAll<HTMLElement>("[data-client-id]") ?? [])].map((el) => el.dataset.clientId!);
      const next = moveSelection(ids, row?.dataset.clientId ?? null, e.key);
      if (next) nav.current?.querySelector<HTMLElement>(`[data-client-id="${CSS.escape(next)}"]`)?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <nav ref={nav} aria-label="Clients" className="rounded-[14px] border border-line bg-sunken/60">
      <div className="space-y-2 p-3">
        {addToken ? <AddClient token={addToken} base={base} /> : null}
        <label className="flex items-center justify-between gap-2 rounded-[10px] border border-line-strong bg-surface px-3 py-2 focus-within:border-ink/40">
          <input
            ref={search}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Search ${clients.length} ${clients.length === 1 ? "client" : "clients"}`}
            aria-label="Search clients"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink placeholder:text-ink-3 focus:outline-none"
          />
          <kbd className="hidden rounded-[5px] border border-line-strong px-1.5 text-[11px] text-ink-3 sm:inline">/</kbd>
        </label>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter clients">
          {TABS.map((t) => {
            const n = t.key === "all" ? clients.length : clients.filter((c) => c.status === t.key).length;
            const active = tab === t.key;
            return (
              <button
                key={t.key}
                type="button"
                aria-pressed={active}
                onClick={() => setTab(t.key)}
                className={`rounded-lg px-2.5 py-1 text-xs font-semibold transition-colors ${active ? "bg-surface text-ink" : "text-ink-3 hover:text-ink"}`}
              >
                {t.label} · {n}
              </button>
            );
          })}
        </div>
      </div>

      <div className={`${COLS} px-5 pb-1 text-[12px] font-medium text-ink-3`}>
        <span>Client · last session</span>
        <span className="text-right">Reps</span>
        <span className="text-right">Clean</span>
        <span />
      </div>
      {shown.length === 0 ? (
        <p className="px-5 py-8 text-center text-sm text-ink-3">{q ? "No clients match." : "Nobody here right now."}</p>
      ) : null}
      <ul className="max-h-[70vh] overflow-y-auto px-2 pb-2">
        {shown.map((c) => {
          const active = c.id === selectedId;
          return (
            <li key={c.id}>
              <Link
                href={href(c.id)}
                aria-current={active ? "page" : undefined}
                data-client-id={c.id}
                className={`${COLS} rounded-[10px] px-3 py-2.5 transition-colors ${
                  active ? "bg-surface shadow-[0_0_0_1px_var(--color-line)]" : "hover:bg-surface/60"
                } focus-visible:bg-surface focus-visible:shadow-[0_0_0_2px_var(--color-ink)] focus-visible:outline-none ${
                  c.status === "inactive" && !active ? "opacity-60" : ""
                }`}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-semibold text-ink">{c.name}</span>
                  <span className="block truncate text-xs text-ink-3">{c.detail}</span>
                </span>
                <span className="text-right text-[13.5px] font-semibold tabular-nums text-ink">{c.reps ?? "–"}</span>
                <span className="text-right text-[13.5px] font-semibold tabular-nums text-ink">{c.cleanPct === null ? "–" : `${c.cleanPct}%`}</span>
                <span
                  className={`size-[7px] rounded-full ${DOT[c.status]}`}
                  role="img"
                  aria-label={c.status === "on_track" ? "on track" : c.status === "review" ? "needs review" : "inactive"}
                />
              </Link>
            </li>
          );
        })}
      </ul>
      <p className="hidden border-t border-line px-5 py-2 text-[12px] text-ink-3 lg:block">↑ ↓ to move · Enter to open · / to search</p>
    </nav>
  );
}
