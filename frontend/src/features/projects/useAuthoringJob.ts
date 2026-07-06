import { useEffect, useRef, useState } from "react";

import { jobApi } from "@/lib/api/client";
import type { JobStatusValue } from "@/lib/api/types";

const TERMINAL: readonly JobStatusValue[] = ["succeeded", "failed", "cancelled"];
const POLL_MS = 1500;

export interface AuthoringJobState {
  /** An authoring job is in flight (queued/running). */
  active: boolean;
  /** The terminal status once the job finishes (null while running). */
  outcome: JobStatusValue | null;
  detail: string | null;
}

/** Poll a "Describe it" authoring job (the ``?authoring=<jobId>`` handle) to
 *  completion, so the Tests viewer can show an "authoring…" banner and reload the
 *  list the moment the freshly-proposed cases land. ``onDone`` fires once, on success.
 *
 *  ``onDone`` is read through a ref so a fresh closure each render never restarts the
 *  poll loop (only ``jobId`` does). */
export function useAuthoringJob(
  jobId: string | null,
  onDone: () => void,
): AuthoringJobState {
  const [state, setState] = useState<AuthoringJobState>({
    active: jobId !== null,
    outcome: null,
    detail: null,
  });
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      const result = await jobApi.get(jobId as string);
      if (cancelled) return;
      if (result.ok && result.data) {
        const { status, detail } = result.data;
        if (TERMINAL.includes(status)) {
          setState({ active: false, outcome: status, detail });
          if (status === "succeeded") onDoneRef.current();
          return;
        }
        setState({ active: true, outcome: null, detail });
      }
      timer = setTimeout(() => void poll(), POLL_MS);
    }

    void poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [jobId]);

  return state;
}
