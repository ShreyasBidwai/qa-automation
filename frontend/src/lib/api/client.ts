import { clearToken, getToken } from "@/lib/auth/session";

import type {
  AuthTokenResponse,
  AuthUser,
  Finding,
  FindingsResponse,
  HealthzResponse,
  IngestResponse,
  JobStatus,
  OpenFindingsResponse,
  PageParams,
  Project,
  ProjectCreateBody,
  ProjectListResponse,
  ProfileUpdateBody,
  ProjectUpdateBody,
  ReadyzResponse,
  RunCreateBody,
  RunListResponse,
  RunResponse,
  RunStatus,
  SignInBody,
  SignUpBody,
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
}

interface ProblemJson {
  title?: string;
  detail?: string;
  code?: string;
}

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";
const REQUEST_TIMEOUT_MS = 8000;

function problemMessage(data: unknown, status: number): string {
  const problem = (data ?? {}) as ProblemJson;
  return problem.detail ?? problem.title ?? `Request failed (${status})`;
}

async function request<T>(path: string, init?: RequestInit): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
      return {
        ok: false,
        status: response.status,
        data: null,
        error: problemMessage(body, response.status),
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
  /** PATCH /runs/{id}/findings/{fid} — set triage disposition; returns the finding. */
  triage: (runId: string, findingId: string, body: TriagePatchBody) =>
    patchJson<Finding>(`${API_BASE}/runs/${runId}/findings/${findingId}`, body),
};

export const jobApi = {
  /** GET /jobs/{id} — poll a background job (e.g. ingest). */
  get: (jobId: string) => getJson<JobStatus>(`${API_BASE}/jobs/${jobId}`),
};
