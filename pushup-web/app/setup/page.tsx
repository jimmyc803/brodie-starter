import { SetupDiagram } from "@/components/setup-diagram";

export const metadata = { title: "Setup | Brodie Push-Up Challenge" };

const checklist = [
  "Phone on the floor or a low surface, 6–8 feet to your SIDE.",
  "Phone in landscape (turned sideways).",
  "Your whole body is visible, head to feet. Check the preview.",
  "Good light on you. No bright window or lamp behind you.",
  "Only you in frame. No one walking behind.",
  "Clear floor, enough room to lie flat. Shoes or grippy socks.",
];

export default function SetupPage() {
  return (
    <div className="space-y-6">
      <h1 className="font-display text-5xl uppercase leading-none">
        Set up in <span className="text-accent">30 seconds</span>
      </h1>
      <SetupDiagram />
      <section>
        <h2 className="font-display text-2xl uppercase text-accent">Checklist</h2>
        <ul className="mt-2 space-y-2">
          {checklist.map((c) => (
            <li key={c} className="flex gap-3 rounded-lg border border-hairline bg-surface p-3">
              <span aria-hidden className="font-bold text-accent">
                ✓
              </span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      </section>
      <p className="text-sm text-ink-2">
        Setup time happens inside your 3:00 counting window, so get it right before you connect.
      </p>
    </div>
  );
}
