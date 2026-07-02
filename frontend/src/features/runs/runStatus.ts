import type { StatusDescriptor } from "@/features/system-status/status";
import type { JobStatusValue } from "@/lib/api/types";

/**
 * Map a background job/run status to a badge descriptor. Colour is never the
 * sole signal — the label carries the meaning (StatusBadge adds an icon).
 */
export function runStatusDescriptor(status: JobStatusValue): StatusDescriptor {
  switch (status) {
    case "queued":
      return { level: "info", label: "Queued" };
    case "running":
      return { level: "info", label: "Running…" };
    case "succeeded":
      return { level: "pass", label: "Done" };
    case "failed":
      return { level: "fail", label: "Failed" };
    case "cancelled":
      return { level: "neutral", label: "Cancelled" };
    default:
      // NEVER return undefined — a status the backend adds that we haven't mapped
      // yet must degrade to a neutral badge, not throw inside StatusBadge and take
      // the whole app down to the error boundary. Show the raw value so it's honest.
      return { level: "neutral", label: status };
  }
}

export const TERMINAL_STATUSES: ReadonlySet<JobStatusValue> = new Set([
  "succeeded",
  "failed",
  "cancelled",
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
      // A run that couldn't complete (infra), NOT a test that found a real bug —
      // its own level so users don't read it as a failure (architecture-review #4).
      return { level: "error", label: "Errored" };
    case "running":
      return { level: "info", label: "Running…" };
    case "pending":
      return { level: "info", label: "Queued" };
    default:
      return { level: "neutral", label: status };
  }
}
