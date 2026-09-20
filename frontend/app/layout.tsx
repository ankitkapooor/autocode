import type { Metadata } from "next";
import { IBM_Plex_Mono, Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans", display: "swap" });
const plexMono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "600"], variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "OrthoCode AI — Evidence-first orthopedic coding", template: "%s · OrthoCode AI" },
  description: "Evidence-first orthopedic coding with bounded decisions, licensed codebooks, deterministic CMS rules, and mandatory human review.",
  icons: { icon: "/favicon.svg" }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${inter.variable} ${plexMono.variable}`}>{children}</body>
    </html>
  );
}
