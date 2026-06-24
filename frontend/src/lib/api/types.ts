/** Shapes exchanged with the backend (see backend/app/api/schemas.py). */

// --- auth (B2 sessions / B3 profile) ----------------------------------------

export interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  created_at: string;
}

/** Sign-up / sign-in result: the bearer token + the authenticated user. */
export interface AuthTokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface SignUpBody {
  email: string;
  password: string;
}

export interface SignInBody {
  email: string;
  password: string;
}

/** PATCH /auth/me — partial account-profile update (only provided fields change). */
export interface ProfileUpdateBody {
  name?: string | null;
  email?: string;
}

/** POST /auth/change-password (B2/B11). The policy is enforced server-side. */
export interface ChangePasswordBody {
  current_password: string;
  new_password: string;
}

/** One field-level validation message from a 422 (problem+json `errors[]`, B11). */
export interface FieldError {
  field: string;
  message: string;
}

// --- organizations / membership / invites (B3, ADR-0032/0033) ---------------

export type OrgRoleName = "owner" | "admin" | "member" | "viewer";

export interface OrgResponse {
  id: string;
  name: string;
  is_personal: boolean;
  role: OrgRoleName; // the caller's role in THIS org (authoritative for gating)
  created_at: string;
}

export interface OrgListResponse {
  items: OrgResponse[];
  total: number;
}

export interface MemberResponse {
  user_id: string;
  email: string;
  name: string | null;
  role: OrgRoleName;
  created_at: string; // when they joined the org
}

export interface MemberListResponse {
  items: MemberResponse[];
  total: number;
}

export interface RoleUpdateBody {
  role: OrgRoleName;
}

export interface InviteCreateBody {
  email: string;
  role: OrgRoleName;
}

/** A pending/accepted invite — deliberately WITHOUT the token (ADR-0033). */
export interface InviteResponse {
  id: string;
  email: string;
  role: OrgRoleName;
  expires_at: string;
  accepted_at: string | null;
  created_at: string;
}

export interface InviteListResponse {
  items: InviteResponse[];
  total: number;
}

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
  stack?: string | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  repo_url: string;
  app_url: string | null;
  auth_config_ref: string | null;
  stack?: string | null;
  created_at: string;
}

/** PATCH body for a project — only the provided fields change (ProjectUpdate). */
export interface ProjectUpdateBody {
  name?: string;
  repo_url?: string;
  app_url?: string | null;
  stack?: string | null;
}

/**
 * Per-project DB-state testing tier (B10, ADR-0043). Gates whether a run may make
 * cross-layer assertions directly against the target database:
 *  - `off`       — no DB-state testing (default).
 *  - `read_only` — DB-state assertions that only read (SELECT); never writes.
 *  - `full`      — write-capable DB-state testing (safe only against a disposable,
 *                  non-production target; the backend also refuses prod at run time).
 */
export type DbStateTier = "off" | "read_only" | "full";

export interface DbStateTierResponse {
  project_id: string;
  tier: DbStateTier;
}

export interface DbStateTierUpdateBody {
  tier: DbStateTier;
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

/** Which layers a run exercises (ADR-0052). Values match the FindingLayer vocab. */
export type RunLayer = "ui" | "api" | "db";

export interface ModeBRunBody {
  mode: "mode_b";
  strategy: SelectionStrategy;
  changeset?: string[];
  max_targets?: number;
  /** Layer scope (ADR-0052): which of ui/api/db to test. Omitted = the full set
   *  (existing behaviour unchanged); must be non-empty when present. */
  layers?: RunLayer[];
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

// --- run progress events (live run view, ADR-0050) --------------------------

/** A step's lifecycle status: `started` opens it, the rest close it. */
export type RunEventStatus = "started" | "passed" | "failed" | "skipped";

/** One ordered run-progress event (GET /runs/{id}/events[/stream]). `seq` is a
 *  per-run monotonic cursor; `detail` is optional structured context (counts,
 *  endpoint, expected/actual, …); `status` is widened to string for forward-compat. */
export interface RunProgressEvent {
  seq: number;
  phase: string;
  step: string;
  status: string;
  detail?: Record<string, unknown> | null;
  timestamp: string; // ISO 8601
}

export interface RunEventsResponse {
  run_id: string;
  events: RunProgressEvent[];
}

// --- project documents (ADR-0052) -------------------------------------------

/** Accepted document kinds (kept in sync with the backend DocumentKind literal). */
export type DocumentKind =
  | "requirements"
  | "api_contract"
  | "user_flow"
  | "acceptance_criteria"
  | "other";

export interface ProjectDocument {
  id: string;
  title: string;
  doc_kind: string;
  chunk_count: number;
  created_at: string;
}

export interface DocumentListResponse {
  items: ProjectDocument[];
  total: number;
}

// --- target-account credentials (ADR-0053) ----------------------------------

/** How a project's runs obtain a target-app account. */
export type CredentialMode = "specific_account" | "polaris_creates";

/** The SAFE credential view — the secret is write-only and NEVER returned. */
export interface CredentialStatus {
  mode: string;
  identifier: string | null;
  has_credentials: boolean;
}

/** PUT body. `secret` is write-only; required (with `identifier`) for a specific
 *  account, omitted for polaris_creates (which clears any stored secret). */
export interface CredentialUpsertBody {
  mode: CredentialMode;
  identifier?: string | null;
  secret?: string | null;
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
  // Present on the live FindingResponse — the global inbox spans projects/runs, so
  // a row can link back to its run. Optional on the type for older/partial payloads.
  project_id?: string;
  run_id?: string;
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

/** The currently-open findings inbox (ADR-0028) — paginated, severity-ranked. */
export interface OpenFindingsResponse {
  items: Finding[];
  total: number;
  limit: number;
  offset: number;
}

// --- list endpoints ---------------------------------------------------------

/** A project's most-recent run, compactly (for the projects list). */
export interface LastRunSummary {
  run_id: string;
  mode: string;
  status: string;
  pass_rate: number | null;
  finished_at: string | null; // null while running / never finished
  created_at: string;
}

export interface ProjectListItem {
  id: string;
  name: string;
  slug: string;
  repo_url: string;
  app_url: string | null;
  created_at: string;
  // Widened read-time summary (ADR-0045). Optional so an older/partial payload
  // still type-checks and degrades to the honest never-run treatment.
  stack?: string | null;
  /** Overall: never_run | errored | action_needed | passing. */
  status?: string;
  open_findings_count?: number;
  last_run?: LastRunSummary | null;
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
