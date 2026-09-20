"use client";

import { BarChart3, LoaderCircle, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { Alert, Empty, LoadingPanel, messageOf, PanelHeading, percent, Status } from "@/components/ui";
import { Evaluation, getEvaluations, runEvaluation } from "@/lib/api";

export default function EvaluationPage() {
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [dataset, setDataset] = useState("orthopedic-gold-v1");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getEvaluations().then(setEvaluations).catch((caught) => setError(messageOf(caught))).finally(() => setLoading(false)); }, []);
  async function run() { setBusy(true); setError(null); try { await runEvaluation(dataset); setEvaluations(await getEvaluations()); setNotice(`Evaluation ${dataset} completed.`); } catch (caught) { setError(messageOf(caught)); } finally { setBusy(false); } }
  if (loading) return <LoadingPanel label="Loading evaluation history" />;
  const latest = evaluations[0];
  return <div className="space-y-5">{notice && <Alert tone="good" onClose={() => setNotice(null)}>{notice}</Alert>}{error && <Alert tone="bad" onClose={() => setError(null)}>{error}</Alert>}<section className="panel"><PanelHeading title="Run evaluation" body="Compare immutable outputs with reviewer-curated gold encounters" /><div className="flex flex-col gap-3 p-5 sm:flex-row"><input className="control flex-1" value={dataset} onChange={(event) => setDataset(event.target.value)} /><button className="button-primary" disabled={busy || !dataset} onClick={() => void run()}>{busy ? <LoaderCircle className="animate-spin" size={16} /> : <Play size={16} />}Run dataset</button></div></section>{latest && <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[["Exact match", "exact_match_rate"], ["Code precision", "code_precision"], ["Code recall", "code_recall"], ["Coverage", "coverage"]].map(([label, key]) => <EvalMetric key={key} label={label} value={percent.format(latest.metrics[key] ?? 0)} detail={`${latest.dataset} · ${latest.sample_count} cases`} />)}</section>}<section className="panel overflow-hidden"><PanelHeading title="Evaluation history" body="Autonomy remains off until prospective thresholds pass" />{evaluations.length ? <><div className="hidden md:block"><table><thead><tr><th>Dataset</th><th>Status</th><th>Sample</th><th>Exact match</th><th>Coverage</th></tr></thead><tbody>{evaluations.map((item) => <tr key={item.id}><td className="font-semibold text-ink">{item.dataset}</td><td><Status status={item.status} /></td><td>{item.sample_count}</td><td>{percent.format(item.metrics.exact_match_rate ?? 0)}</td><td>{percent.format(item.metrics.coverage ?? 0)}</td></tr>)}</tbody></table></div><div className="divide-y divide-line md:hidden">{evaluations.map((item) => <article className="p-4" key={item.id}><div className="flex items-center justify-between gap-3"><div className="font-semibold">{item.dataset}</div><Status status={item.status} /></div><div className="mt-3 grid grid-cols-3 gap-3 text-xs"><div><div className="text-slate">Sample</div><div className="mt-1 font-semibold">{item.sample_count}</div></div><div><div className="text-slate">Exact match</div><div className="mt-1 font-semibold">{percent.format(item.metrics.exact_match_rate ?? 0)}</div></div><div><div className="text-slate">Coverage</div><div className="mt-1 font-semibold">{percent.format(item.metrics.coverage ?? 0)}</div></div></div></article>)}</div></> : <Empty title="No evaluation runs" body="Curate a gold dataset, then run a controlled comparison here to establish a baseline." />}</section></div>;
}

function EvalMetric({ label, value, detail }: { label: string; value: string; detail: string }) { return <div className="panel flex items-start gap-4 p-5"><div className="metric-icon surface-neutral text-blue"><BarChart3 size={18} /></div><div><div className="text-xs font-semibold text-slate">{label}</div><div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{value}</div><div className="mt-1 text-xs text-slate">{detail}</div></div></div>; }
