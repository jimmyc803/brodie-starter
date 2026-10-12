"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { AddClient } from "@/components/coach/add-client";
import type { ClientStatus, ClientSummary } from "@/lib/coach-status";
import { moveSelection } from "@/lib/client-nav";

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
  const router = useRouter();
  const search = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const reviewCount = clients.filter((c) => c.status === "review").length;
  const [tab, setTab] = useState<ClientStatus | "all">(reviewCount ? "review" : "all");
  const [cursor, setCursor] = useState<string | null>(selectedId);
  const q = query.trim().toLowerCase();
  const shown = clients.filter((c) => (tab === "all" || c.status === tab) && (!q || c.name.toLowerCase().includes(q)));
  const href = (id: string) => `${base}?c=${encodeURIComponent(id)}`;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target;
      const typing = t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement;
      if (e.key === "/" && !typing) {
        e.preventDefault();
        search.current?.focus();
        return;
      }
      if (typing && t !== search.current) return;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => moveSelection(shown.map((s) => s.id), c, e.key));
      } else if (e.key === "Enter" && cursor && shown.some((s) => s.id === cursor)) {
        e.preventDefault();
        router.push(href(cursor));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  return (
    <nav aria-label="Clients" className="rounded-[14px] border border-line bg-sunken/60">
      <div className="space-y-2 p-3">
        {addToken ? <AddClient token={addToken} base={base} /> : null}
        <label className="flex items-center justify-between gap-2 rounded-[10px] border border-line-strong bg-surface px-3 py-2">
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
          const focused = c.id === cursor && !active;
          return (
            <li key={c.id}>
              <Link
                href={href(c.id)}
                aria-current={active ? "page" : undefined}
                onFocus={() => setCursor(c.id)}
                className={`${COLS} rounded-[10px] px-3 py-2.5 transition-colors ${
                  active ? "bg-surface shadow-[0_0_0_1px_var(--color-line)]" : focused ? "bg-surface/70" : "hover:bg-surface/60"
                } ${c.status === "inactive" && !active ? "opacity-60" : ""}`}
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
