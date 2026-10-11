"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { createLocalVideoTrack, Room, RoomEvent, Track, type LocalVideoTrack, type RemoteTrack } from "livekit-client";

// The client's workout call, in the browser: publish the camera as the track Brodie watches, play Brodie's voice, show his
// video (the recap card at the end). Same protocol as facetime/phone_test.html, which the worker is built around.
const CALLER_TRACK = "facetime-remote-video";
const COACH_IDENTITY = "brodie-agent";

type Phase = "idle" | "connecting" | "live" | "ended" | "error";

export function CallLauncher({ token, firstName }: { token: string; firstName: string }) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [coachHere, setCoachHere] = useState(false);
  const [needsTap, setNeedsTap] = useState(false);
  const [facing, setFacing] = useState<"user" | "environment">("user");
  const [hasCoachVideo, setHasCoachVideo] = useState(false);
  const roomRef = useRef<Room | null>(null);
  const camRef = useRef<LocalVideoTrack | null>(null);
  const previewRef = useRef<HTMLVideoElement>(null);
  const coachVideoRef = useRef<HTMLVideoElement>(null);
  const audioBoxRef = useRef<HTMLDivElement>(null);
  const wakeRef = useRef<{ release: () => Promise<void> } | null>(null);

  useEffect(() => () => void roomRef.current?.disconnect(), []);

  // After the call, the worker saves the session within a few seconds: refresh the page until the new recap shows up.
  useEffect(() => {
    if (phase !== "ended") return;
    let n = 0;
    const id = setInterval(() => {
      router.refresh();
      if (++n >= 8) clearInterval(id);
    }, 3000);
    return () => clearInterval(id);
  }, [phase, router]);

  async function start() {
    setPhase("connecting");
    setError(null);
    try {
      const res = await fetch(`/api/call/${encodeURIComponent(token)}`, { method: "POST" });
      const pass = await res.json();
      if (!res.ok) throw new Error(pass.error ?? "Could not start the call.");

      const room = new Room({ adaptiveStream: false, dynacast: false });
      roomRef.current = room;
      const coachPresent = () => setCoachHere([...room.remoteParticipants.values()].some((p) => p.identity === COACH_IDENTITY));
      room.on(RoomEvent.ParticipantConnected, coachPresent);
      room.on(RoomEvent.ParticipantDisconnected, coachPresent);
      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack, _pub, p) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          audioBoxRef.current?.appendChild(el);
          el.play().catch(() => setNeedsTap(true));
        } else if (track.kind === Track.Kind.Video && p.identity === COACH_IDENTITY && coachVideoRef.current) {
          track.attach(coachVideoRef.current);
          setHasCoachVideo(true);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => {
        track.detach().forEach((el) => {
          if (el !== coachVideoRef.current) el.remove();
        });
        if (track.kind === Track.Kind.Video) setHasCoachVideo(false);
      });
      room.on(RoomEvent.AudioPlaybackStatusChanged, () => setNeedsTap(!room.canPlaybackAudio));
      room.on(RoomEvent.Disconnected, () => finish());

      await room.connect(pass.url, pass.token);
      coachPresent();
      const cam = await createLocalVideoTrack({ facingMode: facing, resolution: { width: 1280, height: 720, frameRate: 30 } });
      camRef.current = cam;
      if (previewRef.current) cam.attach(previewRef.current);
      await room.localParticipant.publishTrack(cam, {
        name: CALLER_TRACK,
        source: Track.Source.Camera,
        simulcast: false,
        videoEncoding: { maxBitrate: 2_500_000, maxFramerate: 30 },
      });
      try {
        wakeRef.current = await (navigator as Navigator & { wakeLock?: { request: (t: "screen") => Promise<{ release: () => Promise<void> }> } }).wakeLock?.request("screen") ?? null;
      } catch {
        /* keep-awake is best effort */
      }
      setPhase("live");
    } catch (e) {
      await roomRef.current?.disconnect();
      roomRef.current = null;
      setError(e instanceof Error && /permission|NotAllowed/i.test(e.message + e.name) ? "Camera access was blocked. Allow the camera for this site and try again." : e instanceof Error ? e.message : "Could not start the call.");
      setPhase("error");
    }
  }

  function finish() {
    camRef.current?.stop();
    camRef.current = null;
    void wakeRef.current?.release().catch(() => {});
    wakeRef.current = null;
    roomRef.current = null;
    setPhase((p) => (p === "live" || p === "connecting" ? "ended" : p));
  }

  async function end() {
    await roomRef.current?.disconnect();
    finish();
  }

  async function flip() {
    const next = facing === "user" ? "environment" : "user";
    setFacing(next);
    await camRef.current?.restartTrack({ facingMode: next });
  }

  async function unlockAudio() {
    await roomRef.current?.startAudio();
    audioBoxRef.current?.querySelectorAll("audio").forEach((el) => void el.play().catch(() => {}));
    setNeedsTap(false);
  }

  const inCall = phase === "connecting" || phase === "live";
  return (
    <div>
      <div ref={audioBoxRef} hidden />
      <div className={inCall ? "fixed inset-0 z-50 bg-black" : "hidden"}>
        <video ref={previewRef} autoPlay playsInline muted className={`h-full w-full object-cover ${facing === "user" ? "-scale-x-100" : ""}`} />
        <video
          ref={coachVideoRef}
          autoPlay
          playsInline
          muted
          className={`absolute bottom-24 right-3 w-[38%] max-w-56 rounded-xl border border-white/20 bg-black shadow-2xl ${hasCoachVideo ? "" : "hidden"}`}
        />
        <div className="absolute inset-x-0 top-0 flex items-center justify-between gap-3 bg-gradient-to-b from-black/70 to-transparent p-4 pt-[max(1rem,env(safe-area-inset-top))]">
          <span className="flex items-center gap-2 text-sm font-medium text-white">
            <span className={`size-2 rounded-full ${coachHere ? "bg-green-500" : "animate-pulse bg-yellow-400"}`} />
            {phase === "connecting" ? "Connecting…" : coachHere ? "Brodie is here" : "Brodie is joining…"}
          </span>
          <button type="button" onClick={flip} className="rounded-full bg-white/15 px-3 py-1.5 text-sm text-white backdrop-blur">
            Flip camera
          </button>
        </div>
        {needsTap ? (
          <button
            type="button"
            onClick={unlockAudio}
            className="absolute inset-x-6 top-1/2 -translate-y-1/2 rounded-2xl bg-white px-5 py-4 text-base font-semibold text-zinc-950 shadow-xl"
          >
            Tap to hear Brodie
          </button>
        ) : null}
        <div className="absolute inset-x-0 bottom-0 flex flex-col items-center gap-2 bg-gradient-to-t from-black/80 to-transparent p-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
          <p className="text-center text-xs text-white/70">Prop your phone up and step back so Brodie can see you head to toe.</p>
          <button type="button" onClick={end} className="rounded-full bg-red-500 px-8 py-3 text-base font-semibold text-white">
            End workout
          </button>
        </div>
      </div>

      {phase === "ended" ? (
        <div className="rounded-2xl border border-green-500/20 bg-green-500/5 p-5">
          <p className="font-semibold text-green-300">Nice work, {firstName}!</p>
          <p className="mt-1 text-sm text-zinc-400">Saving your workout. Your recap appears below in a few seconds.</p>
          <button type="button" onClick={() => setPhase("idle")} className="mt-4 text-sm text-zinc-400 underline-offset-4 hover:underline">
            Start another workout
          </button>
        </div>
      ) : (
        <>
          <button
            type="button"
            onClick={start}
            disabled={inCall}
            className="w-full rounded-full bg-green-500 px-6 py-4 text-lg font-semibold text-zinc-950 transition-colors hover:bg-green-400 disabled:opacity-60"
          >
            {phase === "connecting" ? "Starting…" : "Start workout"}
          </button>
          {error ? (
            <p role="alert" className="mt-3 text-sm text-red-300">
              {error}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}
