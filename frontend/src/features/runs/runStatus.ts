import type { StatusDescriptor } from "@/features/system-status/status";
import type { JobStatusValue } from "@/lib/api/types";

/**
 * Map a background job/run status to a badge descriptor. Colour is never the
 * sole signal — the label carries the meaning (StatusBadge adds an icon).
 */
export function runStatusDescriptor(status: JobStatusValue): StatusDescriptor {
  switch (status) {
    case "pending":
      return { level: "info", label: "Queued" };
    case "running":
      return { level: "info", label: "Running…" };
    case "succeeded":
      return { level: "pass", label: "Done" };
    case "failed":
      return { level: "fail", label: "Failed" };
  }
}

export const TERMINAL_STATUSES: ReadonlySet<JobStatusValue> = new Set([
  "succeeded",
  "failed",
]);

export function isTerminal(status: JobStatusValue): boolean {
  return TERMINAL_STATUSES.has(status);
}

/**
 * Map a persisted Run.status (passed/failed/errored/running/pending) to a badge —
 * distinct from the job-handle statuses above (succeeded/…) the progress view
 * uses. Used by the runs list, which reads Run rows.
 */
export function runRowStatusDescriptor(status: string): StatusDescriptor {
  switch (status) {
    case "passed":
      return { level: "pass", label: "Passed" };
    case "failed":
      return { level: "fail", label: "Failed" };
    case "errored":
      return { level: "fail", label: "Errored" };
    case "running":
      return { level: "info", label: "Running…" };
    case "pending":
      return { level: "info", label: "Queued" };
    default:
      return { level: "neutral", label: status };
  }
}
