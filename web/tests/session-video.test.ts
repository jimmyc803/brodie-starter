import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sessionClips } from "@/lib/session-video";
import { sampleSessionView } from "@/lib/session-view";

const storage = vi.hoisted(() => ({ createSignedUrl: vi.fn(), createSignedUrls: vi.fn(), from: vi.fn() }));
vi.mock("@/lib/supabase/server", () => ({
  supabaseServer: () => ({ storage: { from: storage.from } }),
}));

beforeEach(() => {
  vi.stubEnv("SUPABASE_URL", "https://storage.example.invalid");
  vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "test-only-key");
  storage.from.mockReturnValue(storage);
});

afterEach(() => {
  vi.resetAllMocks();
  vi.unstubAllEnvs();
});

function recordedSession() {
  const view = sampleSessionView();
  view.session = { ...view.session, id: "recorded-session", share_token: "private-session-token" };
  view.exercises = view.exercises.slice(0, 3).map((ex, i) => ({
    ...ex,
    sets: [{ ...ex.sets[0], reps: (i === 0 ? [12, 5, 9] : i === 1 ? [1, 3] : []).map((t, j) => ({ rep_number: j + 1, t, faults: [] })) }],
  }));
  return view;
}

describe("session video clips", () => {
  it("keeps successful demo exercise URLs and omits missing or errored footage", async () => {
    const view = sampleSessionView();
    storage.createSignedUrls.mockResolvedValue({ data: view.exercises.map((ex, i) => ({
      path: `videos/demo/${ex.exercise_key}.mp4`,
      signedUrl: i === 1 ? null : `https://storage.example.invalid/${ex.exercise_key}.mp4`,
      error: i === 1 ? "Object not found" : i === 2 ? "Denied" : null,
    })), error: null });
    expect(await sessionClips(view)).toEqual([
      { exercise_key: view.exercises[0].exercise_key, url: "https://storage.example.invalid/squat.mp4", start: 0, end: null },
      { exercise_key: view.exercises[3].exercise_key, url: "https://storage.example.invalid/bicep_curl.mp4", start: 0, end: null },
    ]);
    expect(storage.from).toHaveBeenCalledWith("recaps");
    expect(storage.createSignedUrls).toHaveBeenCalledWith(view.exercises.map((ex) => `videos/demo/${ex.exercise_key}.mp4`), 21600);
  });

  it("maps a private session recording to exercise timestamp bounds and clamps setup time at zero", async () => {
    const view = recordedSession();
    const url = "https://storage.example.invalid/private-signed.mp4";
    storage.createSignedUrl.mockResolvedValue({ data: { signedUrl: url }, error: null });
    expect(await sessionClips(view)).toEqual([
      { exercise_key: view.exercises[0].exercise_key, url, start: 2.5, end: 13.5 },
      { exercise_key: view.exercises[1].exercise_key, url, start: 0, end: 4.5 },
    ]);
    expect(storage.createSignedUrl).toHaveBeenCalledWith("videos/recorded-session.mp4", 21600);
    expect(storage.createSignedUrls).not.toHaveBeenCalled();
  });

  it("does not access storage without Supabase configuration", async () => {
    vi.stubEnv("SUPABASE_SERVICE_ROLE_KEY", "");
    expect(await sessionClips(recordedSession())).toEqual([]);
    expect(storage.from).not.toHaveBeenCalled();
  });

  it.each([
    { data: null, error: { message: "Object not found" } },
    { data: null, error: null },
  ])("returns no clips when the recording cannot be signed (%j)", async (result) => {
    storage.createSignedUrl.mockResolvedValue(result);
    expect(await sessionClips(recordedSession())).toEqual([]);
  });

  it("returns no demo clips when bulk signing fails", async () => {
    storage.createSignedUrls.mockResolvedValue({ data: null, error: { message: "Storage unavailable" } });
    expect(await sessionClips(sampleSessionView())).toEqual([]);
  });

  it.each([true, false])("keeps the recap usable when storage throws (demo=%s)", async (demo) => {
    storage.createSignedUrl.mockRejectedValue(new Error("Storage unavailable"));
    storage.createSignedUrls.mockRejectedValue(new Error("Storage unavailable"));
    expect(await sessionClips(demo ? sampleSessionView() : recordedSession())).toEqual([]);
  });
});
