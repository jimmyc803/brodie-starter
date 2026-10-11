"use client";

import { useRef, useState } from "react";

import type { ReviewClip } from "@/lib/rep-review/clips.config";
import { computePoseTrack } from "@/lib/rep-review/pose";
import { putPose, putUploadedClip } from "@/lib/rep-review/store";

const EASE = "cubic-bezier(.2,.8,.2,1)";

// Drop an .mp4/.mov, link it to a config entry, compute its pose landmarks once (in the browser) and cache both in
// IndexedDB. The player then prefers this upload over the entry's bundled clipUrl.
export function useClipUpload() {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = async (id: string, file: File) => {
    setError(null);
    if (!/\.(mp4|mov|m4v|webm)$/i.test(file.name) && !file.type.startsWith("video/")) {
      setError("Drop an .mp4 or .mov file.");
      return false;
    }
    setProgress(0);
    try {
      await putUploadedClip(id, file);
      const track = await computePoseTrack(file, { onProgress: setProgress });
      await putPose(file.name, track);
      return true;
    } catch (e) {
      // The clip still plays without a skeleton; say so instead of failing the upload.
      setError(`Saved, but no skeleton: ${e instanceof Error ? e.message : "pose detection failed"}.`);
      return true;
    } finally {
      setProgress(null);
    }
  };
  return { upload, progress, error };
}

export function DropZone({
  onFile,
  progress,
  accent,
  compact,
}: {
  onFile: (f: File) => void;
  progress: number | null;
  accent: string;
  compact?: boolean;
}) {
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const busy = progress !== null;
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files[0];
        if (f && !busy) onFile(f);
      }}
      onClick={() => !busy && input.current?.click()}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => e.key === "Enter" && input.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center rounded-2xl border border-dashed text-center transition ${compact ? "px-3 py-4" : "px-6 py-10"}`}
      style={{
        borderColor: over ? accent : "rgba(255,255,255,0.18)",
        background: over ? `${accent}14` : "rgba(255,255,255,0.03)",
        transition: `all 240ms ${EASE}`,
      }}
    >
      <input
        ref={input}
        type="file"
        accept="video/mp4,video/quicktime,.mp4,.mov,.m4v"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      {busy ? (
        <div className="w-full max-w-56">
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-white/70 tabular-nums">
            Computing landmarks · {Math.round(progress * 100)}%
          </p>
          <div className="mt-2 h-1 overflow-hidden rounded-full bg-white/10">
            <div className="h-full rounded-full" style={{ width: `${progress * 100}%`, background: accent, transition: `width 160ms ${EASE}` }} />
          </div>
        </div>
      ) : (
        <>
          <p className="text-sm font-semibold text-white/90">Drop a clip</p>
          <p className="mt-0.5 text-xs text-white/50">.mp4 or .mov · or click to choose</p>
        </>
      )}
    </div>
  );
}

export function AddClipPanel({
  clips,
  defaultId,
  accent,
  onClose,
  onAdded,
}: {
  clips: ReviewClip[];
  defaultId: string;
  accent: string;
  onClose: () => void;
  onAdded: (id: string) => void;
}) {
  const [id, setId] = useState(defaultId);
  const { upload, progress, error } = useClipUpload();
  return (
    <div className="absolute inset-0 z-10 flex items-end justify-center bg-black/70 backdrop-blur-md sm:items-center sm:rounded-[28px]">
      <div className="w-full max-w-sm rounded-t-3xl border border-white/10 bg-[#121214] p-5 sm:rounded-3xl" style={{ animation: `rr-in 420ms ${EASE} both` }}>
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-white">Add clip</h3>
          <button onClick={onClose} className="text-xs text-white/50 hover:text-white" disabled={progress !== null}>
            Cancel
          </button>
        </div>
        <label className="mt-4 block text-[11px] font-semibold uppercase tracking-[0.18em] text-white/50">Link to</label>
        <select
          value={id}
          onChange={(e) => setId(e.target.value)}
          className="mt-1.5 w-full rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white"
        >
          {clips.map((c) => (
            <option key={c.id} value={c.id} className="bg-[#121214]">
              {c.exercise} · {c.setLabel} ({c.id})
            </option>
          ))}
        </select>
        <div className="mt-4">
          <DropZone accent={accent} progress={progress} onFile={async (f) => (await upload(id, f)) && onAdded(id)} />
        </div>
        {error ? <p className="mt-2 text-xs text-amber-300">{error}</p> : null}
        <p className="mt-3 text-[11px] leading-relaxed text-white/40">
          Landmarks are computed once on this device and cached; scores and rep times come from the clip config.
        </p>
      </div>
    </div>
  );
}
