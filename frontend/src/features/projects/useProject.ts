import { useEffect, useState } from "react";

import { projectApi } from "@/lib/api/client";
import type { Project } from "@/lib/api/types";

export interface ProjectState {
  project: Project | null;
  error: string | null;
  loading: boolean;
}

/** Fetch a single project by id (GET /projects/{id}). */
export function useProject(id: string): ProjectState {
  const [state, setState] = useState<ProjectState>({
    project: null,
    error: null,
    loading: true,
  });

  useEffect(() => {
    let cancelled = false;
    setState({ project: null, error: null, loading: true });
    void projectApi.get(id).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setState({ project: result.data, error: null, loading: false });
      } else {
        setState({
          project: null,
          error: result.error ?? "Project not found.",
          loading: false,
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [id]);

  return state;
}
