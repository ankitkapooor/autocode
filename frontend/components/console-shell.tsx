"use client";

import { ArrowUpRight, BookOpen, ChartNoAxesCombined, Gauge, Globe2, Home, Menu, RefreshCw, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getOverview, Overview } from "@/lib/api";

const groups = [
  { label: "Workflow", items: [{ href: "/app", label: "Home", icon: Home, exact: true }, { href: "/app/charts", label: "Charts", icon: ChartNoAxesCombined }, { href: "/app/codebook", label: "Codebook", icon: BookOpen }, { href: "/app/evaluation", label: "Evaluation", icon: Gauge }] },
  { label: "Admin", items: [{ href: "/app/admin/reference", label: "Reference data", icon: SlidersHorizontal }] }
];

const titles: Array<[string, string, string]> = [
  ["/app/admin/reference", "Reference data", "System configuration and published codebook controls"],
  ["/app/charts/new", "Upload chart", "Create a chart and start the bounded coding pipeline"],
  ["/app/charts/", "Chart workspace", "Process, review, and release one chart"],
  ["/app/charts", "Charts", "Search every chart and continue its workflow"],
  ["/app/codebook", "Codebook", "Search the active published reference release"],
  ["/app/evaluation", "Evaluation", "Measure coding quality against curated cases"],
  ["/app", "Home", "Today’s operational view"]
];

export function ConsoleShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);
  const [overview, setOverview] = useState<Overview | null>(null);
  const page = titles.find(([path]) => path === "/app" ? pathname === path : pathname.startsWith(path)) ?? titles.at(-1)!;
  useEffect(() => { void getOverview().then(setOverview).catch(() => setOverview(null)); }, [pathname]);
  useEffect(() => { setMenuOpen(false); }, [pathname]);

  return <div className="min-h-screen bg-canvas text-ink">
    <aside className="fixed inset-y-0 left-0 z-40 hidden w-[256px] flex-col bg-navy text-white lg:flex"><ConsoleBrand /><ConsoleNavigation pathname={pathname} /><ConsoleGuard /></aside>
    {menuOpen && <div className="fixed inset-0 z-50 lg:hidden"><button className="absolute inset-0 bg-ink/50 backdrop-blur-sm" aria-label="Close navigation" onClick={() => setMenuOpen(false)} /><aside className="relative flex h-full w-[min(86vw,320px)] flex-col bg-navy text-white shadow-2xl"><div className="absolute right-4 top-5"><button className="grid h-9 w-9 place-items-center rounded-lg border border-white/15" onClick={() => setMenuOpen(false)} aria-label="Close navigation"><X size={18} /></button></div><ConsoleBrand /><ConsoleNavigation pathname={pathname} /><ConsoleGuard /></aside></div>}
    <main className="lg:pl-[256px]"><header className="sticky top-0 z-30 flex min-h-[76px] items-center justify-between gap-4 border-b border-line bg-white/95 px-4 backdrop-blur md:px-7 xl:px-9"><div className="flex min-w-0 items-center gap-3"><button className="icon-button lg:hidden" onClick={() => setMenuOpen(true)} aria-label="Open navigation"><Menu size={18} /></button><div className="min-w-0"><h1 className="truncate text-lg font-semibold tracking-[-0.025em] sm:text-xl">{page[1]}</h1><p className="mt-0.5 hidden truncate text-xs text-slate sm:block">{page[2]}</p></div></div><div className="flex items-center gap-2"><div className={`hidden items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold sm:flex ${overview?.gate === "ready" ? "status-good" : "status-warning"}`}><span className="status-dot" />{overview?.gate === "ready" ? `CPT ${overview.active_release?.name ?? "active"}` : "Coding gate blocked"}</div><button className="icon-button" aria-label="Refresh page" onClick={() => router.refresh()}><RefreshCw size={16} /></button></div></header><div className="mx-auto max-w-[1560px] p-4 pb-24 md:p-6 md:pb-28 xl:p-8 lg:pb-8">{children}</div></main>
  </div>;
}

function ConsoleBrand() { return <div className="flex h-[76px] items-center gap-3 border-b border-white/10 px-6"><Link href="/" className="grid h-9 w-9 place-items-center rounded-xl bg-white text-[12px] font-extrabold tracking-[-0.08em] text-navy">OC</Link><div><div className="text-[15px] font-semibold">OrthoCode AI</div><div className="mt-0.5 text-[10px] font-semibold tracking-[0.13em] text-slate-300">Coding workspace</div></div></div>; }

function ConsoleNavigation({ pathname }: { pathname: string }) { return <nav className="flex-1 overflow-y-auto px-3 py-5" aria-label="Console navigation">{groups.map((group, groupIndex) => <div key={group.label} className={groupIndex ? "mt-7 border-t border-white/10 pt-6" : ""}><div className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.18em] text-slate-400">{group.label}</div><div className="space-y-1">{group.items.map((item) => { const active = item.exact ? pathname === item.href : pathname.startsWith(item.href); return <Link key={item.href} href={item.href} className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${active ? "bg-white/12 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}><item.icon size={17} /><span>{item.label}</span>{active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-cyan-300" />}</Link>; })}</div></div>)}</nav>; }

function ConsoleGuard() { return <div className="border-t border-white/10 p-4"><Link href="/" className="mb-3 flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-semibold text-slate-200 transition hover:bg-white/10 hover:text-white"><Globe2 size={16} /><span>Public website</span><ArrowUpRight size={14} className="ml-auto" /></Link><div className="rounded-xl bg-white/5 p-3"><div className="flex items-center gap-2 text-xs font-semibold"><ShieldCheck size={15} className="text-cyan-300" />Human review required</div><p className="mt-2 text-[11px] leading-4 text-slate-300">Autonomy stays off until measured thresholds and provider controls pass.</p></div></div>; }
