export type Release = {
  id: string;
  name: string;
  status: "staged" | "validated" | "rejected" | "published" | "superseded";
  effective_from: string;
  validated_at: string | null;
  published_at: string | null;
  validation_summary: { blocking_errors?: number; warnings?: number; record_counts?: Record<string, number> };
};

export type ImportRun = {
  id: string;
  status: string;
  release_name: string;
  parser_version: string;
  started_at: string | null;
  completed_at: string | null;
  published: boolean;
  blocking_errors: number;
  warnings: number;
};

export type Overview = {
  phase: number;
  gate: "ready" | "blocked";
  autonomous_coding_enabled: boolean;
  licensed_cpt_records: number;
  active_release: Release | null;
  latest_release: Release | null;
  record_counts: Record<string, number>;
  ncci_runtime: { mode: "unavailable" | "materialized_sql" | "source_index"; record_count: number; path: string | null };
  source_inventory: { root: string; files_discovered: number; files_by_family: Record<string, number>; error: string | null };
  recent_runs: ImportRun[];
};

export type Chart = {
  id: string;
  external_id: string | null;
  original_filename: string;
  service_date: string;
  setting: string;
  status: string;
  stage: string;
  page_count: number;
  assigned_to: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  result?: CodingSummary | null;
};

export type CodingSummary = {
  id: string;
  status: string;
  confidence_state: "GREEN" | "YELLOW" | "RED";
  confidence_score: number;
  summary: string | null;
  warnings: Array<{ code: string; message: string }>;
  jev_provider: string;
  jev_output: Record<string, unknown>;
  decision_engine: "legacy_llm" | "jev";
  decision_engine_mode: "legacy_llm" | "jev_shadow" | "jev_primary";
  jev_summary: {
    decision_count?: number;
    accepted?: number;
    review?: number;
    rejected?: number;
  };
  jev_decisions: Array<{
    question?: string;
    fact?: string;
    classification?: string;
    code_system?: string;
    code?: string;
    modifier?: string;
    diagnosis_code?: string;
    probability?: number | null;
    status?: string;
    evidence_span_ids?: string[];
    alternatives?: Array<{ code?: string; description?: string | null; probability?: number }>;
  }>;
  autonomous_eligible: boolean;
  created_at: string;
  updated_at: string;
};

export type CodingResult = CodingSummary & {
  lines: Array<{
    id: string;
    position: number;
    code_system: string;
    code: string;
    description: string | null;
    units: number;
    modifiers: string[];
    diagnosis_pointers: string[];
    confidence: number;
    rationale: string;
    evidence_span_ids: string[];
    source: string;
  }>;
  rule_decisions: Array<{
    id: string;
    coding_line_id: string | null;
    rule_type: string;
    outcome: "pass" | "warning" | "fail";
    message: string;
    details: Record<string, unknown>;
  }>;
  reviews: Array<Record<string, unknown>>;
};

export type ChartPage = {
  id: string;
  page_number: number;
  text: string;
  extraction_method: string;
  evidence: Array<{ id: string; kind: string; text: string; confidence: number }>;
};

export type ClinicalFact = {
  id: string;
  fact_type: string;
  value: string;
  normalized_value: string | null;
  assertion: string;
  confidence: number;
  evidence_span_ids: string[];
};

export type Dashboard = {
  queue: Record<string, number>;
  confidence: Record<string, number>;
  charts_total: number;
  processed_total: number;
  recent_charts: Chart[];
};

export type Evaluation = {
  id: string;
  dataset: string;
  status: string;
  sample_count: number;
  started_at: string | null;
  completed_at: string | null;
  metrics: Record<string, number>;
};

export type CodeEntry = {
  id: string;
  code_system: string;
  code: string;
  short_description: string | null;
  long_description: string | null;
  effective_from: string | null;
  effective_to: string | null;
  billable: boolean | null;
  category: string | null;
  chapter: string | null;
  parent_code: string | null;
};

export type ModifierEntry = {
  id: string;
  modifier: string;
  description: string | null;
  type: string;
  compatible_code_families: string[];
  effective_from: string | null;
  effective_to: string | null;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const isForm = options?.body instanceof FormData;
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: isForm ? options?.headers : { "Content-Type": "application/json", ...options?.headers },
    cache: "no-store"
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = body.detail;
    const message = typeof detail === "string" ? detail : detail?.message;
    throw new Error(message ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const getDashboard = () => apiFetch<Dashboard>("/api/dashboard");
export const getCharts = () => apiFetch<Chart[]>("/api/charts");
export const getChart = (id: string) => apiFetch<Chart>(`/api/charts/${id}`);
export const getCoding = (id: string) => apiFetch<CodingResult>(`/api/charts/${id}/coding`);
export const getPages = (id: string) => apiFetch<ChartPage[]>(`/api/charts/${id}/pages`);
export const getFacts = (id: string) => apiFetch<ClinicalFact[]>(`/api/charts/${id}/facts`);
export const uploadChart = (data: FormData) => apiFetch<{ chart: Chart; status: string }>("/api/charts", { method: "POST", body: data });
export const reprocessChart = (id: string) => apiFetch<{ chart_id: string; status: string }>(`/api/charts/${id}/process`, { method: "POST", body: "{}" });
export const submitReview = (id: string, payload: Record<string, unknown>) =>
  apiFetch<{ id: string; status: string; disposition: string }>(`/api/charts/${id}/reviews`, { method: "POST", body: JSON.stringify(payload) });
export const getEvaluations = () => apiFetch<Evaluation[]>("/api/evaluations/runs");
export const runEvaluation = (dataset: string) => apiFetch<Evaluation>("/api/evaluations/runs", { method: "POST", body: JSON.stringify({ dataset }) });
export const searchCodes = (query: string, system?: string) =>
  apiFetch<CodeEntry[]>(`/api/codes/search?q=${encodeURIComponent(query)}${system ? `&system=${encodeURIComponent(system)}` : ""}&limit=50`);
export const searchModifiers = (query: string) =>
  apiFetch<ModifierEntry[]>(`/api/modifiers/search?q=${encodeURIComponent(query)}&limit=50`);

export const getOverview = () => apiFetch<Overview>("/api/admin/reference-data/overview");
export const startImport = () => apiFetch<{ status: string; message: string }>("/api/admin/reference-data/import", { method: "POST", body: JSON.stringify({ publish: false }) });
export const publishRelease = (id: string) => apiFetch<Release>(`/api/admin/reference-data/releases/${id}/publish`, { method: "POST", body: JSON.stringify({ confirmation: "publish" }) });
