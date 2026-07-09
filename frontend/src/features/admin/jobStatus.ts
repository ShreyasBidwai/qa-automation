import type { JobStatusValue } from "@/lib/api/types";

/** How a job status reads in the console — a dot colour + label. Colour is never the
 *  only signal (the label carries the meaning). `error`/unknown fall back to neutral. */
export interface JobStatusViz {
  label: string;
  dot: string;
  text: string;
}

const VIZ: Record<string, JobStatusViz> = {
  queued: {
    label: "Queued",
    dot: "bg-status-neutral-solid",
    text: "text-status-neutral-fg",
  },
  running: {
    label: "Running",
    dot: "bg-status-info-solid",
    text: "text-status-info-fg",
  },
  succeeded: {
    label: "Succeeded",
    dot: "bg-status-pass-solid",
    text: "text-status-pass-fg",
  },
  failed: { label: "Failed", dot: "bg-status-fail-solid", text: "text-status-fail-fg" },
  cancelled: {
    label: "Cancelled",
    dot: "bg-status-flaky-solid",
    text: "text-status-flaky-fg",
  },
};

export function jobStatusViz(status: string): JobStatusViz {
  return (
    VIZ[status] ?? {
      label: status,
      dot: "bg-status-neutral-solid",
      text: "text-status-neutral-fg",
    }
  );
}

/** A job is cancellable while it's still queued or running. */
export function isCancellable(status: JobStatusValue): boolean {
  return status === "queued" || status === "running";
}

/** A finished-unhappy job (failed/cancelled) can be requeued as a fresh attempt. */
export function isRequeueable(status: JobStatusValue): boolean {
  return status === "failed" || status === "cancelled";
}
