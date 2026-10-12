import type { Metadata, Viewport } from "next";
import { Barlow_Condensed, Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { Logo, MobileJoinBar, SiteNav } from "@/components/site-chrome";
import { getCompetition } from "@/lib/data";
import { smsLink } from "@/lib/format";
import "./globals.css";

const display = Barlow_Condensed({
  subsets: ["latin"],
  weight: ["700", "800"],
  style: ["normal", "italic"],
  variable: "--font-barlow",
  display: "swap",
});
const sans = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const mono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["700"],
  variable: "--font-jbmono",
  display: "swap",
  preload: false,
});

const description = "One week. Strict push-ups on FaceTime, judged live. Climb the board, grow your Brodie.";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Brodie Push-Up Challenge", template: "%s | Brodie Push-Up Challenge" },
  description,
  applicationName: "Brodie Push-Ups",
  openGraph: {
    type: "website",
    siteName: "Brodie Push-Up Challenge",
    title: "Brodie Push-Up Challenge",
    description,
  },
  twitter: { card: "summary_large_image", title: "Brodie Push-Up Challenge", description },
};

export const viewport: Viewport = {
  themeColor: "#08080a",
  colorScheme: "dark",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const comp = await getCompetition();
  const joinHref = smsLink(comp?.brodieNumber ?? null);

  return (
    <html lang="en" className={`dark ${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="stage grain min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only z-50 rounded-full bg-accent px-4 py-2 font-semibold text-on-accent focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <header className="sticky top-0 z-30 border-b border-hairline bg-canvas/75 backdrop-blur-xl">
          <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-4 py-1.5 sm:px-6">
            <Logo />
            <SiteNav joinHref={joinHref} />
          </nav>
        </header>
        <main id="main" className="mx-auto max-w-6xl px-4 pt-6 pb-28 sm:px-6 sm:pt-10 sm:pb-16">
          {children}
        </main>
        <footer className="border-t border-hairline">
          <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 pt-8 pb-32 text-sm text-ink-3 sm:flex-row sm:items-center sm:justify-between sm:px-6 sm:pb-10">
            <p>No video or audio is stored. 18+, US only. Display names only, never phone numbers.</p>
            <ul className="flex gap-1">
              {[
                ["/join", "Join"],
                ["/rules", "Rules"],
                ["/setup", "Setup"],
              ].map(([href, label]) => (
                <li key={href}>
                  <Link href={href} className="inline-flex min-h-11 items-center px-2 text-ink-2 hover:text-ink">
                    {label}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </footer>
        <MobileJoinBar joinHref={joinHref} />
      </body>
    </html>
  );
}
