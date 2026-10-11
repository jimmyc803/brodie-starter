// The 1080 x 1920 recap card as Satori JSX (flexbox only; every multi-child div sets display: flex).
// Shown as video on the FaceTime call, sent as the iMessage image and used as the recap link's preview.
import { SCORE_GRADIENT_CSS, UNTRAINED } from "@/lib/body/neon";
import { VIEWBOX } from "@/lib/body/shapes";
import { bodySvgDataUri } from "@/lib/body/svg";
import { COLORS } from "@/lib/contract";
import type { RecapCard } from "@/lib/recap-image/model";

export const CARD_WIDTH = 1080;
export const CARD_HEIGHT = 1920;

const BG = "#09090b";
const PANEL = "#18181b";
const BORDER = "#27272a";
const TEXT = "#fafafa";
const MUTED = "#a1a1aa";
const FAINT = "#71717a";

const BODY_W = 400;
const BODY_H = Math.round((BODY_W * (VIEWBOX.height + 12)) / 112); // body viewBox plus a 6-unit glow margin

function Body({ side, card }: { side: "front" | "back"; card: RecapCard }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      {/* eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text */}
      <img src={bodySvgDataUri(side, card.fills, { width: BODY_W, id: side })} width={BODY_W} height={BODY_H} />
      <div style={{ display: "flex", marginTop: 12, fontSize: 30, letterSpacing: 8, color: FAINT }}>
        {side.toUpperCase()}
      </div>
    </div>
  );
}

export function RecapCardImage({ card }: { card: RecapCard }) {
  const accent = { focus: COLORS.red, solid: COLORS.green, empty: COLORS.gray }[card.focusKind];
  const kicker = { focus: "FOCUS NEXT", solid: "NICE WORK", empty: "NO REPS COUNTED" }[card.focusKind];
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        backgroundColor: BG,
        backgroundImage: "radial-gradient(circle at 50% 42%, #1c1c22 0%, #09090b 62%)",
        color: TEXT,
        padding: "84px 64px 60px",
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", fontSize: 30, letterSpacing: 10, color: COLORS.green }}>
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
          textAlign: "center",
        }}
      >
        {card.title}
      </div>
      <div style={{ display: "flex", marginTop: 20, fontSize: 38, color: MUTED, textAlign: "center" }}>{card.subtitle}</div>

      {/* Bodies */}
      <div style={{ display: "flex", justifyContent: "center", marginTop: 56 }}>
        <Body side="front" card={card} />
        <div style={{ display: "flex", width: 40 }} />
        <Body side="back" card={card} />
      </div>

      {/* Legend: the score bar (team colors, blended) and "not trained" */}
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginTop: 30, fontSize: 26, color: MUTED }}>
        <div style={{ display: "flex", width: 640, height: 18, borderRadius: 9, backgroundImage: SCORE_GRADIENT_CSS }} />
        <div style={{ display: "flex", width: 640, justifyContent: "space-between", marginTop: 10 }}>
          <div style={{ display: "flex" }}>Needs work</div>
          <div style={{ display: "flex" }}>Room to improve</div>
          <div style={{ display: "flex" }}>Solid</div>
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
              border: `2px solid ${BORDER}`,
              borderRadius: 28,
            }}
          >
            <div style={{ display: "flex", fontSize: 76, letterSpacing: -2, lineHeight: 1 }}>{s.value}</div>
            <div style={{ display: "flex", marginTop: 14, fontSize: 26, letterSpacing: 3, color: MUTED }}>
              {s.label.toUpperCase()}
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
          border: `2px solid ${BORDER}`,
          borderRadius: 28,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", fontSize: 26, letterSpacing: 4, color: accent }}>
          <div style={{ display: "flex", width: 14, height: 14, borderRadius: 7, backgroundColor: accent, marginRight: 14 }} />
          {kicker}
        </div>
        <div style={{ display: "flex", marginTop: 12, fontSize: card.focusLine.length > 34 ? 42 : 50, textAlign: "center" }}>
          {card.focusLine}
        </div>
      </div>

      {/* Footer */}
      <div style={{ display: "flex", marginTop: "auto", paddingTop: 24, fontSize: 24, color: FAINT }}>{card.footer}</div>
    </div>
  );
}
