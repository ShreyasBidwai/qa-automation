import { useEffect, useState } from "react";

import { projectApi } from "@/lib/api/client";
import type { ModuleSummary } from "@/lib/api/types";

export interface ProjectModulesState {
  modules: ModuleSummary[];
  loading: boolean;
  error: string | null;
}

/**
 * The project's feature areas ("modules", ADR-0061) for the run form's module picker.
 * `enabled` gates the fetch so it costs nothing until the operator is on the autonomous
 * mode (where module scoping lives). Empty until the model has been built.
 */
export function useProjectModules(
  projectId: string,
  enabled = true,
): ProjectModulesState {
  const [state, setState] = useState<ProjectModulesState>({
    modules: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    void projectApi.modules(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setState({ modules: result.data.modules, loading: false, error: null });
      } else {
        setState({
          modules: [],
          loading: false,
          error: result.error ?? "Couldn't load the modules.",
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, enabled]);

  return state;
}
