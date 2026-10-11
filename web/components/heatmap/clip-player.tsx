"use client";

import { useEffect, useRef } from "react";

import type { ExerciseClip } from "@/lib/contract";

// Bottom sheet that plays one exercise's stretch of the workout recording, looping between clip.start and clip.end.
export function ClipPlayer({
  clip,
  title,
  subtitle,
  onClose,
}: {
  clip: ExerciseClip;
  title: string;
  subtitle: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const seekStart = () => {
    const v = ref.current;
    if (!v) return;
    v.currentTime = clip.start;
    void v.play().catch(() => {});
  };
  const onTime = () => {
    const v = ref.current;
    if (v && clip.end !== null && v.currentTime >= clip.end) seekStart();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center" role="dialog" aria-modal aria-label={title}>
      <button aria-label="Close video" onClick={onClose} className="absolute inset-0 bg-black/70 backdrop-blur-sm" />
      <div className="relative w-full max-w-sm animate-in slide-in-from-bottom-8 fade-in rounded-t-3xl border border-white/10 bg-zinc-950 p-4 pb-6 duration-300 sm:rounded-3xl">
        <div className="mx-auto mb-3 h-1 w-10 rounded-full bg-zinc-700 sm:hidden" />
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold">{title}</h3>
            <p className="text-xs text-zinc-400">{subtitle}</p>
          </div>
          <button onClick={onClose} className="rounded-full bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-300 hover:bg-zinc-700">
            Close
          </button>
        </div>
        <video
          ref={ref}
          src={clip.url}
          className="mx-auto max-h-[65dvh] w-full rounded-2xl bg-black object-contain"
          playsInline
          muted
          autoPlay
          loop={clip.end === null}
          controls
          preload="auto"
          onLoadedMetadata={seekStart}
          onTimeUpdate={onTime}
          onEnded={seekStart}
        />
        <p className="mt-3 text-center text-[11px] text-zinc-500">From your workout recording · camera-counted reps</p>
      </div>
    </div>
  );
}
