import { ArrowUpRight } from "lucide-react";
import Link from "next/link";

export function Logo({ dark = false }: { dark?: boolean }) {
  return <Link href="/" className={`inline-flex items-center gap-3 font-semibold tracking-[-0.02em] ${dark ? "text-white" : "text-ink"}`}><span className={`grid h-9 w-9 place-items-center rounded-xl text-[12px] font-extrabold tracking-[-0.08em] ${dark ? "bg-white text-navy" : "bg-navy text-white"}`}>OC</span><span>OrthoCode AI</span></Link>;
}

export function MarketingHeader() {
  return <header className="border-b border-white/10 bg-marketing px-5 sm:px-8 lg:px-12"><div className="mx-auto flex h-20 max-w-7xl items-center justify-between"><Logo dark /><nav className="hidden items-center gap-8 text-sm text-slate-300 md:flex" aria-label="Marketing navigation"><Link href="/#architecture">How it works</Link><Link href="/security">Security</Link></nav><Link className="rounded-full bg-cyan-300 px-4 py-2 text-sm font-semibold text-navy transition hover:bg-cyan-200" href="/app">Open demo</Link></div></header>;
}

export function MarketingFooter() {
  return <footer className="bg-marketing px-5 py-10 text-slate-400 sm:px-8 lg:px-12"><div className="mx-auto flex max-w-7xl flex-col justify-between gap-8 border-t border-white/10 pt-8 sm:flex-row sm:items-center"><Logo dark /><div className="flex flex-wrap gap-6 text-sm"><Link href="/how-it-works">Architecture</Link><Link href="/security">Security</Link><Link className="inline-flex items-center gap-1" href="/app">Open demo <ArrowUpRight size={13} /></Link></div><p className="text-xs">Interactive demo · de-identified data only</p></div></footer>;
}
