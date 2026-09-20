import {
  ArrowRight,
  Check,
  FileCheck2,
  Fingerprint,
  LockKeyhole,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  TriangleAlert
} from "lucide-react";
import Link from "next/link";

import { MarketingFooter, MarketingHeader } from "@/components/marketing-shell";

const layers = [
  {
    number: "01",
    eyebrow: "Extract",
    title: "Turn chart text into cited facts",
    body: "A language model structures the chart into atomic clinical facts, each linked to the evidence that supports it.",
    boundary: "It cannot select a code, modifier, or unit.",
    icon: Sparkles
  },
  {
    number: "02",
    eyebrow: "Decide",
    title: "Choose from bounded candidates",
    body: "TypeSafe JEV weighs only candidates retrieved from the active, licensed and versioned codebook release.",
    boundary: "It cannot invent a code outside the licensed release.",
    icon: SearchCheck
  },
  {
    number: "03",
    eyebrow: "Enforce",
    title: "Apply rules that cannot be overruled",
    body: "Deterministic Python checks enforce active-code, NCCI, MUE, add-on and fee-schedule constraints.",
    boundary: "No model can override a hard CMS rule.",
    icon: ShieldCheck
  }
];

const trust = [
  [LockKeyhole, "Fails closed", "If the decision engine is unavailable or unsure, the chart is routed to a human. No silent fallback, no fabricated lines."],
  [Fingerprint, "Evidence stays attached", "Every proposed line retains its cited chart evidence and decision trace for reviewer and audit use."],
  [FileCheck2, "Humans remain in control", "Autonomous coding is disabled by default. Corrections are append-only and feed controlled evaluation."],
  [ShieldCheck, "Bounded data sharing", "Development is de-identified only; JEV receives bounded evidence spans and PHI sharing is off by default."]
] as const;

const faqs = [
  ["Is this autonomous coding?", "No, not by default. Autonomous submission is disabled unless explicitly enabled and every measured threshold is met; a human reviews every chart today."],
  ["What happens if the AI is unsure?", "The chart fails closed to human review. The system preserves the evidence and candidates it has, but it does not guess to avoid an empty result."],
  ["Where do the codes come from?", "Only from the active, licensed and versioned CPT, HCPCS and ICD-10 codebook release for the service date—never from free-form generation."],
  ["What is JEV?", "TypeSafe JEV is a bounded decision engine. It chooses among retrieved candidates and can abstain; it never generates a new billing code. Its probabilities are routing signals, not substitutes for coder judgment."]
];

export default function LandingPage() {
  // TODO(marketing-review): Product, security, and compliance copy requires owner sign-off before public launch.
  return (
    <div className="marketing-page">
      <MarketingHeader />
      <main>
        <section className="relative overflow-hidden px-5 pb-20 pt-16 sm:px-8 sm:pb-28 sm:pt-24 lg:px-12">
          <div className="hero-glow" aria-hidden="true" />
          <div className="mx-auto max-w-7xl">
            <div className="max-w-4xl">
              <div className="marketing-kicker"><span /> Built for orthopedic professional coding</div>
              <h1 className="mt-7 max-w-4xl text-balance text-5xl font-semibold leading-[0.98] tracking-[-0.055em] text-white sm:text-6xl lg:text-[82px]">Every code traces back to a chart.</h1>
              <p className="mt-7 max-w-2xl text-pretty text-lg leading-8 text-slate-300 sm:text-xl">OrthoCode AI extracts clinical facts, makes bounded coding decisions, and enforces CMS requirements deterministically—so every proposed line has a defensible trail.</p>
              <div className="mt-9 flex flex-col items-start gap-4 sm:flex-row sm:items-center">
                <Link className="marketing-primary" href="/request-access">Request access <ArrowRight size={17} /></Link>
                <p className="flex items-center gap-2 text-sm text-slate-400"><Check size={16} className="text-cyan-300" /> In development · human review is mandatory</p>
              </div>
            </div>
            <div className="mt-20 grid border-y border-white/10 sm:grid-cols-3">
              {[["Licensed", "Versioned codebooks"], ["Bounded", "Typed decisions"], ["Deterministic", "CMS rule enforcement"]].map(([value, label]) => (
                <div key={value} className="border-b border-white/10 py-6 last:border-0 sm:border-b-0 sm:border-r sm:px-8 sm:first:pl-0 sm:last:border-r-0"><div className="text-2xl font-semibold tracking-[-0.04em] text-white">{value}</div><div className="mt-1 text-sm text-slate-400">{label}</div></div>
              ))}
            </div>
          </div>
        </section>

        <section className="bg-warm px-5 py-20 text-ink sm:px-8 sm:py-28 lg:px-12" id="problem">
          <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-[0.7fr_1.3fr] lg:gap-24">
            <div><div className="section-kicker">The problem</div><h2 className="marketing-h2 mt-5">Orthopedic coding leaves very little room for a plausible guess.</h2></div>
            <div className="lg:pt-9">
              <p className="text-pretty text-xl leading-9 text-slate">Multi-procedure claims, NCCI bundling edits, and modifier disputes make orthopedic surgical billing unusually exposed to denials and audits.</p>
              <div className="mt-9 grid gap-4 sm:grid-cols-3">{[["NCCI", "Bundling edits"], ["−59 / X{EPSU}", "Modifier disputes"], ["MUE", "Unit limits"]].map(([title, text]) => <div key={title} className="rounded-2xl border border-line bg-white p-5"><div className="font-mono text-sm font-semibold text-blue">{title}</div><div className="mt-2 text-sm font-medium text-slate">{text}</div></div>)}</div>
              <p className="mt-9 text-base leading-7 text-slate">This is a domain where hard rules and complete evidence trails matter more than raw automation speed. The architecture should reflect that.</p>
            </div>
          </div>
        </section>

        <section className="bg-white px-5 py-20 text-ink sm:px-8 sm:py-28 lg:px-12" id="architecture">
          <div className="mx-auto max-w-7xl">
            <div className="max-w-3xl"><div className="section-kicker">How it works</div><h2 className="marketing-h2 mt-5">Three layers. Each with a strict boundary.</h2><p className="mt-5 text-lg leading-8 text-slate">JEV—TypeSafe&apos;s bounded decision engine—sits between fact extraction and deterministic rule enforcement. That separation is the safety model.</p></div>
            <div className="mt-14 grid gap-px overflow-hidden rounded-3xl border border-line bg-line lg:grid-cols-3">
              {layers.map((layer) => <article key={layer.number} className="group bg-white p-7 sm:p-9"><div className="flex items-center justify-between"><div className="grid h-11 w-11 place-items-center rounded-xl bg-sky-50 text-blue"><layer.icon size={21} /></div><span className="font-mono text-xs text-slate">{layer.number}</span></div><div className="mt-8 text-xs font-bold uppercase tracking-[0.18em] text-teal">{layer.eyebrow}</div><h3 className="mt-3 text-xl font-semibold tracking-[-0.025em]">{layer.title}</h3><p className="mt-4 text-sm leading-6 text-slate">{layer.body}</p><div className="mt-7 border-t border-line pt-5"><p className="flex gap-2 text-sm font-semibold leading-6 text-ink"><TriangleAlert size={16} className="mt-1 shrink-0 text-amber" />{layer.boundary}</p></div></article>)}
            </div>
            <div className="mt-8 flex justify-end"><Link className="text-link" href="/how-it-works">See the full architecture <ArrowRight size={15} /></Link></div>
          </div>
        </section>

        <section className="bg-ink px-5 py-20 text-white sm:px-8 sm:py-28 lg:px-12" id="trust">
          <div className="mx-auto max-w-7xl"><div className="grid gap-12 lg:grid-cols-[0.75fr_1.25fr] lg:gap-24"><div><div className="section-kicker section-kicker-dark">Trust by design</div><h2 className="marketing-h2 mt-5 text-white">The system is designed to make uncertainty visible.</h2><p className="mt-5 text-base leading-7 text-slate-300">No inflated autonomy claim. No mystery score standing in for evidence. No model opinion overriding a hard rule.</p><Link className="marketing-secondary mt-8" href="/security">Read the security posture <ArrowRight size={16} /></Link></div><div className="grid gap-px overflow-hidden rounded-3xl border border-white/10 bg-white/10 sm:grid-cols-2">{trust.map(([Icon, title, body]) => <article key={title} className="bg-ink p-7"><Icon size={20} className="text-cyan-300" /><h3 className="mt-5 text-lg font-semibold">{title}</h3><p className="mt-3 text-sm leading-6 text-slate-300">{body}</p></article>)}</div></div></div>
        </section>

        <section className="bg-white px-5 py-20 text-ink sm:px-8 sm:py-28 lg:px-12" id="faq">
          <div className="mx-auto max-w-5xl"><div className="section-kicker">Questions, answered plainly</div><h2 className="marketing-h2 mt-5">What a careful coding team should ask.</h2><div className="mt-12 divide-y divide-line border-y border-line">{faqs.map(([question, answer]) => <details key={question} className="faq-row group"><summary><span>{question}</span><span className="faq-plus" /></summary><p>{answer}</p></details>)}</div></div>
        </section>

        <section className="bg-warm px-5 py-20 text-ink sm:px-8 sm:py-28 lg:px-12"><div className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-8 rounded-3xl bg-navy p-8 text-white sm:p-12 lg:flex-row lg:items-end"><div className="max-w-2xl"><div className="text-xs font-bold uppercase tracking-[0.18em] text-cyan-300">Built carefully, not loudly</div><h2 className="mt-5 text-3xl font-semibold tracking-[-0.04em] sm:text-5xl">Bring evidence and rules into the same review.</h2></div><Link className="marketing-primary shrink-0" href="/request-access">Request access <ArrowRight size={17} /></Link></div></section>
      </main>
      <MarketingFooter />
    </div>
  );
}
