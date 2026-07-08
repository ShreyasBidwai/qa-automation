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

/** Which AI backend a project's runs use for generation + triage. Null ⇒ the
 * instance default. The UI never sends an API key — each provider's key is
 * server-side env only (ANTHROPIC_API_KEY / GEMINI_API_KEY). */
export type AiProvider = "anthropic_api" | "claude_cli" | "gemini";

export interface ProjectCreateBody {
  name: string;
  repo_url: string;
  app_url?: string | null;
  auth_config_ref?: string | null;
  stack?: string | null;
  ai_provider?: AiProvider | null;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  repo_url: string;
  app_url: string | null;
  auth_config_ref: string | null;
  stack?: string | null;
  ai_provider?: string | null;
  created_at: string;
}

export interface ModelKindCount {
  kind: string; // endpoint | page | model | table | role
  count: number;
}

/** The built-model (Brain) summary for a project (GET /projects/{id}/model). */
export interface ModelStats {
  built: boolean;
  node_count: number;
  edge_count: number;
  nodes_by_kind: ModelKindCount[];
  last_built_at: string | null;
}

/** One feature area of the app, derived from the Brain (ADR-0061). `total` = its
 *  testable targets; `endpoint_count`/`page_count` split API vs UI (frontend). */
export interface ModuleSummary {
  key: string;
  label: string;
  endpoint_count: number;
  page_count: number;
  total: number;
}

export interface ModuleListResponse {
  modules: ModuleSummary[];
}

/** PATCH body for a project — only the provided fields change (ProjectUpdate). */
export interface ProjectUpdateBody {
  name?: string;
  repo_url?: string;
  app_url?: string | null;
  stack?: string | null;
  ai_provider?: AiProvider | null;
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

// Mirrors the backend ``JobStatus`` enum (app/models/enums.py): the durable job
// queue emits ``queued`` (NOT ``pending``) and can end ``cancelled``. Keeping this
// in lockstep matters — a status the UI doesn't model used to crash the app (a
// non-total status→badge map returned ``undefined``, and StatusBadge threw on it).
export type JobStatusValue =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "cancelled";

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

/** The authoring engine a "Describe it" (mode_c) run uses: `ui` composes a browser
 *  page-journey, `api` authors endpoint-contract tests for the resolved endpoint. */
export type AuthoringLayer = "ui" | "api";

export interface ModeBRunBody {
  mode: "mode_b";
  strategy: SelectionStrategy;
  changeset?: string[];
  max_targets?: number;
  /** Layer scope (ADR-0052): which of ui/api/db to test. Omitted = the full set
   *  (existing behaviour unchanged); must be non-empty when present. */
  layers?: RunLayer[];
  /** Module scope (ADR-0061): feature-area keys to test. Omitted = all modules;
   *  composes with `layers` (a module + `ui` tests that module's frontend). */
  modules?: string[];
}

export interface ModeCRunBody {
  mode: "mode_c";
  prompt: string;
  /** Which authoring engine to use. Omitted = `ui` (the page-journey default). */
  layer?: AuthoringLayer;
}

export type RunCreateBody = ModeBRunBody | ModeCRunBody;

export interface RunResponse {
  run_id: string;
  status: JobStatusValue;
}

/** The caller's current in-progress run (GET /runs/active), or all-null if none.
 *  Powers the "Ongoing run" view; `run_id` is the `/runs/{run_id}/live` handle. */
export interface ActiveRunResponse {
  run_id: string | null;
  project_id: string | null;
  mode: string | null;
  status: JobStatusValue | null;
}

export interface RunStatus {
  run_id: string;
  project_id: string;
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
  // Whether this step has a screenshot to watch — its bytes are fetched (authorized)
  // from GET /runs/{id}/events/screenshot?seq=N. The opaque ref is never exposed.
  has_screenshot?: boolean;
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

// --- generated tests (the Tests viewer) -------------------------------------

/** One generated test as the operator sees it (GET /projects/{id}/tests).
 *  `target` is the human-readable Brain node (e.g. "GET api/orders"); `code` is
 *  the runnable Pest/PHPUnit source. Read-only. */
export interface TestCaseSummary {
  id: string;
  target: string;
  type: string; // happy | negative
  layer: string; // api | ui | db
  oracle_source: string; // characterization | rule-derived | spec-grounded
  framework: string; // pest
  code: string;
  created_at: string;
  origin: string; // generated | edited | proposed | authored
  proposal_status: string | null; // pending | accepted | rejected (null = not a proposal)
}

/** Result of accepting/discarding a proposed case (POST …/tests/{id}/accept|/discard). */
export interface CaseReviewResponse {
  id: string;
  proposal_status: string; // accepted | rejected
  is_current: boolean;
}

export interface TestCaseListResponse {
  items: TestCaseSummary[];
  total: number;
}

/** A CSV row the importer rejected, so QA can fix exactly that line.
 *  `row` is 1-based (0 = a whole-file problem, e.g. a missing header). */
export interface CsvImportRowError {
  row: number;
  message: string;
}

/** Summary of a CSV test-scenario import (POST /projects/{id}/tests/import).
 *  A partial file succeeds — good rows land (`created` + `updated`), bad rows
 *  come back in `errors` for the QA to correct. */
export interface CsvImportResponse {
  total: number;
  created: number;
  updated: number;
  errors: CsvImportRowError[];
}

// --- target-account credentials (ADR-0053) ----------------------------------

/** How a project's runs obtain a target-app account. */
export type CredentialMode = "specific_account" | "polaris_creates";

/** The SAFE credential view — the secret is write-only and NEVER returned.
 *  `has_totp` is true when an authenticator seed is stored (unattended 2FA). */
export interface CredentialStatus {
  mode: string;
  identifier: string | null;
  has_credentials: boolean;
  has_totp: boolean;
}

/** PUT body. `secret` + `totp_secret` are write-only; `secret` (with `identifier`)
 *  is required for a specific account. Omitting `totp_secret` on a specific-account
 *  update preserves any stored seed; polaris_creates clears everything. */
export interface CredentialUpsertBody {
  mode: CredentialMode;
  identifier?: string | null;
  secret?: string | null;
  totp_secret?: string | null;
}

/** The stored login config for the authenticated crawl (ADR-0056). No secret. */
export interface AuthConfigStatus {
  configured: boolean;
  login_url: string | null;
  username_selector: string | null;
  password_selector: string | null;
  submit_selector: string | null;
  otp_selector: string | null;
  otp_submit_selector: string | null;
  success_selector: string | null;
}

/** PUT body for the login config — `login_url` required, selectors optional. */
export interface AuthConfigUpsertBody {
  login_url: string;
  username_selector?: string | null;
  password_selector?: string | null;
  submit_selector?: string | null;
  otp_selector?: string | null;
  otp_submit_selector?: string | null;
  success_selector?: string | null;
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
  // The AI's root-cause classification of the failure (real-bug / bad-test / flaky /
  // infra / unknown), or null if triage didn't run. Distinct from `triage` (the human
  // disposition) — this is the model's read: signal vs. noise, at a glance.
  ai_triage?: string | null;
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

/** The choices a run was started with (ADR-0062) — so recent runs are distinguishable
 *  and re-runnable. Derived from the run's durable job payload. */
export interface RunPreferences {
  mode: string; // mode_b | mode_c
  strategy: string | null; // full_sweep | change_impact (mode_b)
  layers: string[] | null; // ui/api/db subset; null = all
  modules: string[] | null; // module keys; null = all
  changeset_size: number | null; // number of changed files (change_impact)
  layer: string | null; // mode_c authoring layer (ui | api)
}

export interface RunListItem {
  id: string;
  mode: string; // the persisted Run.mode ("B" / "C")
  status: string; // the persisted Run.status (passed/failed/errored/…)
  created_at: string;
  pass_rate: number | null;
  preferences?: RunPreferences | null;
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

// --- account dashboard (ADR-0065) -------------------------------------------

export interface ProjectHealthItem {
  project_id: string;
  name: string;
  status: string; // passing | action_needed | errored | never_run
  pass_rate: number | null;
  open_findings: number;
  last_run_at: string | null;
}

export interface TrendPoint {
  date: string; // YYYY-MM-DD
  runs: number;
  passed: number;
  failed: number;
  errored: number;
  skipped: number;
  pass_rate: number | null;
}

export interface RecentRunItem {
  run_id: string;
  project_id: string;
  project_name: string;
  mode: string;
  status: string;
  pass_rate: number | null;
  created_at: string;
}

export interface AccountDashboard {
  range_days: number;
  projects_total: number;
  projects_by_status: Record<string, number>;
  open_findings: Record<string, number>; // critical / major / minor / total
  project_health: ProjectHealthItem[];
  runs_total: number;
  tests_total: number;
  outcomes: Record<string, number>; // pass / fail / error / skipped
  pass_rate: number | null;
  trend: TrendPoint[];
  recent_runs: RecentRunItem[];
}

// --- operator / admin console (staff-only, cross-tenant) ---------------------
// Mirrors backend/app/api/admin.py + ops.py + incidents.py. Every surface here is
// staff-gated server-side (403 for a non-staff caller); the UI only hides what it
// knows will be refused — the server is the real authority.

/** The staff roles the backend recognises (the allow-list). */
export type StaffRole = "superadmin" | "support" | "billing" | "read_only_ops";

/** The fine-grained actions a staff role grants. `permissions` is widened to
 *  `string[]` on the wire for forward-compat; this names the values we gate on. */
export type StaffPermission =
  | "view_ops"
  | "manage_jobs"
  | "view_tenants"
  | "manage_tenants"
  | "view_users"
  | "manage_users"
  | "view_billing"
  | "manage_billing"
  | "view_audit"
  | "impersonate";

/** GET /admin/me — the signed-in staff member's console identity (403 if not staff). */
export interface AdminMe {
  user_id: string;
  email: string;
  staff_role: string;
  permissions: string[];
}

// Tenants (organizations) ----------------------------------------------------

export interface AdminOrgListItem {
  id: string;
  name: string;
  is_personal: boolean;
  suspended: boolean;
  member_count: number;
  project_count: number;
  created_at: string;
}

export interface AdminOrgList {
  items: AdminOrgListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminOrgMember {
  user_id: string;
  email: string;
  name: string | null;
  role: string;
}

export interface AdminOrgDetail {
  id: string;
  name: string;
  is_personal: boolean;
  suspended: boolean;
  member_count: number;
  project_count: number;
  created_at: string;
  members: AdminOrgMember[];
}

// Users ----------------------------------------------------------------------

export interface AdminUserListItem {
  id: string;
  email: string;
  name: string | null;
  is_active: boolean;
  staff_role: string | null;
  org_count: number;
  created_at: string;
}

export interface AdminUserList {
  items: AdminUserListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminUserOrg {
  org_id: string;
  org_name: string;
  role: string;
}

export interface AdminUserDetail {
  id: string;
  email: string;
  name: string | null;
  is_active: boolean;
  staff_role: string | null;
  created_at: string;
  orgs: AdminUserOrg[];
}

/** POST /admin/users/{id}/staff-role — grant a role name, or null to revoke. */
export interface SetStaffRoleBody {
  staff_role: string | null;
}

// Jobs / queue ---------------------------------------------------------------

/** One job in the durable queue (GET /ops/jobs, POST /admin/jobs/{id}/…). `status`
 *  is a JobStatusValue but stays a string for forward-compat with new statuses. */
export interface JobSummary {
  id: string;
  kind: string;
  status: JobStatusValue;
  project_id: string;
  mode: string | null;
  attempts: number;
  max_attempts: number;
  detail: string | null;
  created_at: string;
  locked_at: string | null;
  finished_at: string | null;
}

export interface JobList {
  items: JobSummary[];
  total: number;
}

/** GET /ops/queue — the cross-tenant queue snapshot. `stuck` = running past the
 *  threshold; `runner_healthy` is the at-a-glance signal (no stuck jobs). */
export interface QueueStats {
  queued: number;
  running: number;
  succeeded: number;
  failed: number;
  cancelled: number;
  stuck: number;
  total: number;
  runner_healthy: boolean;
}

// Staff audit trail ----------------------------------------------------------

export interface StaffAuditItem {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_email: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
}

export interface StaffAuditList {
  items: StaffAuditItem[];
  total: number;
  limit: number;
  offset: number;
}

// Internal incidents (ADR-0047) ----------------------------------------------

/** One captured internal failure (operator diagnostic). Same failure groups under
 *  one `fingerprint`; the traceback is only on the detail view. */
export interface IncidentListItem {
  id: string;
  created_at: string;
  phase: string;
  component: string | null;
  project_id: string | null;
  run_id: string | null;
  exception_type: string;
  message: string;
  fingerprint: string;
}

export interface IncidentList {
  items: IncidentListItem[];
  total: number;
  limit: number;
  offset: number;
}

/** GET /incidents/{id} — the full incident, including the captured traceback. */
export interface IncidentDetail extends IncidentListItem {
  traceback: string | null;
}
