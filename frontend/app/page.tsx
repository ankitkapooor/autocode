"use client";

import {
  Activity,
  Archive,
  BarChart3,
  BookOpen,
  Check,
  ChevronRight,
  CircleAlert,
  ClipboardCheck,
  Clock3,
  Database,
  FileSearch,
  FileCheck2,
  Gauge,
  LayoutDashboard,
  LoaderCircle,
  LockKeyhole,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Sparkles,
  UploadCloud,
  X
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  Chart,
  ChartPage,
  ClinicalFact,
  CodeEntry,
  CodingResult,
  Dashboard,
  Evaluation,
  ModifierEntry,
  Overview,
  getChart,
  getCharts,
  getCoding,
  getDashboard,
  getEvaluations,
  getFacts,
  getOverview,
  getPages,
  publishRelease,
  reprocessChart,
  runEvaluation,
  searchCodes,
  searchModifiers,
  startImport,
  submitReview,
  uploadChart
} from "@/lib/api";

type View = "dashboard" | "queue" | "upload" | "processing" | "review" | "output" | "codebook" | "evaluation" | "reference";

const number = new Intl.NumberFormat("en-US");
const percent = new Intl.NumberFormat("en-US", { style: "percent", maximumFractionDigits: 1 });

const navigation: Array<{ id: View; label: string; icon: typeof LayoutDashboard }> = [
  { id: "dashboard", label: "Operations", icon: LayoutDashboard },
  { id: "queue", label: "Work queue", icon: Archive },
  { id: "upload", label: "Upload chart", icon: UploadCloud },
  { id: "review", label: "Coding review", icon: ClipboardCheck },
  { id: "output", label: "Final output", icon: FileCheck2 },
  { id: "codebook", label: "Codebook", icon: BookOpen },
  { id: "evaluation", label: "Evaluation", icon: Gauge },
  { id: "reference", label: "Reference data", icon: Database }
];

const pipeline = [
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
];

export default function OrthoCodeApp() {
  const [view, setView] = useState<View>("dashboard");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [charts, setCharts] = useState<Chart[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedChart, setSelectedChart] = useState<Chart | null>(null);
  const [coding, setCoding] = useState<CodingResult | null>(null);
  const [pages, setPages] = useState<ChartPage[]>([]);
  const [facts, setFacts] = useState<ClinicalFact[]>([]);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [dashboardResult, chartResult, overviewResult, evaluationResult] = await Promise.allSettled([
      getDashboard(),
      getCharts(),
      getOverview(),
      getEvaluations()
    ]);
    if (dashboardResult.status === "fulfilled") setDashboard(dashboardResult.value);
    if (chartResult.status === "fulfilled") setCharts(chartResult.value);
    if (overviewResult.status === "fulfilled") setOverview(overviewResult.value);
    if (evaluationResult.status === "fulfilled") setEvaluations(evaluationResult.value);
    const rejected = [dashboardResult, chartResult, overviewResult].find((result) => result.status === "rejected");
    if (rejected?.status === "rejected") setError(rejected.reason instanceof Error ? rejected.reason.message : "API unavailable");
    else setError(null);
    setLoading(false);
  }, []);

  const loadSelected = useCallback(async (id: string) => {
    const chart = await getChart(id);
    setSelectedChart(chart);
    const [codingResult, pageResult, factResult] = await Promise.allSettled([getCoding(id), getPages(id), getFacts(id)]);
    setCoding(codingResult.status === "fulfilled" ? codingResult.value : null);
    setPages(pageResult.status === "fulfilled" ? pageResult.value : []);
    setFacts(factResult.status === "fulfilled" ? factResult.value : []);
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (selectedId) void loadSelected(selectedId).catch((caught) => setError(messageOf(caught)));
  }, [selectedId, loadSelected]);

  useEffect(() => {
    if (!selectedId || !selectedChart || !["uploaded", "processing"].includes(selectedChart.status)) return;
    const timer = window.setInterval(() => {
      void loadSelected(selectedId).then(refresh).catch((caught) => setError(messageOf(caught)));
    }, 2200);
    return () => window.clearInterval(timer);
  }, [selectedId, selectedChart, loadSelected, refresh]);

  function openChart(chart: Chart) {
    setSelectedId(chart.id);
    setView(["uploaded", "processing", "failed"].includes(chart.status) ? "processing" : "review");
  }

  async function runAction(name: string, task: () => Promise<unknown>, success: string) {
    setAction(name);
    setError(null);
    setNotice(null);
    try {
      await task();
      setNotice(success);
      await refresh();
      if (selectedId) await loadSelected(selectedId);
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setAction(null);
    }
  }

  const pendingReview = useMemo(() => charts.filter((chart) => chart.status === "needs_review"), [charts]);

  return (
    <div className="min-h-screen bg-canvas text-ink">
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-[248px] flex-col bg-navy text-white lg:flex">
        <div className="flex h-[72px] items-center gap-3 border-b border-white/10 px-6">
          <div className="grid h-9 w-9 place-items-center rounded-lg bg-white text-[13px] font-extrabold tracking-[-0.08em] text-navy">OC</div>
          <div><div className="text-[15px] font-semibold">OrthoCode AI</div><div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-300">Coding control plane</div></div>
        </div>
        <nav className="flex-1 space-y-1 px-3 py-5">
          {navigation.map((item) => <NavItem key={item.id} {...item} active={view === item.id || (item.id === "queue" && view === "processing")} onClick={() => setView(item.id)} />)}
        </nav>
        <div className="border-t border-white/10 p-4">
          <div className="rounded-lg bg-white/5 p-3">
            <div className="flex items-center gap-2 text-xs font-semibold"><ShieldCheck size={15} className="text-emerald-300" />Autonomy guarded</div>
            <div className="mt-1.5 text-[11px] leading-4 text-slate-300">Human review remains required until measured thresholds and a real decision provider pass.</div>
          </div>
        </div>
      </aside>

      <main className="lg:pl-[248px]">
        <header className="sticky top-0 z-30 flex h-[72px] items-center justify-between border-b border-line bg-white/95 px-4 backdrop-blur md:px-8">
          <div>
            <h1 className="text-[17px] font-semibold tracking-[-0.02em]">{titleFor(view)}</h1>
            <p className="mt-0.5 hidden text-xs text-slate sm:block">Evidence-first orthopedic professional coding</p>
          </div>
          <div className="flex items-center gap-2">
            <div className={`hidden items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold sm:flex ${overview?.gate === "ready" ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-800"}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${overview?.gate === "ready" ? "bg-emerald-600" : "bg-amber-600"}`} />
              {overview?.gate === "ready" ? `CPT ${overview.active_release?.name ?? "active"}` : "Coding gate blocked"}
            </div>
            <button className="icon-button" aria-label="Refresh" onClick={() => void refresh()}><RefreshCw size={16} /></button>
          </div>
        </header>

        <div className="mx-auto max-w-[1500px] p-4 md:p-6 xl:p-8">
          <div className="mb-4 flex gap-2 overflow-x-auto lg:hidden">
            {navigation.map((item) => <button key={item.id} className={`whitespace-nowrap rounded-md border px-3 py-2 text-xs font-semibold ${view === item.id ? "border-navy bg-navy text-white" : "border-line bg-white text-slate"}`} onClick={() => setView(item.id)}>{item.label}</button>)}
          </div>
          {notice && <Alert tone="good" onClose={() => setNotice(null)}>{notice}</Alert>}
          {error && <Alert tone="bad" onClose={() => setError(null)}>{error}</Alert>}
          {loading ? <LoadingPanel /> : (
            <>
              {view === "dashboard" && <DashboardView data={dashboard} overview={overview} charts={charts} onOpen={openChart} onUpload={() => setView("upload")} />}
              {view === "queue" && <QueueView charts={charts} onOpen={openChart} />}
              {view === "upload" && <UploadView gateReady={overview?.gate === "ready"} busy={action === "upload"} onUpload={async (data) => {
                setAction("upload"); setError(null);
                try { const result = await uploadChart(data); setSelectedId(result.chart.id); setView("processing"); setNotice("Chart accepted and processing started."); await refresh(); }
                catch (caught) { setError(messageOf(caught)); }
                finally { setAction(null); }
              }} />}
              {view === "processing" && <ProcessingView chart={selectedChart} onRetry={() => selectedId && void runAction("retry", () => reprocessChart(selectedId), "Chart reprocessing started.")} busy={action === "retry"} />}
              {view === "review" && <ReviewView chart={selectedChart} coding={coding} pages={pages} facts={facts} queue={pendingReview} busy={action === "review"} onSelect={setSelectedId} onSubmit={(payload) => selectedId && runAction("review", () => submitReview(selectedId, payload), "Review saved to the audit trail.")} />}
              {view === "output" && <FinalOutputView chart={selectedChart} coding={coding} charts={charts} onSelect={setSelectedId} />}
              {view === "codebook" && <CodebookView />}
              {view === "evaluation" && <EvaluationView evaluations={evaluations} busy={action === "evaluation"} onRun={(dataset) => runAction("evaluation", () => runEvaluation(dataset), `Evaluation ${dataset} completed.`)} />}
              {view === "reference" && <ReferenceView overview={overview} busy={action} onImport={() => runAction("reference-import", startImport, "Reference normalization queued.")} onPublish={() => overview?.latest_release && runAction("reference-publish", () => publishRelease(overview.latest_release!.id), "Reference release published.")} />}
            </>
          )}
        </div>
      </main>
    </div>
  );
}

function DashboardView({ data, overview, charts, onOpen, onUpload }: { data: Dashboard | null; overview: Overview | null; charts: Chart[]; onOpen: (chart: Chart) => void; onUpload: () => void }) {
  const ready = overview?.gate === "ready";
  return <>
    <section className={`gate-card ${ready ? "gate-ready" : "gate-blocked"}`}>
      <div className="flex gap-4"><div className={`gate-icon ${ready ? "bg-emerald-50 text-teal" : "bg-amber-50 text-amber"}`}>{ready ? <ShieldCheck size={22} /> : <LockKeyhole size={22} />}</div><div><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{ready ? "Coding workflow unlocked" : "Reference gate requires attention"}</h2><span className={`status-pill ${ready ? "status-good" : "status-neutral"}`}>{overview?.active_release?.name ?? "unpublished"}</span></div><p className="mt-1 max-w-3xl text-sm leading-6 text-slate">{ready ? `${number.format(overview?.licensed_cpt_records ?? 0)} licensed CPT records are active. Chart coding is available with mandatory human review.` : "Publish a validated release containing licensed CPT before clinical chart processing."}</p></div></div>
      <button className="button-primary" disabled={!ready} onClick={onUpload}><UploadCloud size={16} />Upload chart</button>
    </section>
    <section className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Metric icon={Archive} label="Charts" value={number.format(data?.charts_total ?? 0)} detail="All de-identified encounters" />
      <Metric icon={Clock3} label="Needs review" value={number.format(data?.queue.needs_review ?? 0)} detail="Coder work queue" tone="warning" />
      <Metric icon={Check} label="Processed" value={number.format(data?.processed_total ?? 0)} detail="Pipeline completed" tone="good" />
      <Metric icon={Gauge} label="Green confidence" value={number.format(data?.confidence.GREEN ?? 0)} detail="Still requires review" />
    </section>
    <div className="mt-5 grid gap-5 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,0.75fr)]">
      <section className="panel overflow-hidden"><PanelHeading title="Recent charts" body="Latest uploads and processing outcomes" /><ChartTable charts={charts.slice(0, 8)} onOpen={onOpen} /></section>
      <section className="panel"><PanelHeading title="Confidence distribution" body="Calibrated after deterministic edits" /><div className="space-y-5 p-5">{(["GREEN", "YELLOW", "RED"] as const).map((state) => { const count = data?.confidence[state] ?? 0; const total = Math.max(1, Object.values(data?.confidence ?? {}).reduce((sum, value) => sum + value, 0)); return <div key={state}><div className="flex items-center justify-between text-xs font-semibold"><span>{state}</span><span>{count}</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full confidence-${state.toLowerCase()}`} style={{ width: `${(count / total) * 100}%` }} /></div></div>; })}<div className="rounded-lg border border-line bg-slate-50 p-3 text-xs leading-5 text-slate">Confidence is a routing signal, not a substitute for coder judgment. Rule failures always force review.</div></div></section>
    </div>
  </>;
}

function QueueView({ charts, onOpen }: { charts: Chart[]; onOpen: (chart: Chart) => void }) {
  const [query, setQuery] = useState("");
  const filtered = charts.filter((chart) => `${chart.external_id ?? ""} ${chart.original_filename} ${chart.status}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="panel overflow-hidden"><div className="panel-heading"><div><h2>Chart work queue</h2><p>{filtered.length} encounters across processing and review</p></div><div className="search-box"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chart or status" /></div></div><ChartTable charts={filtered} onOpen={onOpen} /></section>;
}

function UploadView({ gateReady, busy, onUpload }: { gateReady: boolean; busy: boolean; onUpload: (data: FormData) => Promise<void> }) {
  const [file, setFile] = useState<File | null>(null);
  const [serviceDate, setServiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [setting, setSetting] = useState("practitioner");
  const [externalId, setExternalId] = useState("");
  const [deidentified, setDeidentified] = useState(false);
  async function submit(event: FormEvent) { event.preventDefault(); if (!file) return; const data = new FormData(); data.append("document", file); data.append("service_date", serviceDate); data.append("setting", setting); data.append("external_id", externalId); data.append("deidentified", String(deidentified)); await onUpload(data); }
  return <div className="mx-auto max-w-3xl"><section className="panel overflow-hidden"><PanelHeading title="Upload surgical chart" body="PDF documents only · 25 MB maximum · de-identified development workflow" /><form className="space-y-6 p-6" onSubmit={submit}><label className={`upload-zone ${file ? "upload-zone-active" : ""}`}><input type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><div className="grid h-12 w-12 place-items-center rounded-xl bg-sky-50 text-blue"><UploadCloud size={23} /></div><div className="mt-3 font-semibold">{file ? file.name : "Choose a de-identified PDF"}</div><div className="mt-1 text-xs text-slate">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Click to browse from this computer"}</div></label><div className="grid gap-4 sm:grid-cols-2"><Field label="Service date"><input type="date" required value={serviceDate} onChange={(event) => setServiceDate(event.target.value)} /></Field><Field label="Billing setting"><select value={setting} onChange={(event) => setSetting(event.target.value)}><option value="practitioner">Practitioner</option><option value="hospital">Outpatient hospital</option></select></Field></div><Field label="De-identified chart ID" note="Do not enter a patient name or medical record number."><input maxLength={128} value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="ORTHO-CASE-001" /></Field><label className="flex cursor-pointer items-start gap-3 rounded-lg border border-line bg-slate-50 p-4"><input className="mt-0.5 h-4 w-4 accent-navy" type="checkbox" checked={deidentified} onChange={(event) => setDeidentified(event.target.checked)} /><span><span className="block text-sm font-semibold">I confirm this chart is de-identified</span><span className="mt-1 block text-xs leading-5 text-slate">Development mode blocks processing unless this confirmation is provided.</span></span></label><div className="flex justify-end"><button className="button-primary" disabled={!gateReady || !file || !deidentified || busy}>{busy ? <LoaderCircle size={16} className="animate-spin" /> : <Sparkles size={16} />}Start coding pipeline</button></div></form></section></div>;
}

function ProcessingView({ chart, onRetry, busy }: { chart: Chart | null; onRetry: () => void; busy: boolean }) {
  if (!chart) return <Empty title="Select a chart" body="Open a chart from the work queue to inspect processing." />;
  const activeIndex = pipeline.findIndex(([key]) => key === chart.stage);
  const complete = chart.stage === "complete";
  return <div className="grid gap-5 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,0.75fr)]"><section className="panel"><PanelHeading title={chart.external_id || chart.original_filename} body={`${chart.service_date} · ${chart.setting}`} /><div className="p-6"><div className="mb-7 flex items-center justify-between"><div><Status status={chart.status} /><p className="mt-2 text-sm text-slate">Current stage: <span className="font-semibold text-ink">{labelStage(chart.stage)}</span></p></div>{chart.status === "processing" && <LoaderCircle className="animate-spin text-blue" size={25} />}</div><div className="space-y-1">{pipeline.map(([key, label], index) => { const done = complete || index < activeIndex; const active = !complete && index === activeIndex; return <div key={key} className={`pipeline-row ${active ? "pipeline-active" : ""}`}><div className={`pipeline-dot ${done ? "pipeline-done" : active ? "pipeline-running" : ""}`}>{done ? <Check size={13} /> : index + 1}</div><div><div className="text-sm font-semibold">{label}</div><div className="mt-0.5 text-xs text-slate">{done ? "Completed" : active ? "In progress" : "Waiting"}</div></div></div>; })}</div>{chart.status === "failed" && <div className="mt-6 rounded-lg border border-red-200 bg-red-50 p-4"><div className="flex gap-3"><CircleAlert className="mt-0.5 shrink-0 text-danger" size={18} /><div><div className="text-sm font-semibold text-red-900">{chart.error_code}</div><p className="mt-1 text-sm text-red-800">{chart.error_message}</p><button className="button-secondary mt-3" disabled={busy} onClick={onRetry}><RefreshCw size={15} />Retry</button></div></div></div>}</div></section><section className="panel"><PanelHeading title="Control context" body="Immutable inputs used by this run" /><div className="divide-y divide-line p-2"><KeyValue label="Document" value={chart.original_filename} /><KeyValue label="SHA-256" value="Captured" /><KeyValue label="Pages" value={String(chart.page_count)} /><KeyValue label="Service date" value={chart.service_date} /><KeyValue label="Setting" value={chart.setting} /><KeyValue label="Review policy" value="Human required" /></div></section></div>;
}

function ReviewView({ chart, coding, pages, facts, queue, busy, onSelect, onSubmit }: { chart: Chart | null; coding: CodingResult | null; pages: ChartPage[]; facts: ClinicalFact[]; queue: Chart[]; busy: boolean; onSelect: (id: string) => void; onSubmit: (payload: Record<string, unknown>) => void }) {
  const [evidenceId, setEvidenceId] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("coder-01");
  const [notes, setNotes] = useState("");
  const [correction, setCorrection] = useState({ lineId: "", field: "code", value: "", rationale: "" });
  const selectedEvidence = pages.flatMap((page) => page.evidence.map((item) => ({ ...item, page: page.page_number }))).find((item) => item.id === evidenceId);
  if (!chart || !coding) return <div className="grid gap-5 xl:grid-cols-[320px_minmax(0,1fr)]"><section className="panel overflow-hidden"><PanelHeading title="Needs review" body={`${queue.length} charts`} /><ChartPicker charts={queue} selected={chart?.id} onSelect={onSelect} /></section><Empty title="No coding result selected" body="Choose a completed chart from the review queue." /></div>;
  function review(disposition: string) { const changes = correction.value ? [{ coding_line_id: correction.lineId || null, field_name: correction.field, new_value: parseCorrection(correction.field, correction.value), rationale: correction.rationale || null }] : []; onSubmit({ reviewer_id: reviewer, disposition: changes.length && disposition === "approved" ? "approved_with_changes" : disposition, notes: notes || null, changes }); }
  return <div className="space-y-5"><section className="panel overflow-hidden"><div className="panel-heading"><div><div className="flex items-center gap-2"><h2>{chart.external_id || chart.original_filename}</h2><Confidence state={coding.confidence_state} score={coding.confidence_score} /></div><p>{chart.service_date} · {chart.setting} · {facts.length} extracted facts</p></div><Status status={coding.status} /></div><div className="grid divide-y divide-line xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] xl:divide-x xl:divide-y-0"><div className="min-h-[560px]"><div className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-slate">Evidence document</div><div className="max-h-[700px] overflow-y-auto p-5">{selectedEvidence && <div className="mb-4 rounded-lg border border-sky-200 bg-sky-50 p-3 text-sm leading-6"><div className="mb-1 text-[10px] font-bold uppercase tracking-wide text-blue">Page {selectedEvidence.page} · selected evidence</div>{selectedEvidence.text}</div>}{pages.map((page) => <div key={page.id} className="mb-7"><div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate"><span className="grid h-6 w-6 place-items-center rounded bg-slate-100">{page.page_number}</span>Page {page.page_number}</div><div className="space-y-2">{page.evidence.map((item) => <button key={item.id} className={`evidence-block ${evidenceId === item.id ? "evidence-active" : ""}`} onClick={() => setEvidenceId(item.id)}>{item.text}</button>)}</div></div>)}</div></div><div className="min-h-[560px]"><div className="border-b border-line px-5 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-slate">Proposed coding</div><div className="space-y-4 p-5"><DecisionEngineSummary coding={coding} /><p className="text-sm leading-6 text-slate">{coding.summary}</p>{coding.lines.length ? coding.lines.map((line) => <article key={line.id} className="rounded-xl border border-line p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div><div className="flex items-center gap-2"><span className="rounded bg-navy px-2 py-1 font-mono text-xs font-bold text-white">{line.code_system}</span><span className="font-mono text-xl font-semibold">{line.code}</span>{line.modifiers.map((modifier) => <span key={modifier} className="status-pill status-neutral">-{modifier}</span>)}</div><p className="mt-2 text-sm font-medium">{line.description}</p></div><span className="font-mono text-xs text-slate">{line.source === "jev_decision_engine" ? "JEV confidence" : "Confidence"}: {percent.format(line.confidence)}</span></div><p className="mt-3 text-xs leading-5 text-slate">{line.rationale}</p><div className="mt-3 flex flex-wrap gap-2">{line.evidence_span_ids.map((id) => <button key={id} className="evidence-link" onClick={() => setEvidenceId(id)}><FileSearch size={12} />Evidence {id.slice(0, 6)}</button>)}</div><div className="mt-4 space-y-2 border-t border-line pt-3">{coding.rule_decisions.filter((rule) => rule.coding_line_id === line.id).map((rule) => <div key={rule.id} className={`rule-row rule-${rule.outcome}`}><span>{rule.outcome === "pass" ? <Check size={13} /> : <CircleAlert size={13} />}</span><span>{rule.message}</span></div>)}</div></article>) : <Empty title="No supported code lines" body="The chart requires manual coding because evidence or retrieval was insufficient." />}{coding.jev_decisions.length > 0 && <DecisionTrace decisions={coding.jev_decisions} onEvidence={setEvidenceId} />}{coding.warnings.length > 0 && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3"><div className="text-xs font-bold uppercase tracking-wide text-amber">Review findings</div>{coding.warnings.slice(0, 8).map((warning, index) => <p key={`${warning.code}-${index}`} className="mt-2 text-xs leading-5 text-amber-900">{warning.message}</p>)}</div>}</div></div></div></section><section className="panel"><PanelHeading title="Reviewer disposition" body="Corrections are appended; model output remains immutable" /><div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]"><div className="space-y-4"><Field label="Reviewer ID"><input value={reviewer} onChange={(event) => setReviewer(event.target.value)} /></Field><Field label="Review notes"><textarea rows={4} value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Optional rationale or documentation gap" /></Field></div><div className="rounded-lg border border-line bg-slate-50 p-4"><div className="text-sm font-semibold">Optional correction</div><div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Coding line"><select value={correction.lineId} onChange={(event) => setCorrection({ ...correction, lineId: event.target.value })}><option value="">Select line</option>{coding.lines.map((line) => <option key={line.id} value={line.id}>{line.code_system} {line.code}</option>)}</select></Field><Field label="Field"><select value={correction.field} onChange={(event) => setCorrection({ ...correction, field: event.target.value })}><option value="code">Code</option><option value="units">Units</option><option value="modifiers">Modifiers</option><option value="remove_line">Remove line</option><option value="add_line">Add line</option></select></Field></div><Field label="Corrected value" note="Use comma-separated values for modifiers."><input value={correction.value} onChange={(event) => setCorrection({ ...correction, value: event.target.value })} /></Field><div className="mt-3"><Field label="Correction rationale"><input value={correction.rationale} onChange={(event) => setCorrection({ ...correction, rationale: event.target.value })} /></Field></div></div></div><div className="flex flex-wrap justify-end gap-2 border-t border-line px-5 py-4"><button className="button-secondary text-danger" disabled={busy || !reviewer} onClick={() => review("rejected")}><X size={15} />Reject</button><button className="button-primary" disabled={busy || !reviewer} onClick={() => review("approved")}>{busy ? <LoaderCircle className="animate-spin" size={15} /> : <Check size={15} />}{correction.value ? "Approve with correction" : "Approve coding"}</button></div></section></div>;
}

function DecisionEngineSummary({ coding }: { coding: CodingResult }) {
  const summary = coding.jev_summary;
  const abstained = summary.abstained ?? 0;
  return <div className="grid gap-2 rounded-lg border border-line bg-slate-50 p-3 sm:grid-cols-5">
    <KeyValue label="Decision engine" value={coding.decision_engine_mode === "jev_primary" ? "TypeSafe JEV" : coding.decision_engine_mode.replaceAll("_", " ")} />
    <KeyValue label="JEV decisions" value={String(summary.decision_count ?? 0)} />
    <KeyValue label="Codes selected" value={String(summary.codes_selected ?? 0)} />
    <KeyValue label="Abstained" value={String(abstained)} />
    <KeyValue label="Review required" value={String((summary.review ?? 0) + (summary.rejected ?? 0) + abstained)} />
  </div>;
}

function DecisionTrace({ decisions, onEvidence }: { decisions: CodingResult["jev_decisions"]; onEvidence: (id: string) => void }) {
  return <div className="rounded-lg border border-line p-3"><div className="text-xs font-bold uppercase tracking-wide text-slate">JEV decision trace</div><div className="mt-2 space-y-2">{decisions.slice(0, 12).map((decision, index) => <div key={`${decision.question ?? "decision"}-${index}`} className="rounded bg-slate-50 p-3 text-xs"><div className="flex items-center justify-between gap-3"><span className="font-semibold text-ink">{decision.code ? `${decision.code_system} ${decision.code}` : decision.modifier ? `Modifier ${decision.modifier}` : decision.fact || decision.classification || "Decision"}</span><span>{decision.probability == null ? "No probability" : percent.format(decision.probability)} · {decision.status ?? "unknown"}</span></div>{decision.alternatives && decision.alternatives.length > 0 && <div className="mt-1 text-slate">Alternatives: {decision.alternatives.slice(0, 3).map((item) => `${item.code} ${item.probability == null ? "" : percent.format(item.probability)}`).join(" · ")}</div>}<div className="mt-2 flex flex-wrap gap-1">{decision.evidence_span_ids?.map((id) => <button key={id} className="evidence-link" onClick={() => onEvidence(id)}>Evidence {id.slice(0, 6)}</button>)}</div></div>)}</div></div>;
}

function FinalOutputView({ chart, coding, charts, onSelect }: { chart: Chart | null; coding: CodingResult | null; charts: Chart[]; onSelect: (id: string) => void }) {
  const completed = charts.filter((item) => ["needs_review", "ready_for_submission", "reviewer_approved", "reviewer_rejected"].includes(item.status));
  const jevStatus = String(coding?.jev_output.status ?? "not available").replaceAll("_", " ");
  return <div className="grid gap-5 xl:grid-cols-[300px_minmax(0,1fr)]">
    <section className="panel overflow-hidden"><PanelHeading title="Coded encounters" body={`${completed.length} results`} /><ChartPicker charts={completed} selected={chart?.id} onSelect={onSelect} /></section>
    {!chart || !coding ? <Empty title="No final coding result selected" body="Complete a chart run, then select it here to view CPT, modifiers, diagnoses, evidence, rules, and JEV confidence." /> : <div className="space-y-5">
      <section className="gate-card gate-ready"><div className="flex gap-4"><div className="gate-icon bg-emerald-50 text-teal"><FileCheck2 size={21} /></div><div><h2 className="font-semibold">Final coding output</h2><p className="mt-1 text-sm text-slate">{chart.external_id || chart.original_filename} · {chart.service_date} · {chart.setting}</p></div></div><Confidence state={coding.confidence_state} score={coding.confidence_score} /></section>
      <DecisionEngineSummary coding={coding} />
      <section className="grid gap-4 sm:grid-cols-3"><Metric icon={FileCheck2} label="Coding lines" value={number.format(coding.lines.length)} detail={coding.status.replaceAll("_", " ")} /><Metric icon={Sparkles} label="JEV status" value={jevStatus} detail={String(coding.jev_output.model ?? coding.jev_provider)} tone={coding.jev_output.status === "complete" ? "good" : "warning"} /><Metric icon={CircleAlert} label="Rule findings" value={number.format(coding.rule_decisions.filter((item) => item.outcome !== "pass").length)} detail="Warnings and failures" tone="warning" /></section>
      <section className="panel overflow-hidden"><PanelHeading title="Structured coded encounter" body={coding.summary || "Evidence-backed coding result"} /><div className="overflow-x-auto"><table><thead><tr><th>System</th><th>Code</th><th>Description</th><th>Modifiers</th><th>Units</th><th>Diagnosis links</th><th>Decision confidence</th></tr></thead><tbody>{coding.lines.map((line) => <tr key={line.id}><td><span className="rounded bg-navy px-2 py-1 font-mono text-xs font-bold text-white">{line.code_system}</span></td><td className="font-mono text-base font-semibold text-ink">{line.code}</td><td><div className="max-w-md"><div className="font-medium text-ink">{line.description || "—"}</div><div className="mt-1 text-xs leading-5 text-slate">{line.rationale}</div></div></td><td>{line.modifiers.length ? line.modifiers.map((item) => <span key={item} className="status-pill status-neutral mr-1">-{item}</span>) : "—"}</td><td>{line.units}</td><td>{line.diagnosis_pointers.join(", ") || "—"}</td><td>{percent.format(line.confidence)}</td></tr>)}</tbody></table></div></section>
      <section className="panel"><PanelHeading title="Validation summary" body="Deterministic rules and JEV decisions retained with the result" /><div className="space-y-2 p-5">{coding.rule_decisions.map((rule) => <div key={rule.id} className={`rule-row rule-${rule.outcome}`}><span>{rule.outcome === "pass" ? <Check size={13} /> : <CircleAlert size={13} />}</span><span>{rule.message}</span></div>)}</div></section>
    </div>}
  </div>;
}

function CodebookView() {
  const [mode, setMode] = useState<"codes" | "modifiers">("codes");
  const [query, setQuery] = useState("29827");
  const [system, setSystem] = useState("CPT");
  const [codes, setCodes] = useState<CodeEntry[]>([]);
  const [modifiers, setModifiers] = useState<ModifierEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void searchCodes("29827", "CPT").then(setCodes).catch((caught) => setError(messageOf(caught))); }, []);
  async function runSearch(event?: FormEvent) {
    event?.preventDefault();
    if (!query.trim()) return;
    setBusy(true); setError(null);
    try {
      if (mode === "codes") setCodes(await searchCodes(query, system || undefined));
      else setModifiers(await searchModifiers(query));
    } catch (caught) { setError(messageOf(caught)); }
    finally { setBusy(false); }
  }
  function switchMode(next: "codes" | "modifiers") {
    setMode(next); setQuery(next === "codes" ? "29827" : "59"); setError(null);
    if (next === "codes" && !codes.length) void searchCodes("29827", "CPT").then(setCodes).catch((caught) => setError(messageOf(caught)));
    if (next === "modifiers" && !modifiers.length) void searchModifiers("59").then(setModifiers).catch((caught) => setError(messageOf(caught)));
  }
  return <div className="space-y-5">
    <section className="panel"><PanelHeading title="Published codebook" body="Search active CPT, HCPCS, ICD-10-CM, and CPT/HCPCS modifier records" /><div className="p-5"><div className="mb-4 flex gap-2"><button className={mode === "codes" ? "button-primary" : "button-secondary"} onClick={() => switchMode("codes")}>Codes</button><button className={mode === "modifiers" ? "button-primary" : "button-secondary"} onClick={() => switchMode("modifiers")}>Modifiers</button></div><form className="flex flex-col gap-3 sm:flex-row" onSubmit={runSearch}>{mode === "codes" && <select className="control sm:w-44" value={system} onChange={(event) => setSystem(event.target.value)}><option value="CPT">CPT</option><option value="HCPCS">HCPCS</option><option value="ICD10CM">ICD-10-CM</option><option value="">All systems</option></select>}<div className="search-box flex-1"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={mode === "codes" ? "Code or description" : "Modifier or description"} /></div><button className="button-primary" disabled={busy || !query.trim()}>{busy ? <LoaderCircle className="animate-spin" size={15} /> : <Search size={15} />}Search</button></form>{error && <div className="mt-4 text-sm text-danger">{error}</div>}</div></section>
    <section className="panel overflow-hidden"><PanelHeading title={mode === "codes" ? "Code results" : "Modifier results"} body={mode === "codes" ? `${codes.length} active records` : `${modifiers.length} active records`} /><div className="overflow-x-auto">{mode === "codes" ? <table><thead><tr><th>System</th><th>Code</th><th>Description</th><th>Category</th><th>Effective</th></tr></thead><tbody>{codes.map((item) => <tr key={item.id}><td>{item.code_system}</td><td className="font-mono text-base font-semibold text-ink">{item.code}</td><td><div className="max-w-2xl">{item.long_description || item.short_description || "—"}</div></td><td>{item.category || item.chapter || "—"}</td><td>{item.effective_from || "—"}</td></tr>)}</tbody></table> : <table><thead><tr><th>Modifier</th><th>Description</th><th>Type</th><th>Effective</th></tr></thead><tbody>{modifiers.map((item) => <tr key={item.id}><td className="font-mono text-base font-semibold text-ink">-{item.modifier}</td><td><div className="max-w-2xl">{item.description || "—"}</div></td><td>{item.type.replaceAll("_", " ")}</td><td>{item.effective_from || "—"}</td></tr>)}</tbody></table>}</div></section>
  </div>;
}

function EvaluationView({ evaluations, busy, onRun }: { evaluations: Evaluation[]; busy: boolean; onRun: (dataset: string) => void }) {
  const [dataset, setDataset] = useState("orthopedic-gold-v1");
  const latest = evaluations[0];
  return <div className="space-y-5"><section className="panel"><PanelHeading title="Run evaluation" body="Compare immutable coding outputs with reviewer-curated gold encounters" /><div className="flex flex-col gap-3 p-5 sm:flex-row"><input className="control flex-1" value={dataset} onChange={(event) => setDataset(event.target.value)} /><button className="button-primary" disabled={busy || !dataset} onClick={() => onRun(dataset)}>{busy ? <LoaderCircle className="animate-spin" size={16} /> : <Play size={16} />}Run dataset</button></div></section>{latest && <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{[["Exact match", "exact_match_rate"], ["Code precision", "code_precision"], ["Code recall", "code_recall"], ["Coverage", "coverage"]].map(([label, key]) => <Metric key={key} icon={BarChart3} label={label} value={percent.format(latest.metrics[key] ?? 0)} detail={`${latest.dataset} · ${latest.sample_count} cases`} />)}</section>}<section className="panel overflow-hidden"><PanelHeading title="Evaluation history" body="Autonomy remains off until prospective thresholds pass" />{evaluations.length ? <table><thead><tr><th>Dataset</th><th>Status</th><th>Sample</th><th>Exact match</th><th>Coverage</th></tr></thead><tbody>{evaluations.map((item) => <tr key={item.id}><td className="font-semibold text-ink">{item.dataset}</td><td><Status status={item.status} /></td><td>{item.sample_count}</td><td>{percent.format(item.metrics.exact_match_rate ?? 0)}</td><td>{percent.format(item.metrics.coverage ?? 0)}</td></tr>)}</tbody></table> : <Empty title="No evaluation runs" body="Curate a gold dataset, then run a controlled comparison here." />}</section></div>;
}

function ReferenceView({ overview, busy, onImport, onPublish }: { overview: Overview | null; busy: string | null; onImport: () => void; onPublish: () => void }) {
  if (!overview) return <Empty title="Reference service unavailable" body="Start the API to inspect reference releases." />;
  const records = Object.values(overview.record_counts).reduce((sum, value) => sum + value, 0);
  return <div className="space-y-5"><section className={`gate-card ${overview.gate === "ready" ? "gate-ready" : "gate-blocked"}`}><div className="flex gap-4"><div className={`gate-icon ${overview.gate === "ready" ? "bg-emerald-50 text-teal" : "bg-amber-50 text-amber"}`}>{overview.gate === "ready" ? <Database size={21} /> : <CircleAlert size={21} />}</div><div><h2 className="font-semibold">{overview.gate === "ready" ? "Published codebook is runtime-ready" : "Coding gate is blocked"}</h2><p className="mt-1 text-sm text-slate">{number.format(overview.licensed_cpt_records)} licensed CPT codes · {overview.active_release?.name ?? "no active release"}</p></div></div><div className="flex gap-2"><button className="button-secondary" disabled={busy !== null} onClick={onImport}>{busy === "reference-import" ? <LoaderCircle className="animate-spin" size={15} /> : <RefreshCw size={15} />}Normalize</button><button className="button-primary" disabled={busy !== null || overview.latest_release?.status !== "validated"} onClick={onPublish}>Publish</button></div></section><section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric icon={Database} label="Licensed CPT" value={number.format(overview.licensed_cpt_records)} detail="AMA 2026 active codes" tone="good" /><Metric icon={Archive} label="Source files" value={number.format(overview.source_inventory.files_discovered)} detail="Checksummed artifacts" /><Metric icon={Activity} label="Runtime records" value={number.format(records)} detail={overview.ncci_runtime.mode === "source_index" ? "Compact NCCI source index" : overview.latest_release?.name ?? "No release"} /><Metric icon={ShieldCheck} label="Autonomy" value={overview.autonomous_coding_enabled ? "Enabled" : "Disabled"} detail="Empirical gate required" /></section><section className="panel overflow-hidden"><PanelHeading title="Runtime reference coverage" body="Normalized tables plus indexed licensed source data; no duplicate multi-gigabyte NCCI SQL copy" /><div className="grid sm:grid-cols-2 lg:grid-cols-4">{Object.entries(overview.record_counts).map(([key, value]) => <div key={key} className="border-b border-r border-line p-5"><div className="font-mono text-xl font-semibold">{number.format(value)}</div><div className="mt-1 text-xs font-medium capitalize text-slate">{key.replaceAll("_", " ")}</div></div>)}</div></section></div>;
}

function ChartTable({ charts, onOpen }: { charts: Chart[]; onOpen: (chart: Chart) => void }) { if (!charts.length) return <Empty title="No charts yet" body="Upload a de-identified surgical chart to start the workflow." />; return <div className="overflow-x-auto"><table><thead><tr><th>Chart</th><th>Service date</th><th>Status</th><th>Stage</th><th>Pages</th><th /></tr></thead><tbody>{charts.map((chart) => <tr key={chart.id} className="cursor-pointer" onClick={() => onOpen(chart)}><td><div className="font-semibold text-ink">{chart.external_id || chart.original_filename}</div><div className="mt-0.5 font-mono text-[10px] text-slate">{chart.id.slice(0, 8)}</div></td><td>{chart.service_date}</td><td><Status status={chart.status} /></td><td>{labelStage(chart.stage)}</td><td>{chart.page_count}</td><td className="text-right"><ChevronRight size={16} /></td></tr>)}</tbody></table></div>; }
function ChartPicker({ charts, selected, onSelect }: { charts: Chart[]; selected?: string; onSelect: (id: string) => void }) { return <div className="max-h-[620px] divide-y divide-line overflow-y-auto">{charts.map((chart) => <button key={chart.id} className={`w-full px-5 py-4 text-left hover:bg-slate-50 ${selected === chart.id ? "bg-sky-50" : ""}`} onClick={() => onSelect(chart.id)}><div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-semibold">{chart.external_id || chart.original_filename}</span><ChevronRight size={14} className="text-slate" /></div><div className="mt-1 text-xs text-slate">{chart.service_date} · {chart.setting}</div></button>)}</div>; }
function NavItem({ label, icon: Icon, active, onClick }: { label: string; icon: typeof LayoutDashboard; active: boolean; onClick: () => void }) { return <button onClick={onClick} className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition ${active ? "bg-white/12 text-white" : "text-slate-300 hover:bg-white/5 hover:text-white"}`}><Icon size={17} /><span>{label}</span>{active && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-cyan-300" />}</button>; }
function PanelHeading({ title, body }: { title: string; body: string }) { return <div className="panel-heading"><div><h2>{title}</h2><p>{body}</p></div></div>; }
function Metric({ icon: Icon, label, value, detail, tone }: { icon: typeof Archive; label: string; value: string; detail: string; tone?: "good" | "warning" }) { return <div className="panel flex items-start gap-4 p-5"><div className={`metric-icon ${tone === "good" ? "bg-emerald-50 text-teal" : tone === "warning" ? "bg-amber-50 text-amber" : "bg-sky-50 text-blue"}`}><Icon size={18} /></div><div className="min-w-0"><div className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate">{label}</div><div className="mt-1 text-2xl font-semibold tracking-[-0.04em]">{value}</div><div className="mt-1 truncate text-xs text-slate">{detail}</div></div></div>; }
function Status({ status }: { status: string }) { const good = ["complete", "published", "validated", "reviewer_approved", "ready_for_submission"].includes(status); const bad = ["failed", "rejected", "reviewer_rejected"].includes(status); return <span className={`status-pill ${good ? "status-good" : bad ? "status-bad" : "status-neutral"}`}>{status.replaceAll("_", " ")}</span>; }
function Confidence({ state, score }: { state: string; score: number }) { return <span className={`confidence-pill confidence-${state.toLowerCase()}`}>{state} · {percent.format(score)}</span>; }
function Field({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) { return <label className="block"><span className="mb-1.5 block text-xs font-semibold text-ink">{label}</span>{children}{note && <span className="mt-1.5 block text-[11px] leading-4 text-slate">{note}</span>}</label>; }
function KeyValue({ label, value }: { label: string; value: string }) { return <div className="flex items-center justify-between gap-4 px-3 py-3 text-sm"><span className="text-slate">{label}</span><span className="truncate font-medium text-ink">{value}</span></div>; }
function Empty({ title, body }: { title: string; body: string }) { return <div className="panel grid min-h-[220px] place-items-center p-8 text-center"><div><div className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-slate-100 text-slate"><FileSearch size={19} /></div><div className="mt-3 text-sm font-semibold">{title}</div><p className="mt-1 text-xs leading-5 text-slate">{body}</p></div></div>; }
function LoadingPanel() { return <div className="panel grid min-h-[360px] place-items-center"><div className="text-center"><LoaderCircle className="mx-auto animate-spin text-blue" /><div className="mt-3 text-sm font-semibold">Loading control plane</div></div></div>; }
function Alert({ tone, children, onClose }: { tone: "good" | "bad"; children: React.ReactNode; onClose: () => void }) { return <div className={`mb-4 flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm ${tone === "good" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-red-200 bg-red-50 text-red-900"}`}><span>{children}</span><button onClick={onClose}><X size={15} /></button></div>; }

function titleFor(view: View) { return ({ dashboard: "Operations dashboard", queue: "Chart work queue", upload: "Upload chart", processing: "Processing status", review: "Coding review", output: "Final coding output", codebook: "CPT and modifier codebook", evaluation: "Evaluation", reference: "Reference data administration" })[view]; }
function labelStage(stage: string) { return pipeline.find(([key]) => key === stage)?.[1] ?? stage.replaceAll("_", " "); }
function messageOf(value: unknown) { return value instanceof Error ? value.message : "The operation could not be completed"; }
function parseCorrection(field: string, value: string): unknown { if (field === "units") return Number(value); if (field === "modifiers") return value.split(",").map((item) => item.trim()).filter(Boolean); if (field === "add_line") { try { return JSON.parse(value); } catch { return { code: value }; } } return value; }
