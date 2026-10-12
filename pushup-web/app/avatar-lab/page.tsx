import * as React from "react";
import { Avatar } from "../../components/brodie-avatar";

export default function AvatarLabPage() {
  return (
    <main style={{ minHeight: "100vh", background: "#15151F", color: "#F3EFE5", padding: 24, fontFamily: "sans-serif" }}>
      <h1>Brodie avatar lab</h1>
      <p>Ten levels. Chest, triceps, front delts and core grow as you progress.</p>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 20 }}>
        {Array.from({ length: 10 }, (_, index) => index + 1).map((level) => (
          <figure key={level} style={{ margin: 0, padding: 16, background: "#242434", borderRadius: 16, textAlign: "center" }}>
            <Avatar level={level} size={160} />
            <Avatar level={level} size={96} pose="idle" />
            <figcaption>Level {level}</figcaption>
          </figure>
        ))}
      </div>
    </main>
  );
}
