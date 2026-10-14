import { ImageResponse } from "next/og";
import { getCompetition } from "@/lib/data";
import { prizePool } from "@/lib/mappers";

export const alt = "Brodie Push-Up Challenge: strict reps, live board";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

export const revalidate = 300;

export default async function OpengraphImage() {
  const comp = await getCompetition().catch(() => null);
  const pool = prizePool(comp?.firstPrize ?? "$500", comp?.drawingPrize ?? "$500");
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: 64,
          background: "#f2ecdf",
          color: "#16120e",
          fontFamily: "sans-serif",
          border: "14px solid #16120e",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <div style={{ width: 64, height: 64, borderRadius: 32, background: "#ff3d97", border: "4px solid #16120e", display: "flex", alignItems: "center", justifyContent: "center" }}>
            <svg width="40" height="40" viewBox="0 0 32 32">
              <path d="M7 21.5h18M10 21.5l3-9.5h6l3 9.5M13 12l3-4 3 4" stroke="#16120e" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" fill="none" />
            </svg>
          </div>
          <div style={{ display: "flex", fontSize: 30, fontWeight: 800, letterSpacing: 4, textTransform: "uppercase", background: "#16120e", color: "#f2ecdf", padding: "6px 14px" }}>
            Brodie Push-Up Challenge
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 150, fontWeight: 900, lineHeight: 0.86, textTransform: "uppercase", letterSpacing: -5 }}>
          <span>Strict reps.</span>
          <span style={{ color: "#ff3d97", textShadow: "8px 6px 0 #2346d8" }}>Live board.</span>
        </div>
        <div style={{ display: "flex", gap: 28, fontSize: 30, fontWeight: 700, textTransform: "uppercase" }}>
          <span>Ends Oct 20</span>
          <span>·</span>
          <span>Judged live on FaceTime</span>
          <span>·</span>
          <span style={{ background: "#ffd83a", padding: "0 10px" }}>{`${pool} in prizes`}</span>
        </div>
      </div>
    ),
    size,
  );
}
