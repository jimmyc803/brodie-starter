import type { Metadata, Viewport } from "next";
import { Anton, Archivo, Space_Mono } from "next/font/google";
import Link from "next/link";
import { Logo, MobileJoinBar, SiteNav, Ticker } from "@/components/site-chrome";
import { Brodie } from "@/components/mascot";
import { VisitBeacon } from "@/components/visit-beacon";
import { getCompetition } from "@/lib/data";
import { smsLink } from "@/lib/format";
import "./globals.css";

const display = Anton({ subsets: ["latin"], weight: "400", variable: "--font-anton", display: "swap" });
const sans = Archivo({ subsets: ["latin"], variable: "--font-archivo", display: "swap" });
const mono = Space_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-spacemono",
  display: "swap",
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
  themeColor: "#16120e",
  colorScheme: "light",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const comp = await getCompetition();
  const joinHref = smsLink(comp?.brodieNumber ?? null);

  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${mono.variable}`}>
      <body className="stage grain min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only z-50 border-2 border-ink bg-yellow px-4 py-2 font-semibold text-ink focus:not-sr-only focus:fixed focus:top-3 focus:left-3"
        >
          Skip to content
        </a>
        <Ticker firstPrize={comp?.firstPrize ?? "$500"} />
        <header className="sticky top-0 z-30 border-b-2 border-ink bg-canvas/95 backdrop-blur-sm">
          <nav aria-label="Main" className="mx-auto flex max-w-6xl items-center justify-between gap-2 px-4 py-2 sm:px-6">
            <Logo />
            <SiteNav joinHref={joinHref} />
          </nav>
        </header>
        <main id="main" className="mx-auto max-w-6xl px-4 pt-6 pb-12 sm:px-6 sm:pt-10 sm:pb-16">
          {children}
        </main>
        <footer className="relative mt-8 overflow-hidden border-t-2 border-ink bg-ink text-canvas">
          <div className="mx-auto max-w-6xl px-4 pt-10 pb-32 sm:px-6 sm:pb-10">
            <div className="flex items-end justify-between gap-4">
              <p aria-hidden className="font-display text-[clamp(4rem,19vw,13rem)] leading-[0.8] uppercase">
                Brodie<span className="text-pink">.</span>
              </p>
              <Brodie size={200} className="-mb-10 h-auto w-24 shrink-0 sm:w-40 lg:w-48" />
            </div>
            <div className="mt-6 flex flex-col gap-4 border-t border-canvas/25 pt-5 sm:flex-row sm:items-center sm:justify-between">
              <p className="max-w-md font-mono text-xs leading-relaxed text-canvas/70 uppercase">
                No video or audio is stored. 18+, US only. Display names only, never phone numbers.
                <span className="mt-2 block text-canvas/50">A Beat Muse student project at the University of Pennsylvania.</span>
              </p>
              <ul className="flex flex-wrap gap-x-1">
                {[
                  ["/join", "Join"],
                  ["/how-it-works", "How it works"],
                  ["/rules", "Rules"],
                  ["/setup", "Setup"],
                  ["/privacy", "Privacy"],
                  ["/terms", "Terms"],
                ].map(([href, label]) => (
                  <li key={href}>
                    <Link
                      href={href}
                      className="inline-flex min-h-11 items-center px-2 font-mono text-sm font-bold uppercase text-canvas underline decoration-pink decoration-2 underline-offset-4 hover:text-pink"
                    >
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </footer>
        <MobileJoinBar joinHref={joinHref} />
        <VisitBeacon />
      </body>
    </html>
  );
}
