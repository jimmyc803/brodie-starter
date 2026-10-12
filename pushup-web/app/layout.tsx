import type { Metadata, Viewport } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Brodie Push-Up Challenge",
  description: "One week. Strict push-ups. Live leaderboard.",
};

export const viewport: Viewport = { themeColor: "#0a0a0b", colorScheme: "dark" };

const nav = [
  { href: "/", label: "Leaderboard" },
  { href: "/join", label: "Join" },
  { href: "/rules", label: "Rules" },
  { href: "/setup", label: "Setup" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        <header className="border-b border-hairline">
          <nav
            aria-label="Main"
            className="mx-auto flex max-w-3xl items-center justify-between gap-2 px-4 py-3"
          >
            <Link href="/" className="font-display text-xl uppercase tracking-wide text-accent">
              Brodie Push-Ups
            </Link>
            <ul className="flex gap-4 text-sm font-semibold">
              {nav.slice(1).map((n) => (
                <li key={n.href}>
                  <Link href={n.href} className="py-2 hover:text-accent">
                    {n.label}
                  </Link>
                </li>
              ))}
            </ul>
          </nav>
        </header>
        <main className="mx-auto max-w-3xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-3xl px-4 py-8 text-xs text-ink-2">
          No video or audio is stored. 18+, US only.
        </footer>
      </body>
    </html>
  );
}
