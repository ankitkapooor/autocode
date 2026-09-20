import { ConsoleShell } from "@/components/console-shell";

export default function AppTemplate({ children }: { children: React.ReactNode }) {
  return <ConsoleShell>{children}</ConsoleShell>;
}
