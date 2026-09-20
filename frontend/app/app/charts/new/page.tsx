"use client";

import { ArrowLeft, LoaderCircle, ShieldCheck, Sparkles, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useState } from "react";

import { Alert, Field, LoadingPanel, messageOf, PanelHeading } from "@/components/ui";
import { getOverview, uploadChart } from "@/lib/api";

export default function NewChartPage() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [serviceDate, setServiceDate] = useState(new Date().toISOString().slice(0, 10));
  const [setting, setSetting] = useState("practitioner");
  const [externalId, setExternalId] = useState("");
  const [deidentified, setDeidentified] = useState(false);
  const [gateReady, setGateReady] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getOverview().then((value) => setGateReady(value.gate === "ready")).catch((caught) => { setGateReady(false); setError(messageOf(caught)); }); }, []);
  async function submit(event: FormEvent) { event.preventDefault(); if (!file || !deidentified || !gateReady) return; setBusy(true); setError(null); const data = new FormData(); data.append("document", file); data.append("service_date", serviceDate); data.append("setting", setting); data.append("external_id", externalId); data.append("deidentified", String(deidentified)); try { const result = await uploadChart(data); router.push(`/app/charts/${result.chart.id}`); } catch (caught) { setError(messageOf(caught)); setBusy(false); } }
  if (gateReady === null) return <LoadingPanel label="Checking coding gate" />;
  return <div className="mx-auto max-w-4xl"><div className="mb-5"><Link className="text-link" href="/app/charts"><ArrowLeft size={15} />Back to charts</Link></div>{error && <Alert tone="bad" onClose={() => setError(null)}>{error}</Alert>}{!gateReady && <Alert tone="warning">The reference-data gate is blocked. Publish an eligible licensed release before uploading a chart.</Alert>}<section className="panel overflow-hidden"><PanelHeading title="Upload a surgical chart" body="PDF only · 25 MB maximum · de-identified development workflow" /><form className="space-y-6 p-5 sm:p-7" onSubmit={submit}><label className={`upload-zone ${file ? "upload-zone-active" : ""}`}><input type="file" accept="application/pdf,.pdf" className="sr-only" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><div className="grid h-12 w-12 place-items-center rounded-xl bg-sky-50 text-blue"><UploadCloud size={23} /></div><div className="mt-4 font-semibold">{file ? file.name : "Choose a de-identified PDF"}</div><div className="mt-1 text-xs text-slate">{file ? `${(file.size / 1024 / 1024).toFixed(2)} MB` : "Click to browse from this computer"}</div></label><div className="grid gap-5 sm:grid-cols-2"><Field label="Service date"><input type="date" required value={serviceDate} onChange={(event) => setServiceDate(event.target.value)} /></Field><Field label="Billing setting"><select value={setting} onChange={(event) => setSetting(event.target.value)}><option value="practitioner">Practitioner</option><option value="hospital">Outpatient hospital</option></select></Field></div><Field label="De-identified chart ID" note="Do not enter a patient name or medical record number."><input maxLength={128} value={externalId} onChange={(event) => setExternalId(event.target.value)} placeholder="ORTHO-CASE-001" /></Field><label className={`flex cursor-pointer items-start gap-3 rounded-xl border p-4 ${deidentified ? "border-emerald-200 bg-emerald-50" : "border-line bg-slate-50"}`}><input className="mt-0.5 h-4 w-4 accent-navy" type="checkbox" checked={deidentified} onChange={(event) => setDeidentified(event.target.checked)} /><span><span className="flex items-center gap-2 text-sm font-semibold">{deidentified && <ShieldCheck size={15} className="text-teal" />}I confirm this chart is de-identified</span><span className="mt-1 block text-xs leading-5 text-slate">Development mode blocks processing unless this confirmation is provided.</span></span></label><div className="flex flex-col-reverse justify-end gap-3 sm:flex-row"><Link className="button-secondary" href="/app/charts">Cancel</Link><button className="button-primary" disabled={!gateReady || !file || !deidentified || busy}>{busy ? <LoaderCircle size={16} className="animate-spin" /> : <Sparkles size={16} />}Start coding pipeline</button></div></form></section></div>;
}
