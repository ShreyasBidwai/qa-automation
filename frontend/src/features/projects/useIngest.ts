import { useCallback, useEffect, useRef, useState } from "react";

import { jobApi, projectApi } from "@/lib/api/client";
import type { JobStatusValue } from "@/lib/api/types";

import { isTerminal } from "../runs/runStatus";
import { POLL_INTERVAL_MS } from "../runs/useRunStatus";

export interface IngestState {
  status: JobStatusValue | null;
  error: string | null;
  busy: boolean;
  start: () => void;
}

/** Kick off a Brain build (POST ingest) and poll the job until terminal. */
export function useIngest(projectId: string): IngestState {
  const [status, setStatus] = useState<JobStatusValue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const pollJob = useCallback(async (jobId: string): Promise<void> => {
    const result = await jobApi.get(jobId);
    if (result.ok && result.data) {
      setStatus(result.data.status);
      if (!isTerminal(result.data.status)) {
        timer.current = setTimeout(() => void pollJob(jobId), POLL_INTERVAL_MS);
      }
      return;
    }
    setError(result.error ?? "Could not check the model build.");
  }, []);

  const start = useCallback(() => {
    setError(null);
    setStatus("pending");
    void projectApi.ingest(projectId).then((result) => {
      if (result.ok && result.data) {
        void pollJob(result.data.job_id);
      } else {
        setStatus(null);
        setError(result.error ?? "Could not start the model build.");
      }
    });
  }, [projectId, pollJob]);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return {
    status,
    error,
    busy: status === "pending" || status === "running",
    start,
  };
}
