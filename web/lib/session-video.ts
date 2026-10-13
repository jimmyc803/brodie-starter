import "server-only";

import type { ExerciseClip, SessionView } from "@/lib/contract";
import { hasSupabase, SAMPLE_SESSION_TOKEN } from "@/lib/session-view";
import { supabaseServer } from "@/lib/supabase/server";

// Workout footage for the tap-a-muscle player, from the private 'recaps' bucket:
//   videos/<sessions.id>.mp4      one recording of the whole session; rep t values are seconds into it
//                                 (true when the session was made from a video file, e.g. scripts/make_demo_video.py --save)
//   videos/demo/<exercise_key>.mp4  one clip per exercise for the sample session (/r/demo)
// Missing footage or any storage error means no clips: the recap never breaks over video.
const BUCKET = "recaps";
const TTL_S = 6 * 60 * 60;
const LEAD_S = 2.5; // show the setup before the first rep
const TAIL_S = 1.5;

// demoFallback: the public demo coach's sessions have no recordings of their own, so they borrow the
// per-exercise demo clips. Only the demo coach link passes it; real clients never see someone else's video.
export async function sessionClips(view: SessionView, opts: { demoFallback?: boolean } = {}): Promise<ExerciseClip[]> {
  if (!hasSupabase()) return [];
  try {
    const storage = supabaseServer().storage.from(BUCKET);
    const demoClips = async () => {
      const keys = view.exercises.map((ex) => ex.exercise_key);
      const { data } = await storage.createSignedUrls(keys.map((k) => `videos/demo/${k}.mp4`), TTL_S);
      return (data ?? []).flatMap((d, i) => (d.signedUrl && !d.error ? [{ exercise_key: keys[i], url: d.signedUrl, start: 0, end: null }] : []));
    };
    if (view.session.share_token === SAMPLE_SESSION_TOKEN) return await demoClips();
    const { data, error } = await storage.createSignedUrl(`videos/${view.session.id}.mp4`, TTL_S);
    if (error || !data?.signedUrl) return opts.demoFallback ? await demoClips() : [];
    const own = view.exercises.flatMap((ex) => {
      const ts = ex.sets.flatMap((s) => s.reps.map((r) => r.t)).filter((t): t is number => typeof t === "number");
      if (!ts.length) return [];
      return [{ exercise_key: ex.exercise_key, url: data.signedUrl, start: Math.max(0, Math.min(...ts) - LEAD_S), end: Math.max(...ts) + TAIL_S }];
    });
    return own.length || !opts.demoFallback ? own : await demoClips();
  } catch {
    return [];
  }
}
