"use client";

import { ChevronRight, FileText } from "lucide-react";
import Link from "next/link";

import { Chart } from "@/lib/api";
import { Empty, labelStage, Status } from "@/components/ui";

export function ChartList({ charts, emptyAction }: { charts: Chart[]; emptyAction?: React.ReactNode }) {
  if (!charts.length) return <Empty title="No charts match this view" body="Upload a de-identified chart to start the workflow, or clear the current search and filters." action={emptyAction} />;
  return <>
    <div className="hidden overflow-hidden md:block"><table><thead><tr><th>Chart</th><th>Service date</th><th>Status</th><th>Current stage</th><th>Pages</th><th><span className="sr-only">Open</span></th></tr></thead><tbody>{charts.map((chart) => <tr key={chart.id} className="group"><td><Link className="block" href={`/app/charts/${chart.id}`}><div className="font-semibold text-ink">{chart.external_id || chart.original_filename}</div><div className="mt-1 font-mono text-[11px] text-slate">{chart.id.slice(0, 8)}</div></Link></td><td><Link className="block py-1" href={`/app/charts/${chart.id}`}>{chart.service_date}</Link></td><td><Link className="block py-1" href={`/app/charts/${chart.id}`}><Status status={chart.status} /></Link></td><td><Link className="block py-1 text-ink" href={`/app/charts/${chart.id}`}>{labelStage(chart.stage)}</Link></td><td><Link className="block py-1" href={`/app/charts/${chart.id}`}>{chart.page_count}</Link></td><td><Link className="grid h-9 w-9 place-items-center rounded-lg text-slate transition group-hover:bg-slate-100 group-hover:text-ink" href={`/app/charts/${chart.id}`} aria-label={`Open ${chart.external_id || chart.original_filename}`}><ChevronRight size={17} /></Link></td></tr>)}</tbody></table></div>
    <div className="divide-y divide-line md:hidden">{charts.map((chart) => <Link key={chart.id} href={`/app/charts/${chart.id}`} className="flex items-start gap-3 p-4 transition hover:bg-slate-50"><div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-sky-50 text-blue"><FileText size={18} /></div><div className="min-w-0 flex-1"><div className="truncate text-sm font-semibold text-ink">{chart.external_id || chart.original_filename}</div><div className="mt-1 text-xs text-slate">{chart.service_date} · {chart.page_count} pages</div><div className="mt-3 flex flex-wrap items-center gap-2"><Status status={chart.status} /><span className="text-xs text-slate">{labelStage(chart.stage)}</span></div></div><ChevronRight size={17} className="mt-2 shrink-0 text-slate" /></Link>)}</div>
  </>;
}
