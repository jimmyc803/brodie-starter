// The 1080 x 1920 recap card as Satori JSX (flexbox only; every multi-child div sets display: flex).
// Shown as video on the FaceTime call, sent as the iMessage image and used as the recap link's preview.
import { UNTRAINED } from "@/lib/body/neon";
import { VIEWBOX } from "@/lib/body/shapes";
import { bodySvgDataUri } from "@/lib/body/svg";
import { COLORS } from "@/lib/contract";
import { RANKS } from "@/lib/ranks";
import type { RecapCard } from "@/lib/recap-image/model";

export const CARD_WIDTH = 1080;
export const CARD_HEIGHT = 1920;

const BG = "#000000";
const PANEL = "#1c1c1e";
const TEXT = "#f5f5f7";
const MUTED = "#a1a1a6";
const FAINT = "#86868b";
const FONT = '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif';

const BODY_W = 370;
const BODY_H = Math.round((BODY_W * (VIEWBOX.height + 12)) / 112); // body viewBox plus a 6-unit glow margin

function Body({ side, card }: { side: "front" | "back"; card: RecapCard }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text */}
      <img src={bodySvgDataUri(side, card.fills, { width: BODY_W, id: side })} width={BODY_W} height={BODY_H} />
      <div style={{ display: "flex", marginTop: 12, fontSize: 28, color: FAINT }}>
        {side === "front" ? "Front" : "Back"}
      </div>
    </div>
  );
}

export function RecapCardImage({ card }: { card: RecapCard }) {
  const accent = { focus: COLORS.red, solid: COLORS.green, empty: COLORS.gray }[card.focusKind];
  const kicker = { focus: "Focus next", solid: "Nice work", empty: "No reps counted" }[card.focusKind];
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        backgroundColor: BG,
        fontFamily: FONT,
        color: TEXT,
        padding: "64px 64px 48px",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", fontSize: 32, fontWeight: 600, color: COLORS.green }}>
        <div style={{ display: "flex", width: 16, height: 16, borderRadius: 8, backgroundColor: COLORS.green, marginRight: 18 }} />
        {card.kicker}
      </div>
      <div
        style={{
          display: "flex",
          marginTop: 28,
          fontSize: card.title.length <= 15 ? 120 : card.title.length <= 19 ? 100 : 80,
          lineHeight: 1.05,
          letterSpacing: -3,
          fontWeight: 700,
          color: "#ffffff",
          textAlign: "center",
        }}
      >
        {card.title}
      </div>
      <div style={{ display: "flex", marginTop: 16, fontSize: 38, color: MUTED, letterSpacing: -0.5, textAlign: "center" }}>{card.subtitle}</div>

      {/* Today's rank */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          marginTop: 28,
          padding: "14px 34px",
          borderRadius: 999,
          border: `3px solid ${card.rank.color}`,
          fontSize: 40,
          fontWeight: 600,
          color: card.rank.color,
        }}
      >
        <div style={{ display: "flex", fontSize: 26, color: MUTED, marginRight: 20 }}>Rank</div>
        {card.rank.name.toUpperCase()}
      </div>

      {/* Bodies */}
      <div style={{ display: "flex", justifyContent: "center", marginTop: 24 }}>
        <Body side="front" card={card} />
        <div style={{ display: "flex", width: 40 }} />
        <Body side="back" card={card} />
      </div>

      {/* Legend: the rank ladder (each tier in the color its muscles are painted) and "not trained" */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 30, fontSize: 26, color: MUTED }}>
        <div style={{ display: "flex", width: 840, flexWrap: "wrap", rowGap: 12, fontSize: 23 }}>
          {RANKS.map((r) => (
            <div key={r.key} style={{ display: "flex", width: 210, alignItems: "center" }}>
              <div style={{ display: "flex", width: 18, height: 18, borderRadius: 3, marginRight: 10, backgroundColor: r.color }} />
              {r.name}
            </div>
          ))}
        </div>
        <div style={{ display: "flex", alignItems: "center", marginTop: 14 }}>
          <div style={{ display: "flex", width: 22, height: 22, borderRadius: 11, backgroundColor: UNTRAINED, marginRight: 12 }} />
          Not trained this session
        </div>
      </div>

      {/* Stats */}
      <div style={{ display: "flex", width: "100%", marginTop: 36 }}>
        {card.stats.map((s, i) => (
          <div
            key={s.label}
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              flex: 1,
              padding: "28px 0 24px",
              marginLeft: i ? 20 : 0,
              backgroundColor: PANEL,
              borderRadius: 28,
            }}
          >
            <div style={{ display: "flex", fontSize: 76, letterSpacing: -2, lineHeight: 1, fontWeight: 700, color: "#ffffff" }}>{s.value}</div>
            <div style={{ display: "flex", marginTop: 14, fontSize: 28, color: MUTED }}>
              {s.label}
            </div>
          </div>
        ))}
      </div>

      {/* Focus next */}
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          width: "100%",
          marginTop: 20,
          padding: "26px 36px 30px",
          backgroundColor: PANEL,
          borderRadius: 28,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 28, fontWeight: 600, color: accent }}>
          <div style={{ display: "flex", width: 14, height: 14, borderRadius: 7, backgroundColor: accent, marginRight: 14 }} />
          {kicker}
        </div>
        <div style={{ display: "flex", marginTop: 12, fontSize: card.focusLine.length > 34 ? 42 : 50, fontWeight: 600, letterSpacing: -1, textAlign: "center" }}>
          {card.focusLine}
        </div>
      </div>

      {/* Footer */}
      <div style={{ display: "flex", marginTop: "auto", paddingTop: 24, fontSize: 24, color: FAINT }}>{card.footer}</div>
    </div>
  );
}
