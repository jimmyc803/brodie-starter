"use client";

import { Barlow_Condensed, Bebas_Neue, Inter } from "next/font/google";
import { useCallback, useEffect, useRef, useState } from "react";

import { AddClipPanel } from "@/components/rep-review/add-clip";
import { ReviewEngine, scoreColor, type Phase } from "@/components/rep-review/engine";
import { ACCENTS, type ReviewClip } from "@/lib/rep-review/clips.config";
import { loadPoseTrack } from "@/lib/rep-review/pose";
import { Sfx } from "@/lib/rep-review/sfx";
import { getUploadedClip } from "@/lib/rep-review/store";

const bebas = Bebas_Neue({ weight: "400", subsets: ["latin"], display: "swap" });
const barlow = Barlow_Condensed({ weight: ["600", "700"], subsets: ["latin"], display: "swap" });
const inter = Inter({ weight: ["500", "600", "700"], subsets: ["latin"], display: "swap" });

const EASE = "cubic-bezier(.2,.8,.2,1)";

type Load = { state: "loading" } | { state: "analyzing"; progress: number } | { state: "ready" } | { state: "error"; message: string };

// Full-screen (mobile) / centred (desktop) rep review: the clip with an ad-grade overlay drawn on one canvas (see
// engine.ts). `clips` are the clips to offer, first one plays; the rest show as a thumbnail strip. Client mode hides
// coach-only copy (insight, Adjust program).
export function RepReviewPlayer({
  clips,
  mode,
  clientName,
  programHref,
  onClose,
}: {
  clips: ReviewClip[];
  mode: "coach" | "client";
  clientName?: string;
  programHref?: string;
  onClose: () => void;
}) {
  const [id, setId] = useState(clips[0]?.id);
  const clip = clips.find((c) => c.id === id) ?? clips[0];
  const [reloadKey, setReloadKey] = useState(0);
  const loadKey = `${clip?.id}:${reloadKey}`;
  const [loadState, setLoad] = useState<Load & { key: string }>({ state: "loading", key: "" });
  const load: Load = loadState.key === loadKey ? loadState : { state: "loading" };
  const [phase, setPhase] = useState<Phase>("intro");
  const [muted, setMuted] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [portrait, setPortrait] = useState(true);
  const [dragY, setDragY] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<ReviewEngine | null>(null);
  const [sfx] = useState(() => new Sfx());
  const dragStart = useRef<number | null>(null);

  const accent = ACCENTS[clip?.accent ?? "volt"];
  const name = clientName ?? (clip && clip.clientName !== "[Client]" ? clip.clientName : "Client");

  useEffect(() => {
    sfx.ensure(); // opened by a tap, so audio may start
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
      sfx.close();
    };
  }, [onClose, sfx]);

  // Load clip source (an uploaded file wins over the bundled one), its landmarks and fonts, then start the engine.
  useEffect(() => {
    if (!clip) return;
    const ac = new AbortController();
    let objectUrl: string | null = null;
    let cancelled = false;
    (async () => {
      const uploaded = await getUploadedClip(clip.id);
      const src: string | Blob = uploaded?.blob ?? clip.clipUrl;
      const key = uploaded?.name ?? clip.clipUrl.split("/").pop()!;
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas) return;
      objectUrl = typeof src === "string" ? null : URL.createObjectURL(src);
      video.src = objectUrl ?? (src as string);
      video.load();
      const ready = new Promise<void>((res, rej) => {
        if (video.readyState >= 2) return res();
        video.addEventListener("loadeddata", () => res(), { once: true });
        video.addEventListener("error", () => rej(new Error("This clip couldn't be played.")), { once: true });
      });
      const fonts = Promise.all(
        [bebas.style.fontFamily, barlow.style.fontFamily, inter.style.fontFamily].map((f) =>
          document.fonts.load(`700 64px ${f}`).catch(() => []),
        ),
      );
      const track = await loadPoseTrack(key, {
        src,
        precomputedUrl: uploaded ? undefined : clip.clipUrl.replace(/\.\w+$/, ".pose.json"),
        signal: ac.signal,
        onProgress: (p) => !cancelled && setLoad({ state: "analyzing", progress: p, key: loadKey }),
      });
      await Promise.all([ready, fonts]);
      if (cancelled) return;
      setPortrait(video.videoHeight >= video.videoWidth);
      engineRef.current?.destroy();
      const engine = new ReviewEngine(canvas, video, clip, track, {
        mode,
        clientName: name,
        sfx,
        letterbox: window.matchMedia("(min-width: 640px)").matches,
        fonts: { display: bebas.style.fontFamily, cond: barlow.style.fontFamily, ui: inter.style.fontFamily },
        onPhase: setPhase,
      });
      engineRef.current = engine;
      setLoad({ state: "ready", key: loadKey });
      engine.start();
    })().catch((e: unknown) => {
      if (!cancelled) setLoad({ state: "error", message: e instanceof Error ? e.message : "Couldn't load this clip.", key: loadKey });
    });
    return () => {
      cancelled = true;
      ac.abort();
      engineRef.current?.destroy();
      engineRef.current = null;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [clip, mode, name, loadKey, sfx]);

  const toggleMute = () => {
    const m = !muted;
    setMuted(m);
    sfx.setMuted(m);
  };

  const replay = () => engineRef.current?.replay();
  const idx = clips.findIndex((c) => c.id === clip?.id);
  const next = clips.length > 1 ? () => setId(clips[(idx + 1) % clips.length].id) : null;

  // Export: replay from the top while recording the composited canvas + the sound effects, stop after the end card.
  const exportVideo = useCallback(() => {
    const engine = engineRef.current;
    const canvas = canvasRef.current;
    if (!engine || !canvas || exporting || typeof MediaRecorder === "undefined") return;
    const stream = canvas.captureStream(60);
    const audio = sfx.stream;
    audio?.getAudioTracks().forEach((t) => stream.addTrack(t));
    const type = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t));
    const rec = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: 16_000_000 });
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    rec.onstop = () => {
      const blob = new Blob(chunks, { type: "video/webm" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${clip.id}-review-${engine.size.w}x${engine.size.h}.webm`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      setExporting(false);
    };
    setExporting(true);
    engine.onceSettled(() => rec.state !== "inactive" && rec.stop());
    rec.start(250);
    engine.replay();
  }, [clip, exporting, sfx]);

  // Swipe down to close (mobile).
  const onPointerDown = (e: React.PointerEvent) => {
    if (e.pointerType !== "touch") return;
    dragStart.current = e.clientY;
  };
  const onPointerMove = (e: React.PointerEvent) => {
    if (dragStart.current === null) return;
    setDragY(Math.max(0, e.clientY - dragStart.current));
  };
  const onPointerUp = () => {
    if (dragStart.current === null) return;
    dragStart.current = null;
    if (dragY > 130) onClose();
    else setDragY(0);
  };

  if (!clip) return null;
  const showEnd = phase === "end" && load.state === "ready" && !exporting;
  const others = clips.filter((c) => c.id !== clip.id);
  const fontVars = `${bebas.className} ${inter.className}`;

  return (
    <div
      className={`fixed inset-0 z-[60] flex items-center justify-center ${inter.className}`}
      role="dialog"
      aria-modal
      aria-label={`${clip.exercise} ${clip.setLabel} rep review`}
    >
      <button aria-label="Close rep review" onClick={onClose} className="rr-backdrop absolute inset-0 bg-black/80 backdrop-blur-xl" />
      <div
        className="rr-modal relative flex h-[100dvh] w-full flex-col bg-[#0A0A0A] sm:h-[92dvh] sm:w-[var(--rr-w)] sm:rounded-[28px] sm:border sm:border-white/10 sm:shadow-[0_40px_120px_rgba(0,0,0,0.7)]"
        style={{
          transform: dragY ? `translateY(${dragY}px)` : undefined,
          transition: dragY ? "none" : `transform 380ms ${EASE}`,
          ["--rr-w" as string]: portrait ? "min(94vw, calc((92dvh - 150px) * 9 / 16 + 40px))" : "min(94vw, 1280px)",
        }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {/* top bar */}
        <div className="flex items-center justify-between gap-2 px-4 pb-2 pt-[max(12px,env(safe-area-inset-top))] sm:px-5 sm:pt-4">
          <div className="flex items-center gap-2">
            <span className="size-2 rounded-full" style={{ background: accent, boxShadow: `0 0 12px ${accent}` }} />
            <span className="hidden whitespace-nowrap text-[11px] font-semibold min-[400px]:inline uppercase tracking-[0.22em] text-white/60">Rep review</span>
          </div>
          <div className="flex items-center gap-1.5">
            <Chip onClick={() => setAdding(true)} aria-label="Add clip">
              +<span className="hidden sm:inline"> Add clip</span>
            </Chip>
            <Chip onClick={exportVideo} disabled={load.state !== "ready" || exporting}>
              {exporting ? "● Rec" : "Export"}
            </Chip>
            <Chip onClick={toggleMute} aria-label={muted ? "Unmute" : "Mute"}>
              {muted ? "🔇" : "🔊"}
            </Chip>
            <Chip onClick={onClose} aria-label="Close">
              ✕
            </Chip>
          </div>
        </div>

        {/* stage */}
        <div className="relative min-h-0 flex-1 px-0 sm:px-5">
          <div
            className="relative mx-auto h-full overflow-hidden bg-black sm:rounded-2xl"
            style={{ aspectRatio: portrait ? "9 / 16" : "16 / 9", maxWidth: "100%" }}
          >
            <video ref={videoRef} className="pointer-events-none absolute inset-0 size-full opacity-0" playsInline muted preload="auto" crossOrigin="anonymous" />
            <canvas ref={canvasRef} className={`absolute inset-0 size-full object-contain ${fontVars}`} />
            {load.state !== "ready" ? (
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-[#0A0A0A]">
                {clip.poster ? (
                  // eslint-disable-next-line @next/next/no-img-element -- poster behind the loader, same-origin static file
                  <img src={clip.poster} alt="" className="absolute inset-0 size-full object-cover opacity-25 blur-md" />
                ) : null}
                <div className="relative w-56 text-center">
                  <p className={`${bebas.className} text-4xl tracking-wide text-[#F4F4F0]`}>
                    {load.state === "error" ? "Clip unavailable" : load.state === "analyzing" ? "Reading movement" : "Loading"}
                  </p>
                  {load.state === "error" ? (
                    <p className="mt-1 text-xs text-white/60">{load.message}</p>
                  ) : (
                    <div className="mt-3 h-1 overflow-hidden rounded-full bg-white/10">
                      <div
                        className="h-full rounded-full"
                        style={{
                          width: load.state === "analyzing" ? `${Math.round(load.progress * 100)}%` : "35%",
                          background: accent,
                          transition: `width 200ms ${EASE}`,
                          animation: load.state === "loading" ? "rr-indeterminate 1.1s ease-in-out infinite" : undefined,
                        }}
                      />
                    </div>
                  )}
                  {load.state === "analyzing" ? (
                    <p className="mt-2 text-[11px] font-semibold uppercase tracking-[0.2em] text-white/50 tabular-nums">
                      Pose landmarks · {Math.round(load.progress * 100)}%
                    </p>
                  ) : null}
                </div>
              </div>
            ) : null}

            {/* end card actions */}
            <div
              className="absolute inset-x-0 bottom-0 flex flex-wrap items-center justify-center gap-2 px-4 pb-[max(20px,4%)]"
              style={{
                opacity: showEnd ? 1 : 0,
                transform: showEnd ? "translateY(0)" : "translateY(16px)",
                transition: `opacity 500ms ${EASE} 1.6s, transform 500ms ${EASE} 1.6s`,
                pointerEvents: showEnd ? "auto" : "none",
              }}
            >
              <EndButton primary accent={accent} onClick={replay}>
                ↻ Replay
              </EndButton>
              {next ? <EndButton onClick={next}>Next clip →</EndButton> : null}
              {mode === "coach" && programHref ? (
                <a href={programHref} className="rr-end-btn rounded-full border border-white/15 bg-white/5 px-5 py-3 text-sm font-semibold uppercase tracking-[0.12em] text-[#F4F4F0] backdrop-blur-md transition hover:bg-white/10">
                  Adjust program
                </a>
              ) : null}
            </div>
          </div>
        </div>

        {/* other clips for this muscle */}
        {others.length ? (
          <div className="flex gap-2 overflow-x-auto px-4 pb-[max(14px,env(safe-area-inset-bottom))] pt-3 sm:px-5">
            {clips.map((c) => {
              const active = c.id === clip.id;
              const col = scoreColor(c.setScore, false, ACCENTS[c.accent ?? "volt"]);
              return (
                <button
                  key={c.id}
                  onClick={() => setId(c.id)}
                  aria-pressed={active}
                  className="group relative h-20 w-14 shrink-0 overflow-hidden rounded-xl border transition"
                  style={{ borderColor: active ? accent : "rgba(255,255,255,0.12)", boxShadow: active ? `0 0 0 1px ${accent}, 0 0 18px ${accent}55` : undefined }}
                >
                  {c.poster ? (
                    // eslint-disable-next-line @next/next/no-img-element -- tiny same-origin poster
                    <img src={c.poster} alt="" className="absolute inset-0 size-full object-cover opacity-70 transition group-hover:opacity-100" />
                  ) : null}
                  <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/90 to-transparent px-1 pb-1 pt-4 text-left">
                    <span className={`${bebas.className} block text-lg leading-none`} style={{ color: col }}>
                      {c.setScore}
                    </span>
                    <span className="block truncate text-[9px] font-semibold uppercase tracking-wider text-white/70">{c.setLabel}</span>
                  </span>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="pb-[max(14px,env(safe-area-inset-bottom))] sm:pb-5" />
        )}

        {adding ? (
          <AddClipPanel
            clips={clips}
            defaultId={clip.id}
            accent={accent}
            onClose={() => setAdding(false)}
            onAdded={(cid) => {
              setAdding(false);
              setId(cid);
              setReloadKey((k) => k + 1);
            }}
          />
        ) : null}
      </div>
      <style>{`
        @keyframes rr-indeterminate { 0% { transform: translateX(-100%) } 100% { transform: translateX(300%) } }
        @keyframes rr-in { from { opacity: 0; transform: translateY(24px) scale(.98) } to { opacity: 1; transform: none } }
        @keyframes rr-fade { from { opacity: 0 } to { opacity: 1 } }
        .rr-modal { animation: rr-in 520ms ${EASE} both }
        .rr-backdrop { animation: rr-fade 400ms ${EASE} both }
      `}</style>
    </div>
  );
}

function Chip({ children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...rest}
      className="whitespace-nowrap rounded-full border border-white/10 bg-white/[0.06] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-white/80 transition hover:bg-white/[0.12] disabled:opacity-40"
    >
      {children}
    </button>
  );
}

function EndButton({ children, primary, accent, onClick }: { children: React.ReactNode; primary?: boolean; accent?: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`rounded-full px-5 py-3 text-sm font-semibold uppercase tracking-[0.12em] backdrop-blur-md transition active:scale-[0.97] ${
        primary ? "text-[#0A0A0A]" : "border border-white/15 bg-white/5 text-[#F4F4F0] hover:bg-white/10"
      }`}
      style={primary ? { background: accent, boxShadow: `0 0 30px ${accent}66` } : undefined}
    >
      {children}
    </button>
  );
}
