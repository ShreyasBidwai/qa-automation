import { useEffect, useState } from "react";

import { runApi } from "@/lib/api/client";

const POLL_MS = 4000;

export interface ActiveRunState {
  /** The current in-progress run's handle, once one is found (then pinned). */
  runId: string | null;
  projectId: string | null;
  loading: boolean;
  error: string | null;
}

/**
 * Resolve the caller's current in-progress run for the "Ongoing run" view. While
 * there's none, it polls so a freshly-started run appears on its own; once a run is
 * found it PINS it and stops polling — so the view stays on that run through to its
 * end (RunJourney owns the live→ended lifecycle) instead of flipping back to empty.
 */
export function useActiveRun(): ActiveRunState {
  const [state, setState] = useState<ActiveRunState>({
    runId: null,
    projectId: null,
    loading: true,
    error: null,
  });

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      const result = await runApi.active();
      if (cancelled) return;
      if (result.ok && result.data) {
        if (result.data.run_id) {
          setState({
            runId: result.data.run_id,
            projectId: result.data.project_id,
            loading: false,
            error: null,
          });
          return; // pinned — stop polling
        }
        setState((prev) => ({ ...prev, loading: false, error: null }));
      } else {
        setState((prev) => ({
          ...prev,
          loading: false,
          error: result.error ?? "Couldn't check for a running run.",
        }));
      }
      timer = setTimeout(() => void poll(), POLL_MS);
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, []);

  return state;
}
