import { useEffect, useState } from "react";

import { projectApi } from "@/lib/api/client";
import type { ModelStats } from "@/lib/api/types";

export interface ProjectModelState {
  model: ModelStats | null;
  loading: boolean;
  error: string | null;
}

/**
 * The built-model (Brain) summary for a project — whether it's built, how many
 * nodes/edges and of what kinds. `reloadKey` re-fetches when it changes (the Model
 * card passes the ingest status, so the counts refresh the moment a build finishes).
 */
export function useProjectModel(
  projectId: string,
  reloadKey?: unknown,
): ProjectModelState {
  const [state, setState] = useState<ProjectModelState>({
    model: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    void projectApi.model(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setState({ model: result.data, loading: false, error: null });
      } else {
        setState({
          model: null,
          loading: false,
          error: result.error ?? "Couldn't load the model.",
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId, reloadKey]);

  return state;
}
