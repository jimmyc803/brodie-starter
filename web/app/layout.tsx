import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter is the fallback after the system SF stack (see --font-sans in globals.css).
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// Absolute base for Open Graph image URLs (iMessage link previews need them). Vercel sets the production host.
const siteUrl = process.env.VERCEL_PROJECT_PRODUCTION_URL
  ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}`
  : "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: "Brodie for Coaches",
  description: "Your coach writes the program. Brodie runs the workout over FaceTime.",
};

export const viewport: Viewport = {
  themeColor: "#000000",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} dark h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
