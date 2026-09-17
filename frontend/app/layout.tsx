import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "OrthoCode AI — Coding Control Plane",
  description: "Evidence-first orthopedic coding workflow with licensed 2026 CPT data",
  icons: { icon: "/favicon.svg" }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
