"use client";

import { Filter, Search, UploadCloud } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { ChartList } from "@/components/chart-list";
import { Alert, LoadingPanel, PanelHeading } from "@/components/ui";
import { Chart, getCharts } from "@/lib/api";

export default function ChartsPage() { return <Suspense fallback={<LoadingPanel label="Loading charts" />}><ChartsContent /></Suspense>; }

function ChartsContent() {
  const searchParams = useSearchParams();
  const initialStatus = searchParams.get("status") ?? "all";
  const [charts, setCharts] = useState<Chart[]>([]);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState(initialStatus);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { void getCharts().then(setCharts).catch((caught) => setError(caught instanceof Error ? caught.message : "Charts unavailable")).finally(() => setLoading(false)); }, []);
  const filtered = useMemo(() => charts.filter((chart) => { const matchesQuery = `${chart.external_id ?? ""} ${chart.original_filename} ${chart.status} ${chart.stage}`.toLowerCase().includes(query.toLowerCase()); return matchesQuery && (status === "all" || chart.status === status); }), [charts, query, status]);
  if (loading) return <LoadingPanel label="Loading charts" />;
  return <div className="space-y-5">{error && <Alert tone="bad">{error}</Alert>}<section className="panel overflow-hidden"><PanelHeading title="All charts" body={`${filtered.length} of ${charts.length} encounters`} action={<Link className="button-primary" href="/app/charts/new"><UploadCloud size={16} />Upload chart</Link>} /><div className="flex flex-col gap-3 border-b border-line p-4 sm:flex-row"><div className="search-box flex-1"><Search size={16} /><input aria-label="Search charts" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search chart, file, status or stage" /></div><div className="flex items-center gap-2"><Filter size={15} className="text-slate" /><select className="control min-w-44" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by status"><option value="all">All statuses</option><option value="needs_review">Needs review</option><option value="processing">Processing</option><option value="ready_for_submission">Ready for submission</option><option value="reviewer_approved">Reviewer approved</option><option value="failed">Failed</option></select></div></div><ChartList charts={filtered} emptyAction={<Link className="button-primary" href="/app/charts/new">Upload chart</Link>} /></section></div>;
}
