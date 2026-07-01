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

/**
 * Turn a failed build's ``detail`` (the backend error type) into an honest,
 * actionable message — so a config problem (bad repo URL / token) reads as "here's
 * what to fix", never a scary "something broke on our end". Unknown reasons still
 * name the detail rather than hide it.
 */
export function ingestFailureMessage(detail: string | null | undefined): string {
  switch (detail) {
    case "GitCheckoutError":
      return "Couldn't access the repository. Check the repo URL, and that the access token has read permission (and hasn't expired).";
    case "ApiConfigError":
      return "This project isn't fully configured for ingestion — check the repo URL and the selected stack.";
    default:
      return detail
        ? `The model build failed (${detail}). Check the repo URL and access, then try again.`
        : "The model build failed. Check the repo URL and access, then try again.";
  }
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
      // A failed build isn't a Polaris crash — surface WHY (from the job detail) so
      // the operator can fix it, instead of a bare "Failed".
      if (result.data.status === "failed") {
        setError(ingestFailureMessage(result.data.detail));
      }
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
