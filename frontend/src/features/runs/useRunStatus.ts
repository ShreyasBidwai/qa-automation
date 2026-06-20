import { useEffect, useRef, useState } from "react";

import { runApi } from "@/lib/api/client";
import type { JobStatusValue } from "@/lib/api/types";
import { updateRunStatus } from "@/lib/registry";

import { isTerminal } from "./runStatus";

export const POLL_INTERVAL_MS = 1500;

export interface RunState {
  status: JobStatusValue | null;
  mode: string;
  summary: Record<string, unknown> | null;
  error: string | null;
  loading: boolean;
}

const INITIAL: RunState = {
  status: null,
  mode: "",
  summary: null,
  error: null,
  loading: true,
};

/**
 * Poll a run until it reaches a terminal status (succeeded / failed). Stops
 * polling once terminal; retries on transient errors. Mirrors the system-status
 * container-hook pattern (Standards §5).
 */
export function useRunStatus(runId: string): RunState {
  const [state, setState] = useState<RunState>(INITIAL);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState(INITIAL);

    async function poll(): Promise<void> {
      const result = await runApi.get(runId);
      if (cancelled) return;

      if (result.ok && result.data) {
        const { status, mode, summary } = result.data;
        setState({ status, mode, summary, error: null, loading: false });
        updateRunStatus(runId, status);
        if (!isTerminal(status)) {
          timer.current = setTimeout(() => void poll(), POLL_INTERVAL_MS);
        }
        return;
      }

      setState((prev) => ({
        ...prev,
        error: result.error ?? "Could not load the run.",
        loading: false,
      }));
      timer.current = setTimeout(() => void poll(), POLL_INTERVAL_MS);
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [runId]);

  return state;
}
