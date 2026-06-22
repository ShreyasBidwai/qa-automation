import { useEffect, useState } from "react";

import { findingApi, projectApi, runApi } from "@/lib/api/client";
import type { Finding, Project, RunListItem } from "@/lib/api/types";

export interface ProjectOverview {
  project: Project | null;
  runs: RunListItem[];
  openFindings: Finding[];
  openTotal: number;
  loading: boolean;
  /** Set only when the project itself can't be loaded (the page can't render). */
  error: string | null;
}

const RECENT_RUNS = 5;
const OPEN_FINDINGS = 50;

/**
 * Load everything the project landing page (#3a) shows: the project, its recent
 * runs, and its currently-open findings. The project is required (its failure is
 * the page error); runs + findings are best-effort (a slow/failed supplementary
 * fetch degrades to empty, it never blanks the page).
 */
export function useProjectOverview(projectId: string): ProjectOverview {
  const [state, setState] = useState<ProjectOverview>({
    project: null,
    runs: [],
    openFindings: [],
    openTotal: 0,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState({
      project: null,
      runs: [],
      openFindings: [],
      openTotal: 0,
      loading: true,
      error: null,
    });

    void Promise.all([
      projectApi.get(projectId),
      runApi.list(projectId, { limit: RECENT_RUNS, offset: 0 }),
      findingApi.listForProject(projectId, { limit: OPEN_FINDINGS, offset: 0 }),
    ]).then(([project, runs, findings]) => {
      if (cancelled) return;
      if (!project.ok || !project.data) {
        setState({
          project: null,
          runs: [],
          openFindings: [],
          openTotal: 0,
          loading: false,
          error: project.error ?? "Project not found.",
        });
        return;
      }
      setState({
        project: project.data,
        runs: runs.ok && runs.data ? runs.data.items : [],
        openFindings: findings.ok && findings.data ? findings.data.items : [],
        openTotal: findings.ok && findings.data ? findings.data.total : 0,
        loading: false,
        error: null,
      });
    });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return state;
}
