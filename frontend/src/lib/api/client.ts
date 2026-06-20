import type {
  FindingsResponse,
  HealthzResponse,
  IngestResponse,
  JobStatus,
  Project,
  ProjectCreateBody,
  ReadyzResponse,
  RunCreateBody,
  RunResponse,
  RunStatus,
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
  try {
    const response = await fetch(path, {
      ...init,
      signal: controller.signal,
      headers: { Accept: "application/json", ...init?.headers },
    });
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (!response.ok) {
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

export const healthApi = {
  /** GET /healthz — liveness. */
  liveness: () => getJson<HealthzResponse>("/healthz"),
  /** GET /readyz — readiness, including DB reachability. */
  readiness: () => getJson<ReadyzResponse>("/readyz"),
};

export const projectApi = {
  /** POST /projects — register a project. */
  create: (body: ProjectCreateBody) => postJson<Project>(`${API_BASE}/projects`, body),
  /** GET /projects/{id}. */
  get: (id: string) => getJson<Project>(`${API_BASE}/projects/${id}`),
  /** POST /projects/{id}/ingest — kick off Brain build (background job). */
  ingest: (id: string) =>
    postJson<IngestResponse>(`${API_BASE}/projects/${id}/ingest`, {}),
};

export const runApi = {
  /** POST /projects/{id}/runs — start a run (background job). */
  create: (projectId: string, body: RunCreateBody) =>
    postJson<RunResponse>(`${API_BASE}/projects/${projectId}/runs`, body),
  /** GET /runs/{id} — status + summary. */
  get: (runId: string) => getJson<RunStatus>(`${API_BASE}/runs/${runId}`),
  /** GET /runs/{id}/findings — the ranked findings. */
  findings: (runId: string) =>
    getJson<FindingsResponse>(`${API_BASE}/runs/${runId}/findings`),
};

export const jobApi = {
  /** GET /jobs/{id} — poll a background job (e.g. ingest). */
  get: (jobId: string) => getJson<JobStatus>(`${API_BASE}/jobs/${jobId}`),
};
