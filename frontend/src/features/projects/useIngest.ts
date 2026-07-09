import { useCallback, useEffect, useRef, useState } from "react";

import { useToast } from "@/components/useToast";
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
  // Tracks the last-seen status so a fresh terminal transition (running → succeeded/
  // failed) fires exactly one toast, not one per poll while already terminal.
  const previousStatus = useRef<JobStatusValue | null>(null);
  const { notify } = useToast();

  const pollJob = useCallback(
    async (jobId: string): Promise<void> => {
      const result = await jobApi.get(jobId);
      if (result.ok && result.data) {
        const next = result.data.status;
        const wasAlreadyTerminal =
          previousStatus.current !== null && isTerminal(previousStatus.current);
        previousStatus.current = next;
        setStatus(next);
        // A failed build isn't a Polaris crash — surface WHY (from the job detail) so
        // the operator can fix it, instead of a bare "Failed".
        if (next === "failed") {
          setError(ingestFailureMessage(result.data.detail));
        }
        // App-wide toast (mission item 3): fires even if the operator has since
        // navigated away from this project's page, because whichever ProjectPage
        // instance is mounted when the poll lands still owns this hook's toast.
        if (!wasAlreadyTerminal && isTerminal(next)) {
          const succeeded = next === "succeeded";
          notify({
            title: succeeded ? "Model build finished" : "Model build failed",
            tone: succeeded ? "success" : "error",
            description: succeeded
              ? undefined
              : ingestFailureMessage(result.data.detail),
          });
        }
        if (!isTerminal(next)) {
          timer.current = setTimeout(() => void pollJob(jobId), POLL_INTERVAL_MS);
        }
        return;
      }
      setError(result.error ?? "Could not check the model build.");
    },
    [notify],
  );

  const start = useCallback(() => {
    setError(null);
    previousStatus.current = null;
    // Optimistic initial state mirrors the server's first status ("queued"), so the
    // badge matches what the first poll returns — no flicker, no unmodeled value.
    setStatus("queued");
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
    busy: status === "queued" || status === "running",
    start,
  };
}
