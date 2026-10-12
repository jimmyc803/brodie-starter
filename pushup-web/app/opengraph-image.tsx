import { ImageResponse } from "next/og";
import { getCompetition } from "@/lib/data";

export const alt = "Brodie Push-Up Challenge: strict reps, live board";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export const revalidate = 300;

export default async function OpengraphImage() {
  const firstPrize = await getCompetition().then((c) => c?.firstPrize ?? "$100").catch(() => "$100");
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 72,
          background: "radial-gradient(900px 500px at 90% 0%, rgba(212,255,58,0.22), transparent 60%), #08080a",
          color: "#f6f6f3",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ width: 64, height: 64, borderRadius: 16, background: "#d4ff3a", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="44" height="44" viewBox="0 0 32 32">
              <path d="M7 21.5h18M10 21.5l3-9.5h6l3 9.5M13 12l3-4 3 4" stroke="#0a0b05" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </div>
          <div style={{ fontSize: 34, fontWeight: 800, letterSpacing: 2, textTransform: "uppercase" }}>Brodie Push-Up Challenge</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 140, fontWeight: 900, lineHeight: 0.9, textTransform: "uppercase", letterSpacing: -4 }}>
          <span>Strict reps.</span>
          <span style={{ color: "#d4ff3a" }}>Live board.</span>
        </div>
        <div style={{ display: "flex", gap: 40, fontSize: 30, color: "#b9b9b3" }}>
          <span>One week</span>
          <span>Judged live on FaceTime</span>
          <span style={{ color: "#d4ff3a" }}>{`${firstPrize} to 1st`}</span>
        </div>
      </div>
    ),
    size,
  );
}
