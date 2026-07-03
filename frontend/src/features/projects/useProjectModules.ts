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
 * Fetched only when the picker is mounted, so it costs nothing until the operator
 * chooses to scope by module. Empty until the model has been built.
 */
export function useProjectModules(projectId: string): ProjectModulesState {
  const [state, setState] = useState<ProjectModulesState>({
    modules: [],
    loading: true,
    error: null,
  });

  useEffect(() => {
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
  }, [projectId]);

  return state;
}
