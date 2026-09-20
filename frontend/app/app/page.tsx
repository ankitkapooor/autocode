"use client";

import { Archive, Check, Clock3, Gauge, LockKeyhole, ShieldCheck, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ChartList } from "@/components/chart-list";
import { Alert, LoadingPanel, number, PanelHeading } from "@/components/ui";
import { Chart, Dashboard, getCharts, getDashboard, getOverview, Overview } from "@/lib/api";

export default function HomePage() {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [charts, setCharts] = useState<Chart[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void Promise.allSettled([getDashboard(), getCharts(), getOverview()]).then(([d, c, o]) => { if (d.status === "fulfilled") setDashboard(d.value); if (c.status === "fulfilled") setCharts(c.value); if (o.status === "fulfilled") setOverview(o.value); const failed = [d, c, o].find((item) => item.status === "rejected"); if (failed?.status === "rejected") setError(failed.reason instanceof Error ? failed.reason.message : "API unavailable"); setLoading(false); }); }, []);
  if (loading) return <LoadingPanel label="Loading operational view" />;
  const ready = overview?.gate === "ready";
  return <div className="space-y-5">{error && <Alert tone="bad">{error}</Alert>}<section className={`gate-card ${ready ? "gate-ready" : "gate-blocked"}`}><div className="flex gap-4"><div className={`gate-icon ${ready ? "surface-good text-teal" : "surface-warning text-amber"}`}>{ready ? <ShieldCheck size={25} /> : <LockKeyhole size={25} />}</div><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold tracking-[-0.02em]">{ready ? "Coding workflow is ready" : "Reference gate requires attention"}</h2><span className={`status-pill ${ready ? "status-good" : "status-warning"}`}><span className="status-dot" />{overview?.active_release?.name ?? "unpublished"}</span></div><p className="mt-2 max-w-3xl text-sm leading-6 text-slate">{ready ? `${number.format(overview?.licensed_cpt_records ?? 0)} licensed CPT records are active. Coding is available with mandatory human review.` : "Publish a validated release containing licensed CPT records before clinical chart processing."}</p></div></div><Link className="button-primary" href={ready ? "/app/charts/new" : "/app/admin/reference"}>{ready ? <UploadCloud size={16} /> : <LockKeyhole size={16} />}{ready ? "Upload chart" : "Resolve gate"}</Link></section>
    <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric icon={Archive} label="All charts" value={number.format(dashboard?.charts_total ?? 0)} detail="De-identified encounters" href="/app/charts" /><Metric icon={Clock3} label="Needs review" value={number.format(dashboard?.queue.needs_review ?? 0)} detail="Coder action required" tone="warning" href="/app/charts?status=needs_review" /><Metric icon={Check} label="Processed" value={number.format(dashboard?.processed_total ?? 0)} detail="Pipeline completed" tone="good" /><Metric icon={Gauge} label="Green confidence" value={number.format(dashboard?.confidence.GREEN ?? 0)} detail="Still requires review" /></section>
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)]"><section className="panel overflow-hidden"><PanelHeading title="Recent charts" body="Latest uploads and workflow outcomes" action={<Link className="text-link" href="/app/charts">View all</Link>} /><ChartList charts={charts.slice(0, 7)} emptyAction={<Link className="button-primary" href="/app/charts/new">Upload first chart</Link>} /></section><section className="panel"><PanelHeading title="Confidence routing" body="Calibrated after deterministic edits" /><div className="space-y-5 p-5">{(["GREEN", "YELLOW", "RED"] as const).map((state) => { const count = dashboard?.confidence[state] ?? 0; const total = Math.max(1, Object.values(dashboard?.confidence ?? {}).reduce((sum, value) => sum + value, 0)); return <div key={state}><div className="flex items-center justify-between text-xs font-semibold"><span className="capitalize">{state.toLowerCase()}</span><span>{count}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full confidence-${state.toLowerCase()}`} style={{ width: `${(count / total) * 100}%` }} /></div></div>; })}<div className="rounded-xl border border-line bg-slate-50 p-4 text-xs leading-5 text-slate">Confidence is a routing signal, not a substitute for coder judgment. Rule failures always force review.</div></div></section></div>
  </div>;
}

function Metric({ icon: Icon, label, value, detail, tone = "neutral", href }: { icon: typeof Archive; label: string; value: string; detail: string; tone?: "good" | "warning" | "neutral"; href?: string }) {
  const body = <div className="panel flex h-full items-start gap-4 p-5 transition hover:-translate-y-0.5 hover:shadow-lg"><div className={`metric-icon ${tone === "good" ? "surface-good text-teal" : tone === "warning" ? "surface-warning text-amber" : "surface-neutral text-blue"}`}><Icon size={19} /></div><div className="min-w-0"><div className="text-xs font-semibold text-slate">{label}</div><div className="mt-1 text-3xl font-semibold tracking-[-0.05em]">{value}</div><div className="mt-1 truncate text-xs text-slate">{detail}</div></div></div>;
  return href ? <Link href={href}>{body}</Link> : body;
}
