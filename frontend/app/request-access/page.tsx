import type { Metadata } from "next";

import { AccessForm } from "@/components/access-form";
import { MarketingFooter, MarketingHeader } from "@/components/marketing-shell";

export const metadata: Metadata = { title: "Request access", description: "Request access to the OrthoCode AI development preview." };

export default function RequestAccessPage() {
  return <div className="min-h-screen bg-warm text-ink"><MarketingHeader /><main className="px-5 py-14 sm:px-8 sm:py-20 lg:px-12"><div className="mx-auto grid max-w-6xl gap-12 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20"><div className="pt-4"><div className="section-kicker">Development access</div><h1 className="mt-6 text-4xl font-semibold leading-[1.05] tracking-[-0.05em] sm:text-6xl">See the workflow before the claims.</h1><p className="mt-6 text-lg leading-8 text-slate">We&apos;re speaking with orthopedic coding and revenue-cycle teams who care about evidence, rules and reviewer control. Tell us a little about your workflow.</p><div className="mt-10 space-y-4 text-sm text-slate"><p><span className="font-semibold text-ink">What this is:</span> a development preview of the evidence-first coding workflow.</p><p><span className="font-semibold text-ink">What this is not:</span> a promise of production access or autonomous submission.</p></div></div><AccessForm /></div></main><MarketingFooter /></div>;
}
