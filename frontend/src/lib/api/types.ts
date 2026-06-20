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

/** The deepest failing node (the grouping anchor) — what broke, structurally. */
export interface FindingLocationAnchor {
  node_type: string | null; // a NodeKind value: "table" | "endpoint" | "page"
  identifier: string | null;
  label: string;
}

/** The anchor plus the full cross-layer blast path (page → endpoint → table). */
export interface FindingLocation {
  anchor: FindingLocationAnchor;
  page?: string | null;
  endpoints?: string[];
  tables?: string[];
}

/** One failing test: a short "what failed" line + its oracle trust signal. */
export interface EvidenceItem {
  summary: string;
  oracle_source: string; // "rule-derived" | "characterization" | "spec-grounded"
  reference?: string | null;
}

/** Cross-run history: the T7.4 classification + its supporting fields. */
export interface FindingHistory {
  classification: string; // "new" | "known" | "regression" | "flaky"
  occurrence_count: number;
  first_seen_run?: string | null;
  last_seen_run?: string | null;
}

export type TriageStatusValue =
  | "open"
  | "acknowledged"
  | "resolved"
  | "wont_fix"
  | "false_positive";

/** A finding's triage disposition (ADR-0027) — keyed by the logical issue, so it
 *  persists across runs. Absent record = open; actor (who) is deferred to auth. */
export interface Triage {
  status: TriageStatusValue;
  note?: string | null;
  triaged_at?: string | null;
}

/** PATCH body to set a finding's triage disposition. */
export interface TriagePatchBody {
  status: TriageStatusValue;
  note?: string | null;
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
  // Widened detail (now exposed by FindingResponse). Optional on the type so the
  // drawer still renders gracefully against an older/partial payload, but the
  // live API always populates these (T6.3: render gracefully, never invent).
  confidence_mixed?: boolean;
  expected?: Record<string, unknown> | null;
  location?: FindingLocation | null;
  evidence?: EvidenceItem[] | null;
  history?: FindingHistory | null;
  evidence_ref?: string | null;
  triage?: Triage | null;
}

export interface FindingsResponse {
  run_id: string;
  count: number;
  findings: Finding[];
}

// --- list endpoints ---------------------------------------------------------

export interface ProjectListItem {
  id: string;
  name: string;
  slug: string;
  repo_url: string;
  app_url: string | null;
  created_at: string;
}

export interface ProjectListResponse {
  items: ProjectListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface RunListItem {
  id: string;
  mode: string; // the persisted Run.mode ("B" / "C")
  status: string; // the persisted Run.status (passed/failed/errored/…)
  created_at: string;
  pass_rate: number | null;
}

export interface RunListResponse {
  items: RunListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface PageParams {
  limit: number;
  offset: number;
}
