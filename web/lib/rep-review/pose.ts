import { smoothTrack } from "./one-euro";
import { POSE_VERSION, type PoseFrameRow, type PoseTrack } from "./pose-types";
import { getPose, putPose } from "./store";

// Must match the installed @mediapipe/tasks-vision version exactly.
const VISION_VERSION = "1.1.0";
const WASM_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${VISION_VERSION}/wasm`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task";

const LANDMARKS = 33;

type ComputeOpts = { onProgress?: (frac: number) => void; signal?: AbortSignal; fps?: number };

const abortError = () => new DOMException("Pose computation aborted", "AbortError");

function waitFor(target: HTMLVideoElement, ok: string, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const done = () => {
      target.removeEventListener(ok, onOk);
      target.removeEventListener("error", onErr);
      signal?.removeEventListener("abort", onAbort);
    };
    const onOk = () => (done(), resolve());
    const onErr = () => (done(), reject(new Error("Video failed to load")));
    const onAbort = () => (done(), reject(abortError()));
    target.addEventListener(ok, onOk);
    target.addEventListener("error", onErr);
    signal?.addEventListener("abort", onAbort);
  });
}

export async function computePoseTrack(src: string | Blob, opts: ComputeOpts = {}): Promise<PoseTrack> {
  const { onProgress, signal, fps = 30 } = opts;
  if (signal?.aborted) throw abortError();

  const { FilesetResolver, PoseLandmarker } = await import("@mediapipe/tasks-vision");
  const fileset = await FilesetResolver.forVisionTasks(WASM_URL);
  const make = (delegate: "GPU" | "CPU") =>
    PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate },
      runningMode: "VIDEO",
      numPoses: 1,
    });
  let landmarker;
  try {
    landmarker = await make("GPU");
  } catch {
    landmarker = await make("CPU");
  }

  const objectUrl = typeof src === "string" ? null : URL.createObjectURL(src);
  const video = document.createElement("video");
  try {
    video.muted = true;
    video.playsInline = true;
    video.preload = "auto";
    video.crossOrigin = "anonymous";
    const loaded = waitFor(video, "loadeddata", signal);
    video.src = objectUrl ?? (src as string);
    await loaded;

    const duration = video.duration;
    if (!Number.isFinite(duration) || duration <= 0) throw new Error("Video has no duration");
    const step = 1 / fps;
    const frames: PoseFrameRow[] = [];
    let lastTs = -1;

    for (let t = 0; t <= duration; t += step) {
      if (signal?.aborted) throw abortError();
      const seeked = waitFor(video, "seeked", signal);
      video.currentTime = Math.min(t, duration);
      await seeked;

      const ts = Math.max(Math.round(t * 1000), lastTs + 1);
      lastTs = ts;
      const res = landmarker.detectForVideo(video, ts);
      const lm = res.landmarks[0];
      if (lm && lm.length >= LANDMARKS) {
        const row: PoseFrameRow = [t];
        for (let i = 0; i < LANDMARKS; i++) row.push(lm[i].x, lm[i].y, lm[i].visibility ?? 0);
        frames.push(row);
      } else if (frames.length) {
        frames.push([t, ...frames[frames.length - 1].slice(1)]);
      }
      onProgress?.(Math.min(1, t / duration));
    }
    onProgress?.(1);

    return smoothTrack({
      v: POSE_VERSION,
      fps,
      w: video.videoWidth,
      h: video.videoHeight,
      duration,
      frames,
    });
  } finally {
    landmarker.close();
    video.removeAttribute("src");
    video.load();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  }
}

type LoadOpts = {
  src: string | Blob;
  precomputedUrl?: string;
  compute?: boolean;
  onProgress?: (frac: number) => void;
  signal?: AbortSignal;
};

let warned = false;

const isTrack = (x: unknown): x is PoseTrack =>
  !!x && typeof x === "object" && (x as PoseTrack).v === POSE_VERSION && Array.isArray((x as PoseTrack).frames);

export async function loadPoseTrack(clipKey: string, opts: LoadOpts): Promise<PoseTrack | null> {
  try {
    const cached = await getPose(clipKey);
    if (cached) return cached;

    if (opts.precomputedUrl) {
      try {
        const res = await fetch(opts.precomputedUrl, { signal: opts.signal });
        if (res.ok) {
          const json: unknown = await res.json();
          if (isTrack(json)) {
            await putPose(clipKey, json);
            return json;
          }
        }
      } catch (e) {
        if (opts.signal?.aborted) throw e;
      }
    }

    if (opts.compute === false) return null;
    const track = await computePoseTrack(opts.src, {
      onProgress: opts.onProgress,
      signal: opts.signal,
    });
    await putPose(clipKey, track);
    return track;
  } catch (e) {
    if (!warned) {
      warned = true;
      console.warn("Pose track unavailable", e);
    }
    return null;
  }
}

// Linear interpolation of all 33 landmarks (x, y, v) at time t; null when t is outside the track.
export function sampleJoints(track: PoseTrack, t: number): Float32Array | null {
  const f = track.frames;
  if (!f.length) return null;
  if (t < f[0][0] - 0.25 || t > f[f.length - 1][0] + 0.25) return null;
  let lo = 0;
  let hi = f.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (f[mid][0] <= t) lo = mid;
    else hi = mid;
  }
  const a = f[lo];
  const b = f[hi];
  const span = b[0] - a[0];
  const u = span > 0 ? Math.min(1, Math.max(0, (t - a[0]) / span)) : 0;
  const out = new Float32Array(LANDMARKS * 3);
  for (let i = 0; i < out.length; i++) out[i] = a[i + 1] + (b[i + 1] - a[i + 1]) * u;
  return out;
}
