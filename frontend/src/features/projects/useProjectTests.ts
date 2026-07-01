import { useEffect, useState } from "react";

import { projectApi } from "@/lib/api/client";
import type { TestCaseSummary } from "@/lib/api/types";

export interface ProjectTestsState {
  tests: TestCaseSummary[];
  total: number;
  loading: boolean;
  error: string | null;
}

/** Load a project's generated test cases + their code (read-only viewer). */
export function useProjectTests(projectId: string): ProjectTestsState {
  const [state, setState] = useState<ProjectTestsState>({
    tests: [],
    total: 0,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ ...prev, loading: true, error: null }));
    void projectApi.tests(projectId).then((result) => {
      if (cancelled) return;
      if (result.ok && result.data) {
        setState({
          tests: result.data.items,
          total: result.data.total,
          loading: false,
          error: null,
        });
      } else {
        setState({
          tests: [],
          total: 0,
          loading: false,
          error: result.error ?? "Couldn't load the generated tests.",
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  return state;
}
