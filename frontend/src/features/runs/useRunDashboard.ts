import { useCallback, useEffect, useState } from "react";

import { runApi } from "@/lib/api/client";
import type { Finding, JobStatusValue } from "@/lib/api/types";

export interface DashboardState {
  status: JobStatusValue | null;
  mode: string;
  summary: Record<string, unknown> | null;
  findings: Finding[];
  loading: boolean;
  error: string | null;
}

export interface DashboardController extends DashboardState {
  /** Replace one finding in place (e.g. after a triage PATCH) — keeps the list
   *  and the open drawer in sync without a refetch. */
  replaceFinding: (updated: Finding) => void;
}

const INITIAL: DashboardState = {
  status: null,
  mode: "",
  summary: null,
  findings: [],
  loading: true,
  error: null,
};

/** Load a completed run's summary + ranked findings (GET /runs/{id}[, /findings]). */
export function useRunDashboard(runId: string): DashboardController {
  const [state, setState] = useState<DashboardState>(INITIAL);

  const replaceFinding = useCallback((updated: Finding) => {
    setState((prev) => ({
      ...prev,
      findings: prev.findings.map((f) => (f.id === updated.id ? updated : f)),
    }));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState(INITIAL);

    void Promise.all([runApi.get(runId), runApi.findings(runId)]).then(
      ([run, findings]) => {
        if (cancelled) return;
        if (!run.ok || !run.data) {
          setState({
            ...INITIAL,
            loading: false,
            error: run.error ?? "Could not load the run.",
          });
          return;
        }
        if (!findings.ok || !findings.data) {
          setState({
            status: run.data.status,
            mode: run.data.mode,
            summary: run.data.summary,
            findings: [],
            loading: false,
            error: findings.error ?? "Could not load the findings.",
          });
          return;
        }
        setState({
          status: run.data.status,
          mode: run.data.mode,
          summary: run.data.summary,
          findings: findings.data.findings,
          loading: false,
          error: null,
        });
      },
    );

    return () => {
      cancelled = true;
    };
  }, [runId]);

  return { ...state, replaceFinding };
}
