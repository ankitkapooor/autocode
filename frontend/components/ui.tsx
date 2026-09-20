import { CircleAlert, FileSearch, LoaderCircle, X } from "lucide-react";

import { statusTokens, statusTone, StatusTone } from "@/lib/tokens";

export const number = new Intl.NumberFormat("en-US");
export const percent = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });

export function Status({ status, label }: { status: string; label?: string }) {
  const tone = statusTone(status);
  return <span className={`status-pill ${statusTokens[tone].pill}`}><span className="status-dot" aria-hidden="true" />{label ?? status.replaceAll("_", " ")}</span>;
}

export function Confidence({ state, score }: { state: string; score: number }) {
  const tone: StatusTone = state === "GREEN" ? "good" : state === "YELLOW" ? "warning" : "bad";
  return <span className={`confidence-pill ${statusTokens[tone].pill}`}>{state.toLowerCase()} · {percent.format(score)}</span>;
}

export function PanelHeading({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return <div className="panel-heading"><div><h2>{title}</h2><p>{body}</p></div>{action}</div>;
}

export function Field({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return <label className="block"><span className="form-label">{label}</span>{children}{note && <span className="mt-1.5 block text-xs leading-5 text-slate">{note}</span>}</label>;
}

export function Empty({ title, body, action }: { title: string; body: string; action?: React.ReactNode }) {
  return <div className="grid min-h-[240px] place-items-center p-8 text-center"><div className="max-w-sm"><div className="mx-auto grid h-12 w-12 place-items-center rounded-full bg-slate-100 text-slate"><FileSearch size={20} /></div><h3 className="mt-4 text-base font-semibold">{title}</h3><p className="mt-2 text-sm leading-6 text-slate">{body}</p>{action && <div className="mt-5">{action}</div>}</div></div>;
}

export function LoadingPanel({ label = "Loading workspace" }: { label?: string }) {
  return <div className="panel grid min-h-[380px] place-items-center"><div className="text-center"><LoaderCircle className="mx-auto animate-spin text-blue" /><div className="mt-3 text-sm font-semibold">{label}</div></div></div>;
}

export function Alert({ tone, children, onClose }: { tone: "good" | "bad" | "warning"; children: React.ReactNode; onClose?: () => void }) {
  const classes = tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : tone === "warning" ? "border-amber-200 bg-amber-50 text-amber-900" : "border-red-200 bg-red-50 text-red-900";
  return <div className={`mb-5 flex items-start justify-between gap-3 rounded-xl border px-4 py-3 text-sm leading-6 ${classes}`} role={tone === "bad" ? "alert" : "status"}><span className="flex gap-2"><CircleAlert size={16} className="mt-1 shrink-0" />{children}</span>{onClose && <button className="rounded p-1" onClick={onClose} aria-label="Dismiss message"><X size={15} /></button>}</div>;
}

export function KeyValue({ label, value }: { label: string; value: string }) {
  return <div className="flex min-w-0 items-center justify-between gap-4 px-3 py-3 text-sm"><span className="text-slate">{label}</span><span className="truncate font-medium text-ink">{value}</span></div>;
}

export function messageOf(value: unknown) { return value instanceof Error ? value.message : "The operation could not be completed"; }

export const pipeline = [
  ["document_extraction", "Document extraction"],
  ["clinical_fact_extraction", "Clinical facts"],
  ["jev_fact_validation", "JEV fact validation"],
  ["candidate_retrieval", "Code retrieval"],
  ["coding_reasoning", "Coding reasoning"],
  ["jev_code_selection", "JEV code selection"],
  ["jev_modifier_resolution", "JEV modifier resolution"],
  ["coding_assembly", "Coding assembly"],
  ["deterministic_rules", "Deterministic rules"],
  ["jev_rule_adjudication", "JEV rule adjudication"],
  ["complete", "Calibrated result"]
] as const;

export function labelStage(stage: string) { return pipeline.find(([key]) => key === stage)?.[1] ?? stage.replaceAll("_", " "); }
