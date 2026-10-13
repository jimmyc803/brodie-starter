import { ImageResponse } from "next/og";

export const size = { width: 180, height: 180 };
export const contentType = "image/png";

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", background: "#ff3d97" }}>
        <svg width="120" height="120" viewBox="0 0 32 32">
          <path d="M7 21.5h18M10 21.5l3-9.5h6l3 9.5M13 12l3-4 3 4" stroke="#16120e" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
      </div>
    ),
    size,
  );
}
