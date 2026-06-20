/** Shapes exchanged with the backend (see backend/app/api/schemas.py). */

// --- health (top-level endpoints) -------------------------------------------

export interface HealthzResponse {
  status: string;
}

export interface ReadyzResponse {
  status: string;
  checks?: { database?: string };
  reason?: string;
}

// --- projects ---------------------------------------------------------------

export interface ProjectCreateBody {
  name: string;
  repo_url: string;
  app_url?: string | null;
  auth_config_ref?: string | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  repo_url: string;
  app_url: string | null;
  auth_config_ref: string | null;
  created_at: string;
}

// --- jobs / ingest ----------------------------------------------------------

export type JobStatusValue = "pending" | "running" | "succeeded" | "failed";

export interface IngestResponse {
  job_id: string;
  status: JobStatusValue;
}

export interface JobStatus {
  job_id: string;
  kind: string;
  status: JobStatusValue;
  run_id: string | null;
  detail: string | null;
}

// --- runs -------------------------------------------------------------------

export type SelectionStrategy = "full_sweep" | "change_impact";

export interface ModeBRunBody {
  mode: "mode_b";
  strategy: SelectionStrategy;
  changeset?: string[];
  max_targets?: number;
}

export interface ModeCRunBody {
  mode: "mode_c";
  prompt: string;
}

export type RunCreateBody = ModeBRunBody | ModeCRunBody;

export interface RunResponse {
  run_id: string;
  status: JobStatusValue;
}

export interface RunStatus {
  run_id: string;
  mode: string;
  status: JobStatusValue;
  summary: Record<string, unknown> | null;
}

// --- findings ---------------------------------------------------------------

/** The cross-layer location of a finding (page → endpoint → table). */
export interface FindingLocation {
  page?: string | null;
  endpoints?: string[];
  tables?: string[];
}

export interface FindingHistoryEntry {
  run_id: string;
  status: string;
  at?: string | null;
}

export interface Finding {
  id: string;
  root_cause_key: string;
  title: string;
  layer: string;
  severity: string;
  status: string;
  oracle_source: string;
  explains_count: number;
  // Richer detail the backend model carries but FindingResponse does NOT expose
  // yet — optional, so the detail drawer renders them when present and flags them
  // when absent (T6.3: render gracefully, never invent).
  expected?: Record<string, unknown> | null;
  actual?: Record<string, unknown> | string | null;
  location?: FindingLocation | null;
  evidence_ref?: string | null;
  history?: FindingHistoryEntry[] | null;
}

export interface FindingsResponse {
  run_id: string;
  count: number;
  findings: Finding[];
}
