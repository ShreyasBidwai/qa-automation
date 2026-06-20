/**
 * A small client-side registry of the projects and runs this browser has
 * created. The backend has no list endpoint yet (only get-by-id), so the
 * Projects / Runs lists are sourced from here and persisted in localStorage.
 * When list endpoints land, swap this source — the rest of the UI is unchanged.
 *
 * Snapshots are cached so the getters return a stable reference between writes
 * (required by `useSyncExternalStore`).
 */

import type { JobStatusValue } from "./api/types";

export interface ProjectRef {
  id: string;
  name: string;
  slug: string;
  createdAt: string;
}

export interface RunRef {
  runId: string;
  projectId: string;
  projectName: string;
  mode: string;
  status: JobStatusValue;
  startedAt: string;
}

const PROJECTS_KEY = "polaris.projects";
const RUNS_KEY = "polaris.runs";
const REGISTRY_EVENT = "polaris:registry";

let projectsCache: ProjectRef[] | null = null;
let runsCache: RunRef[] | null = null;

function read<T>(key: string): T[] {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T[]) : [];
  } catch {
    return [];
  }
}

function write<T>(key: string, items: T[]): void {
  if (key === PROJECTS_KEY) projectsCache = items as ProjectRef[];
  if (key === RUNS_KEY) runsCache = items as RunRef[];
  try {
    window.localStorage.setItem(key, JSON.stringify(items));
  } catch {
    // Storage unavailable (private mode / quota) — the in-memory cache still works.
  }
  window.dispatchEvent(new Event(REGISTRY_EVENT));
}

export function subscribeRegistry(onChange: () => void): () => void {
  const onStorage = () => {
    projectsCache = null; // another tab changed it — re-read on next snapshot
    runsCache = null;
    onChange();
  };
  window.addEventListener(REGISTRY_EVENT, onChange);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(REGISTRY_EVENT, onChange);
    window.removeEventListener("storage", onStorage);
  };
}

export function listProjects(): ProjectRef[] {
  if (projectsCache === null) projectsCache = read<ProjectRef>(PROJECTS_KEY);
  return projectsCache;
}

export function rememberProject(project: ProjectRef): void {
  const existing = listProjects().filter((p) => p.id !== project.id);
  write(PROJECTS_KEY, [project, ...existing]);
}

export function listRuns(): RunRef[] {
  if (runsCache === null) runsCache = read<RunRef>(RUNS_KEY);
  return runsCache;
}

export function rememberRun(run: RunRef): void {
  const existing = listRuns().filter((r) => r.runId !== run.runId);
  write(RUNS_KEY, [run, ...existing]);
}

export function updateRunStatus(runId: string, status: JobStatusValue): void {
  const next = listRuns().map((r) => (r.runId === runId ? { ...r, status } : r));
  write(RUNS_KEY, next);
}
