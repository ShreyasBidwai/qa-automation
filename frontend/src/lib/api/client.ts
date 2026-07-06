import { clearToken, getToken } from "@/lib/auth/session";

import type {
  ActiveRunResponse,
  AuthTokenResponse,
  AuthUser,
  ChangePasswordBody,
  AuthConfigStatus,
  AuthConfigUpsertBody,
  CaseReviewResponse,
  CredentialStatus,
  CredentialUpsertBody,
  CsvImportResponse,
  DbStateTierResponse,
  DbStateTierUpdateBody,
  DocumentListResponse,
  FieldError,
  Finding,
  FindingsResponse,
  HealthzResponse,
  IngestResponse,
  InviteCreateBody,
  InviteListResponse,
  InviteResponse,
  JobStatus,
  MemberListResponse,
  MemberResponse,
  ModelStats,
  ModuleListResponse,
  OpenFindingsResponse,
  OrgListResponse,
  PageParams,
  Project,
  ProjectCreateBody,
  ProjectDocument,
  ProjectListResponse,
  ProfileUpdateBody,
  ProjectUpdateBody,
  ReadyzResponse,
  RoleUpdateBody,
  RunCreateBody,
  RunEventsResponse,
  RunListResponse,
  RunResponse,
  RunStatus,
  SignInBody,
  SignUpBody,
  TestCaseListResponse,
  TriagePatchBody,
} from "./types";

/**
 * Typed API client (Standards §5: all data access goes through here). Paths are
 * relative; the Vite dev server proxies them to the backend so the browser
 * stays same-origin. Failures are normalized to a result (`ok:false`) with a
 * human-readable `error` — callers render a state instead of crashing. Errors
 * are read from the backend's RFC-9457 problem+json body when present.
 */

export interface ApiResult<T> {
  ok: boolean;
  status: number;
  data: T | null;
  error?: string;
  /** Field-level validation messages from a 422 (problem+json `errors[]`, B11). */
  fieldErrors?: FieldError[];
  /** Seconds to wait, from a 429's `Retry-After` header (B11 rate limiting). */
  retryAfter?: number;
}

interface ProblemJson {
  title?: string;
  detail?: string;
  code?: string;
  errors?: FieldError[];
}

// Exported so the SSE fetch-stream consumer (run events) builds the same base.
export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const REQUEST_TIMEOUT_MS = 8000;
// File upload chunks + embeds server-side, so it needs longer than a JSON call.
const UPLOAD_TIMEOUT_MS = 30000;

/** An honest, voiced "too many attempts" message that respects Retry-After. */
function rateLimitMessage(retryAfter: number): string {
  if (!retryAfter || retryAfter <= 1) {
    return "Too many attempts. Please wait a moment and try again.";
  }
  if (retryAfter < 60) {
    return `Too many attempts. Please try again in ${retryAfter} seconds.`;
  }
  const minutes = Math.ceil(retryAfter / 60);
  return `Too many attempts. Please try again in ${minutes} minute${
    minutes === 1 ? "" : "s"
  }.`;
}

function problemMessage(data: unknown, status: number): string {
  const problem = (data ?? {}) as ProblemJson;
  // Prefer the per-field messages (e.g. the B11 password policy) over the generic
  // "Request validation failed." title, so the surfaced error is the real one.
  if (problem.errors && problem.errors.length > 0) {
    return problem.errors.map((entry) => entry.message).join(" ");
  }
  return problem.detail ?? problem.title ?? `Request failed (${status})`;
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs: number = REQUEST_TIMEOUT_MS,
): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const token = getToken();
  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        // Attach the B2 bearer token on every request when signed in.
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
      // A 401 means the session is gone (expired / revoked) — drop the token so
      // the app falls back to sign-in instead of looping on dead requests.
      if (response.status === 401) clearToken();
      const fieldErrors = (body as ProblemJson | null)?.errors;
      // B11: honour Retry-After on a 429 and voice it instead of a raw title.
      if (response.status === 429) {
        const retryAfter = Number.parseInt(
          response.headers.get("Retry-After") ?? "",
          10,
        );
        const seconds = Number.isFinite(retryAfter) ? retryAfter : 0;
        return {
          ok: false,
          status: 429,
          data: null,
          error: rateLimitMessage(seconds),
          retryAfter: seconds,
        };
      }
      return {
        ok: false,
        status: response.status,
        data: null,
        error: problemMessage(body, response.status),
        fieldErrors: fieldErrors && fieldErrors.length > 0 ? fieldErrors : undefined,
      };
    }
    return { ok: true, status: response.status, data: body as T };
  } catch {
    return { ok: false, status: 0, data: null, error: "Network error" };
  } finally {
    clearTimeout(timer);
  }
}

function getJson<T>(path: string): Promise<ApiResult<T>> {
  return request<T>(path);
}

function postJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function putJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return request<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function patchJson<T>(path: string, body: unknown): Promise<ApiResult<T>> {
  return request<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** DELETE — a 204 (no body) resolves to `ok:true, data:null`. */
function del(path: string): Promise<ApiResult<null>> {
  return request<null>(path, { method: "DELETE" });
}

/** Multipart POST (file upload). No Content-Type — the browser sets the multipart
 *  boundary; the bearer token + error normalization come from `request`. */
function postFormData<T>(path: string, body: FormData): Promise<ApiResult<T>> {
  return request<T>(path, { method: "POST", body }, UPLOAD_TIMEOUT_MS);
}

export const authApi = {
  /** POST /auth/signup — create an account; returns the bearer token + user. */
  signUp: (body: SignUpBody) =>
    postJson<AuthTokenResponse>(`${API_BASE}/auth/signup`, body),
  /** POST /auth/signin — exchange credentials for a bearer token + user. */
  signIn: (body: SignInBody) =>
    postJson<AuthTokenResponse>(`${API_BASE}/auth/signin`, body),
  /** POST /auth/signout — revoke the current session (idempotent, 204). */
  signOut: () => postJson<null>(`${API_BASE}/auth/signout`, {}),
  /** GET /auth/me — the current user (401 without a valid session). */
  me: () => getJson<AuthUser>(`${API_BASE}/auth/me`),
  /** PATCH /auth/me — update the account profile (name / email). */
  updateProfile: (body: ProfileUpdateBody) =>
    patchJson<AuthUser>(`${API_BASE}/auth/me`, body),
  /** POST /auth/change-password — change the password (B2; policy enforced, 204). */
  changePassword: (body: ChangePasswordBody) =>
    postJson<null>(`${API_BASE}/auth/change-password`, body),
};

/**
 * Organizations / team membership (B3, ADR-0032/0033). The API is the security
 * boundary: every management call is authorized server-side by the caller's role
 * (owner-only owner management, last-owner guard) and surfaces 403/409 — the
 * client only hides actions it knows will be refused, it never grants access.
 */
export const orgApi = {
  /** GET /orgs — the orgs the caller belongs to, with their role in each. */
  listOrgs: () => getJson<OrgListResponse>(`${API_BASE}/orgs`),
  /** GET /orgs/{id}/members — the org's members + their roles. */
  listMembers: (orgId: string) =>
    getJson<MemberListResponse>(`${API_BASE}/orgs/${orgId}/members`),
  /** GET /orgs/{id}/invites — pending/accepted invites (owner/admin only). */
  listInvites: (orgId: string) =>
    getJson<InviteListResponse>(`${API_BASE}/orgs/${orgId}/invites`),
  /** POST /orgs/{id}/invites — invite a member (owner/admin; owner-only to invite owners). */
  invite: (orgId: string, body: InviteCreateBody) =>
    postJson<InviteResponse>(`${API_BASE}/orgs/${orgId}/invites`, body),
  /** PATCH /orgs/{id}/members/{uid} — change a member's role. */
  changeRole: (orgId: string, userId: string, body: RoleUpdateBody) =>
    patchJson<MemberResponse>(`${API_BASE}/orgs/${orgId}/members/${userId}`, body),
  /** DELETE /orgs/{id}/members/{uid} — remove a member (204). */
  removeMember: (orgId: string, userId: string) =>
    del(`${API_BASE}/orgs/${orgId}/members/${userId}`),
};

export const healthApi = {
  /** GET /healthz — liveness. */
  liveness: () => getJson<HealthzResponse>("/healthz"),
  /** GET /readyz — readiness, including DB reachability. */
  readiness: () => getJson<ReadyzResponse>("/readyz"),
};

function pageQuery({ limit, offset }: PageParams): string {
  return `limit=${limit}&offset=${offset}`;
}

export const projectApi = {
  /** POST /projects — register a project. */
  create: (body: ProjectCreateBody) => postJson<Project>(`${API_BASE}/projects`, body),
  /** GET /projects/{id}. */
  get: (id: string) => getJson<Project>(`${API_BASE}/projects/${id}`),
  /** GET /projects/{id}/model — the built-model summary (node/edge counts, by kind). */
  model: (id: string) => getJson<ModelStats>(`${API_BASE}/projects/${id}/model`),
  /** GET /projects/{id}/modules — the feature areas a run can be scoped to (ADR-0061). */
  modules: (id: string) =>
    getJson<ModuleListResponse>(`${API_BASE}/projects/${id}/modules`),
  /** GET /projects — list projects (bounded, newest first). */
  list: (params: PageParams) =>
    getJson<ProjectListResponse>(`${API_BASE}/projects?${pageQuery(params)}`),
  /** PATCH /projects/{id} — partial update (name, repo, app_url, stack). */
  update: (id: string, body: ProjectUpdateBody) =>
    patchJson<Project>(`${API_BASE}/projects/${id}`, body),
  /** DELETE /projects/{id} — soft-delete (ADR-0029); returns 204. */
  remove: (id: string) => del(`${API_BASE}/projects/${id}`),
  /** POST /projects/{id}/ingest — kick off Brain build (background job). */
  ingest: (id: string) =>
    postJson<IngestResponse>(`${API_BASE}/projects/${id}/ingest`, {}),
  /** GET /projects/{id}/tests — the generated test cases + their code (VIEW).
   *  Pass ``run`` to scope to just the cases a single run exercised (ADR-0062). */
  tests: (id: string, run?: string | null) =>
    getJson<TestCaseListResponse>(
      run
        ? `${API_BASE}/projects/${id}/tests?run=${encodeURIComponent(run)}`
        : `${API_BASE}/projects/${id}/tests`,
    ),
  /** POST /projects/{id}/tests/import — import QA-authored scenarios from a CSV
   *  (multipart, MANAGE_PROJECT). Returns a per-row summary; bad rows report. */
  importTests: (id: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return postFormData<CsvImportResponse>(
      `${API_BASE}/projects/${id}/tests/import`,
      form,
    );
  },
  /** POST /projects/{id}/tests/{caseId}/accept — adopt a pending proposal (it runs). */
  acceptTest: (id: string, caseId: string) =>
    postJson<CaseReviewResponse>(
      `${API_BASE}/projects/${id}/tests/${caseId}/accept`,
      {},
    ),
  /** POST /projects/{id}/tests/{caseId}/discard — reject a pending proposal. */
  discardTest: (id: string, caseId: string) =>
    postJson<CaseReviewResponse>(
      `${API_BASE}/projects/${id}/tests/${caseId}/discard`,
      {},
    ),
  /** GET /projects/{id}/db-state-tier — the DB-state testing tier (needs VIEW). */
  getDbStateTier: (id: string) =>
    getJson<DbStateTierResponse>(`${API_BASE}/projects/${id}/db-state-tier`),
  /** PUT /projects/{id}/db-state-tier — set the tier (MANAGE_PROJECT; bad value → 422). */
  setDbStateTier: (id: string, body: DbStateTierUpdateBody) =>
    putJson<DbStateTierResponse>(`${API_BASE}/projects/${id}/db-state-tier`, body),
};

export const findingApi = {
  /** GET /findings — the global inbox: open findings across the user's projects. */
  listOpen: (params: PageParams) =>
    getJson<OpenFindingsResponse>(`${API_BASE}/findings?${pageQuery(params)}`),
  /** GET /projects/{id}/findings — open findings for one project. */
  listForProject: (projectId: string, params: PageParams) =>
    getJson<OpenFindingsResponse>(
      `${API_BASE}/projects/${projectId}/findings?${pageQuery(params)}`,
    ),
};

export const runApi = {
  /** POST /projects/{id}/runs — start a run (background job). */
  create: (projectId: string, body: RunCreateBody) =>
    postJson<RunResponse>(`${API_BASE}/projects/${projectId}/runs`, body),
  /** GET /runs/active — the caller's current in-progress run (Ongoing view), or nulls. */
  active: () => getJson<ActiveRunResponse>(`${API_BASE}/runs/active`),
  /** POST /runs/{id}/rerun — start a fresh run with the same preferences (ADR-0062). */
  rerun: (runId: string) =>
    postJson<RunResponse>(`${API_BASE}/runs/${runId}/rerun`, {}),
  /** GET /projects/{id}/runs — list a project's runs (bounded, newest first). */
  list: (projectId: string, params: PageParams) =>
    getJson<RunListResponse>(
      `${API_BASE}/projects/${projectId}/runs?${pageQuery(params)}`,
    ),
  /** GET /runs/{id} — status + summary. */
  get: (runId: string) => getJson<RunStatus>(`${API_BASE}/runs/${runId}`),
  /** GET /runs/{id}/findings — the ranked findings. */
  findings: (runId: string) =>
    getJson<FindingsResponse>(`${API_BASE}/runs/${runId}/findings`),
  /** GET /runs/{id}/events — replay/poll ordered progress events (after_seq cursor).
   *  Serves a finished run's full journey AND the live view's on-connect catch-up. */
  events: (runId: string, afterSeq?: number) =>
    getJson<RunEventsResponse>(
      `${API_BASE}/runs/${runId}/events${
        afterSeq != null ? `?after_seq=${afterSeq}` : ""
      }`,
    ),
  /** PATCH /runs/{id}/findings/{fid} — set triage disposition; returns the finding. */
  triage: (runId: string, findingId: string, body: TriagePatchBody) =>
    patchJson<Finding>(`${API_BASE}/runs/${runId}/findings/${findingId}`, body),
};

export const jobApi = {
  /** GET /jobs/{id} — poll a background job (e.g. ingest). */
  get: (jobId: string) => getJson<JobStatus>(`${API_BASE}/jobs/${jobId}`),
};

/** Project documents (ADR-0052): attach by upload / list / remove. Upload + delete
 *  are MANAGE_PROJECT (the server 403s otherwise); listing needs VIEW. */
export const documentApi = {
  /** GET /projects/{id}/documents. */
  list: (projectId: string) =>
    getJson<DocumentListResponse>(`${API_BASE}/projects/${projectId}/documents`),
  /** POST /projects/{id}/documents/upload — multipart (file + doc_kind, optional title). */
  upload: (
    projectId: string,
    file: File,
    opts?: { docKind?: string; title?: string },
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("doc_kind", opts?.docKind ?? "requirements");
    if (opts?.title) form.append("title", opts.title);
    return postFormData<ProjectDocument>(
      `${API_BASE}/projects/${projectId}/documents/upload`,
      form,
    );
  },
  /** DELETE /projects/{id}/documents/{documentId}. */
  remove: (projectId: string, documentId: string) =>
    del(`${API_BASE}/projects/${projectId}/documents/${documentId}`),
};

/** Target-account credentials (ADR-0053), all MANAGE_PROJECT. The secret is
 *  write-only — GET never returns it (only mode/identifier/has_credentials). */
export const credentialApi = {
  /** GET /projects/{id}/credentials — the safe status (never the secret). */
  get: (projectId: string) =>
    getJson<CredentialStatus>(`${API_BASE}/projects/${projectId}/credentials`),
  /** PUT /projects/{id}/credentials — set/replace; returns the safe status. */
  put: (projectId: string, body: CredentialUpsertBody) =>
    putJson<CredentialStatus>(`${API_BASE}/projects/${projectId}/credentials`, body),
  /** DELETE /projects/{id}/credentials — clear stored credentials. */
  remove: (projectId: string) => del(`${API_BASE}/projects/${projectId}/credentials`),
};

/** Login config for the authenticated crawl (ADR-0056) — where/how runs sign in.
 *  Carries NO secret (those go to credentialApi); PUT/DELETE are MANAGE_PROJECT. */
export const authConfigApi = {
  /** GET /projects/{id}/auth-config — the stored login config, or configured=false. */
  get: (projectId: string) =>
    getJson<AuthConfigStatus>(`${API_BASE}/projects/${projectId}/auth-config`),
  /** PUT /projects/{id}/auth-config — set/replace the login config. */
  put: (projectId: string, body: AuthConfigUpsertBody) =>
    putJson<AuthConfigStatus>(`${API_BASE}/projects/${projectId}/auth-config`, body),
  /** DELETE /projects/{id}/auth-config — clear it (crawl reverts to unauthenticated). */
  remove: (projectId: string) => del(`${API_BASE}/projects/${projectId}/auth-config`),
};
