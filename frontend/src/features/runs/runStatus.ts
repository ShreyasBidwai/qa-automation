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
