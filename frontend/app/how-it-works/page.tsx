import type { Metadata } from "next";
import { ArrowDown, ArrowRight, Braces, Check, FileText, GitBranch, Scale, Search, ShieldCheck, Sparkles, UserCheck } from "lucide-react";
import Link from "next/link";

import { MarketingFooter, MarketingHeader } from "@/components/marketing-shell";

export const metadata: Metadata = { title: "How it works", description: "A technical walkthrough of OrthoCode AI's evidence-first, bounded coding architecture." };

const pipeline = [
  [FileText, "De-identified document", "A PDF enters the development workflow only after the operator confirms it is de-identified.", "Immutable pages and evidence spans"],
  [Sparkles, "Atomic clinical facts", "OpenAI Structured Outputs turns bounded chart chunks into clinical facts tied to evidence.", "No code or modifier selection"],
  [Check, "JEV fact validation", "The bounded engine classifies facts as performed, planned, historical, ruled out or unsupported.", "Typed choices or abstention"],
  [Search, "Candidate retrieval", "The service date and validated facts retrieve candidates from the active licensed codebook.", "No free-form candidate generation"],
  [GitBranch, "Bounded coding decisions", "JEV selects procedures, diagnoses, modifiers and relationships only among retrieved candidates.", "Probability and evidence retained"],
  [Braces, "Coding-line assembly", "Python assembles supported choices into traceable coding lines and performs unit arithmetic.", "Source and citations preserved"],
  [Scale, "Deterministic enforcement", "Active-code, NCCI, MUE, add-on and fee-schedule checks apply as authoritative rules.", "Hard constraints cannot be overruled"],
  [ShieldCheck, "Confidence calibration", "The weakest contributing decision, abstentions, warnings and hard failures control routing.", "Routing signal, not clinical certainty"],
  [UserCheck, "Human review", "A coder inspects evidence and rules, then accepts or corrects the immutable proposal.", "Append-only audit trail"],
] as const;

export default function HowItWorksPage() {
  return <div className="min-h-screen bg-white text-ink"><MarketingHeader /><main><section className="bg-marketing px-5 pb-20 pt-16 text-white sm:px-8 sm:pb-24 sm:pt-20 lg:px-12"><div className="mx-auto max-w-5xl"><div className="marketing-kicker"><span /> Architecture, without the black box</div><h1 className="mt-7 max-w-4xl text-5xl font-semibold leading-[1.02] tracking-[-0.05em] sm:text-7xl">From chart evidence to a reviewable coding decision.</h1><p className="mt-7 max-w-3xl text-lg leading-8 text-slate-300">The pipeline deliberately separates generative extraction, bounded judgment, deterministic rules and human control. Each layer can do its job—and no more.</p></div></section><section className="bg-warm px-5 py-20 sm:px-8 sm:py-28 lg:px-12"><div className="mx-auto max-w-5xl"><div className="section-kicker">Full data flow</div><h2 className="marketing-h2 mt-5 max-w-3xl">One trace, from source document to signed review.</h2><div className="mt-14 space-y-3">{pipeline.map(([Icon, title, body, boundary], index) => <div key={title}><details className="pipeline-disclosure group" open={index < 3}><summary><span className="pipeline-number">{String(index + 1).padStart(2, "0")}</span><span className="grid h-10 w-10 place-items-center rounded-xl bg-sky-50 text-blue"><Icon size={19} /></span><span className="min-w-0 flex-1"><span className="block text-base font-semibold text-ink">{title}</span><span className="mt-1 block text-sm text-slate">{boundary}</span></span><span className="faq-plus" /></summary><div className="ml-[72px] border-t border-line pb-5 pt-4 text-sm leading-7 text-slate sm:ml-[128px]">{body}</div></details>{index < pipeline.length - 1 && <ArrowDown size={16} className="mx-auto my-3 text-slate" />}</div>)}</div></div></section><section className="bg-white px-5 py-20 sm:px-8 sm:py-24 lg:px-12"><div className="mx-auto flex max-w-5xl flex-col justify-between gap-8 rounded-3xl bg-navy p-8 text-white sm:p-12 lg:flex-row lg:items-center"><div><div className="text-xs font-bold uppercase tracking-[0.16em] text-cyan-300">A bounded system can still be wrong</div><h2 className="mt-4 max-w-2xl text-3xl font-semibold tracking-[-0.04em]">The difference is that it cannot be unaccountably wrong.</h2></div><Link className="marketing-primary shrink-0" href="/app">Open demo <ArrowRight size={16} /></Link></div></section></main><MarketingFooter /></div>;
}
