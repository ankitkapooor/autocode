import type { Metadata } from "next";

import { ConsoleShell } from "@/components/console-shell";

export const metadata: Metadata = { title: "Coding workspace" };

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
