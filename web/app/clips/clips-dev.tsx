"use client";

import { useEffect, useState } from "react";

import { DropZone, useClipUpload } from "@/components/rep-review/add-clip";
import { RepReviewPlayer } from "@/components/rep-review/review-launcher";
import { ACCENTS, REVIEW_CLIPS, type ReviewClip } from "@/lib/rep-review/clips.config";
import { deleteUploadedClip, getPose, getUploadedClip, listUploadedClipIds } from "@/lib/rep-review/store";

type Status = { uploaded: string | null; cached: boolean };

export function ClipsDev() {
  const [status, setStatus] = useState<Record<string, Status>>({});
  const [playing, setPlaying] = useState<{ id: string; mode: "coach" | "client" } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let live = true;
    (async () => {
      const ids = new Set(await listUploadedClipIds());
      const next: Record<string, Status> = {};
      for (const c of REVIEW_CLIPS) {
        const up = ids.has(c.id) ? await getUploadedClip(c.id) : null;
        const key = up?.name ?? c.clipUrl.split("/").pop()!;
        next[c.id] = { uploaded: up?.name ?? null, cached: Boolean(await getPose(key)) };
      }
      if (live) setStatus(next);
    })();
    return () => {
      live = false;
    };
  }, [tick]);

  const ordered = playing ? [REVIEW_CLIPS.find((c) => c.id === playing.id)!, ...REVIEW_CLIPS.filter((c) => c.id !== playing.id)] : [];

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-10 text-zinc-100 sm:px-6">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[#D4FF00]">Dev · rep review</p>
      <h1 className="mt-2 text-3xl font-bold tracking-tight">Clips</h1>
      <p className="mt-1 max-w-2xl text-sm text-zinc-400">
        Entries come from <code className="text-zinc-300">lib/rep-review/clips.config.ts</code>. Drop a clip on an entry to replace its
        video on this device; pose landmarks are computed once and cached in IndexedDB.
      </p>
      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {REVIEW_CLIPS.map((c) => (
          <ClipCard
            key={c.id}
            clip={c}
            status={status[c.id]}
            onPlay={(mode) => setPlaying({ id: c.id, mode })}
            onChanged={() => setTick((t) => t + 1)}
          />
        ))}
      </div>
      {playing ? (
        <RepReviewPlayer clips={ordered} mode={playing.mode} clientName="Ryan" programHref="/c/demo/program" onClose={() => {
          setPlaying(null);
          setTick((t) => t + 1);
        }} />
      ) : null}
    </main>
  );
}

function ClipCard({ clip, status, onPlay, onChanged }: { clip: ReviewClip; status?: Status; onPlay: (m: "coach" | "client") => void; onChanged: () => void }) {
  const { upload, progress, error } = useClipUpload();
  const accent = ACCENTS[clip.accent ?? "volt"];
  return (
    <div className="overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900">
      <div className="relative aspect-[4/3] bg-black">
        {clip.poster ? (
          // eslint-disable-next-line @next/next/no-img-element -- same-origin poster
          <img src={clip.poster} alt="" className="size-full object-cover opacity-80" />
        ) : null}
        <span className="absolute left-3 top-3 rounded-full bg-black/70 px-2 py-0.5 font-mono text-[11px] text-zinc-300">{clip.id}</span>
      </div>
      <div className="space-y-3 p-4">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="font-semibold">
            {clip.exercise} · {clip.setLabel}
          </h2>
          <span className="tabular-nums text-sm" style={{ color: accent }}>
            {clip.setScore}
          </span>
        </div>
        <p className="text-xs text-zinc-400">
          {clip.reps.length} reps · {clip.reps.filter((r) => r.flag).length} flagged · {clip.muscles.join(", ")}
        </p>
        <p className="text-xs text-zinc-500">
          Source: {status?.uploaded ? `upload (${status.uploaded})` : clip.clipUrl} · landmarks {status?.cached ? "cached" : "not cached yet"}
        </p>
        <DropZone compact accent={accent} progress={progress} onFile={async (f) => (await upload(clip.id, f)) && onChanged()} />
        {error ? <p className="text-xs text-amber-300">{error}</p> : null}
        <div className="flex flex-wrap gap-2">
          <button onClick={() => onPlay("coach")} className="rounded-full px-3 py-1.5 text-xs font-semibold text-zinc-950" style={{ background: accent }}>
            ▶ Coach view
          </button>
          <button onClick={() => onPlay("client")} className="rounded-full bg-zinc-800 px-3 py-1.5 text-xs font-semibold hover:bg-zinc-700">
            ▶ Client view
          </button>
          {status?.uploaded ? (
            <button
              onClick={async () => {
                await deleteUploadedClip(clip.id);
                onChanged();
              }}
              className="ml-auto text-xs text-zinc-500 underline-offset-2 hover:underline"
            >
              Remove upload
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
