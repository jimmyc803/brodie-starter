import { afterEach, describe, expect, it, vi } from "vitest";
import { avatarLevelForPoints, makeCardModel, mapCallResult, mapDaily, mapProfile, mapThresholds, publicSiteUrl } from "@/lib/card";

vi.mock("server-only", () => ({}));

const call = {
  call_id: "call-42", display_name: "Ana", points: 30, points_before: 100,
  total_points_after: 130, valid_reps: 30, rejected_reps: 4,
  avatar_level_before: 3, avatar_level_after: 4, rank_before: 9, rank_after: 6,
  reasons: { too_shallow: 3, no_lockout: 1 }, void: false,
};

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("result card mapping", () => {
  it("uses the public before/after snapshots, including explicit avatar levels", () => {
    const model = makeCardModel(mapCallResult(call), mapProfile({ streak: 3 }), {
      dateEt: "2026-10-14", startsAt: "2026-10-14T18:00:00Z", endsAt: "2026-10-14T19:00:00Z",
    }, "https://challenge.example");
    expect(model).toMatchObject({ pointsLabel: "+30 points", pointsBefore: 100, totalPoints: 130,
      levelBefore: 3, levelAfter: 4, rankLabel: "#9 → #6", streak: 3,
      nextPowerHour: "Oct 14, 2:00 PM ET", siteUrl: "https://challenge.example",
      reasons: [{ label: "Too shallow", count: 3 }, { label: "No lockout", count: 1 }] });
    expect(mapCallResult({ ...call, avatar_level_before: 7, avatar_level_after: 8 })).toMatchObject({ levelBefore: 7, levelAfter: 8 });
  });

  it("handles unavailable ranks, streak and power-hour data", () => {
    const model = makeCardModel(mapCallResult({ ...call, rank_before: null }), null, null, null);
    expect(model.rankLabel).toBe("#6");
    expect(model.streak).toBeNull();
    expect(model.nextPowerHour).toBe("Not scheduled");
    expect(makeCardModel(mapCallResult({}), null, null, null).rankLabel).toBe("Unranked");
    expect(makeCardModel(mapCallResult(call), null, { dateEt: "", startsAt: "invalid", endsAt: "" }, null).nextPowerHour).toBe("Not scheduled");
  });

  it("does not award points for a void call or derive totals from earned points", () => {
    const result = mapCallResult({ ...call, void: true, total_points_after: 91 });
    expect(result).toMatchObject({ points: 0, void: true, totalPoints: 91, pointsBefore: 100 });
    expect(makeCardModel(result, null, null, null).pointsLabel).toBe("+0 points");
  });

  it("maps numeric strings and clamps malformed avatar and rank values", () => {
    expect(mapCallResult({ ...call, points: "30", avatar_level_before: -1, avatar_level_after: 99, rank_before: 0 })).toMatchObject({ points: 30, levelBefore: 1, levelAfter: 10, rankBefore: null });
    expect(mapCallResult({ points: Infinity, reasons: ["bad"] })).toMatchObject({ points: 0, reasons: [] });
  });

  it("projects only public fields and never renders arbitrary reason payloads", () => {
    const privateFields = { handle: "+15551234567", phone: "+15551234567", email: "private@example.com" };
    const result = mapCallResult({ ...call, ...privateFields, reasons: {
      "classifier:private@example.com": 2, "classifier:other": "1", "+15551234567": 1,
      too_fast: -1, no_lockout: "bad", toString: 2,
    } });
    expect(result.reasons).toEqual([{ label: "Form check", count: 3 }, { label: "Other", count: 3 }]);
    const profile = mapProfile({ display_name: "Ana", ...privateFields });
    const serialized = JSON.stringify(makeCardModel(result, profile, null, null));
    expect(serialized).not.toMatch(/15551234567|private@example|handle|phone|email/);
  });

  it("uses configured thresholds for level boundaries", () => {
    const thresholds = mapThresholds([0, 10, 50, 100, "bad", null]);
    expect(thresholds).toEqual([0, 10, 50, 100]);
    expect(avatarLevelForPoints(9, thresholds)).toBe(1);
    expect(avatarLevelForPoints(10, thresholds)).toBe(2);
    expect(avatarLevelForPoints(99, thresholds)).toBe(3);
    expect(avatarLevelForPoints(100, thresholds)).toBe(4);
    expect(mapThresholds(null)).toEqual([]);
  });

  it("maps profile and daily totals without leaking other columns", () => {
    expect(mapProfile({ display_name: "Ana", best_call_id: "best", best_call_points: "42", avatar_level: 4, rank: 6 })).toMatchObject({ displayName: "Ana", bestCallId: "best", bestCallPoints: 42, avatarLevel: 4, rank: 6 });
    expect(mapDaily({ date_et: "2026-10-14", points: -5, valid_reps: "4", calls: 1, handle: "private" })).toEqual({ dateEt: "2026-10-14", points: -5, validReps: 4, calls: 1 });
  });

  it("accepts only public HTTP origins for metadata", () => {
    expect(publicSiteUrl("https://challenge.example/path?q=value")).toBe("https://challenge.example");
    for (const input of ["javascript:alert(1)", "https://user:password@example.com", "bad"]) {
      expect(publicSiteUrl(input)).toBe("https://brodie-pushups.vercel.app");
    }
  });
});

describe("public data loaders", () => {
  it("publishes the absolute PNG endpoint in result metadata and excludes missing results", async () => {
    vi.stubEnv("PUSHUP_FIXTURES", "1");
    const { generateMetadata } = await import("@/app/r/[callId]/page");
    const callId = "00000000-0000-4000-8000-000000000042";
    const metadata = await generateMetadata({ params: Promise.resolve({ callId }) });
    const url = `https://brodie-pushups.vercel.app/r/${callId}`;
    expect(metadata).toMatchObject({
      title: "FixtureAthlete: +30 points | Brodie Push-Ups",
      description: "30 valid reps · 4 rejected · #9 → #6",
      openGraph: {
        url,
        images: [{ url: `${url}/card`, width: 1080, height: 1350, type: "image/png" }],
      },
      twitter: { card: "summary_large_image", images: [`${url}/card`] },
    });
    expect(await generateMetadata({ params: Promise.resolve({ callId: "missing" }) }))
      .toMatchObject({ robots: { index: false, follow: false } });
  });

  it("renders the fixture endpoint as a 1080×1350 PNG and returns 404 for missing calls", async () => {
    vi.stubEnv("PUSHUP_FIXTURES", "1");
    const { GET } = await import("@/app/r/[callId]/card/route");
    const request = new Request("http://localhost/r/fixture/card");
    const response = await GET(request, { params: Promise.resolve({ callId: "00000000-0000-4000-8000-000000000042" }) });
    expect(response.headers.get("content-type")).toBe("image/png");
    expect(response.headers.get("cache-control")).toBe("no-store");
    const png = Buffer.from(await response.arrayBuffer());
    expect(png.subarray(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
    expect(png.readUInt32BE(16)).toBe(1080);
    expect(png.readUInt32BE(20)).toBe(1350);
    const missing = await GET(request, { params: Promise.resolve({ callId: "missing" }) });
    expect(missing.status).toBe(404);
  }, 15000);

  it("fixtures include C7 fields, daily points, profile and unknown-result handling", async () => {
    vi.stubEnv("PUSHUP_FIXTURES", "1");
    const { getResultCardModel, getProfile, getUserDaily, getCompetition } = await import("@/lib/data");
    expect(await getResultCardModel("00000000-0000-4000-8000-000000000042")).toMatchObject({ pointsBefore: 100, levelBefore: 3, levelAfter: 4, rankLabel: "#9 → #6" });
    expect(await getProfile("FixtureAthlete")).toMatchObject({ avatarLevel: 4, streak: 3 });
    expect(await getUserDaily("FixtureAthlete")).toHaveLength(3);
    expect((await getCompetition())?.avatarLevelThresholds).toEqual([0, 25, 60, 120, 200, 300, 450, 650, 900, 1200]);
    expect(await getResultCardModel("missing")).toBeNull();
    expect(await getProfile("missing")).toBeNull();
  });

  it("quotes user filters, uses public views and selects the next future power hour", async () => {
    vi.stubEnv("PUSHUP_FIXTURES", "0");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://db.example");
    vi.stubEnv("NEXT_PUBLIC_SUPABASE_ANON_KEY", "test-anon-key");
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => [] });
    vi.stubGlobal("fetch", fetchMock);
    const { getProfile, getNextPowerHour } = await import("@/lib/data");
    const name = 'A&B,"name"';
    await getProfile(name);
    const [url, options] = fetchMock.mock.calls[0];
    expect(new URL(url).pathname).toBe("/rest/v1/user_public");
    expect(new URL(url).searchParams.get("display_name")).toBe(`eq.${JSON.stringify(name)}`);
    expect(options.cache).toBe("no-store");
    await getNextPowerHour();
    const query = new URL(fetchMock.mock.calls[1][0]).searchParams;
    expect(query.get("starts_at")).toMatch(/^gt\.\d{4}-/);
    expect(query.get("order")).toBe("starts_at.asc");
    expect(query.get("limit")).toBe("1");
  });
});
