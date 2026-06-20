import { Link } from "@/components/Link";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";

import { isTerminal, runStatusDescriptor } from "./runStatus";
import { useRunStatus } from "./useRunStatus";

// Phase labels are intentionally distinct from the status badge labels
// ("Queued" / "Running…" / "Done") so the progress track reads as its own step.
const STEPS: { key: string; label: string; reached: (s: string) => boolean }[] = [
  { key: "queued", label: "Queued", reached: () => true },
  {
    key: "running",
    label: "Executing",
    reached: (s) => s === "running" || s === "succeeded" || s === "failed",
  },
  {
    key: "done",
    label: "Complete",
    reached: (s) => s === "succeeded" || s === "failed",
  },
];

/** Live run progress: queued → running → done, polling until terminal. */
export function RunStatusView({ runId }: { runId: string }) {
  const run = useRunStatus(runId);

  if (run.loading && run.status === null) {
    return <p className="text-sm text-muted-foreground">Loading run…</p>;
  }

  const status = run.status ?? "pending";
  const descriptor = runStatusDescriptor(status);
  const done = isTerminal(status);

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center gap-3">
        <StatusBadge status={descriptor} />
        <span className="font-mono text-xs text-muted-foreground">{runId}</span>
      </div>

      <ol className="flex items-center gap-2" aria-label="Run progress">
        {STEPS.map((step, index) => {
          const reached = step.reached(status);
          return (
            <li key={step.key} className="flex items-center gap-2">
              <span
                className={
                  reached
                    ? "text-sm font-medium text-foreground"
                    : "text-sm text-muted-foreground"
                }
              >
                {step.label}
              </span>
              {index < STEPS.length - 1 ? (
                <span aria-hidden="true" className="text-muted-foreground">
                  →
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>

      {run.error ? (
        <p role="alert" className="text-sm text-status-fail-fg">
          {run.error} Retrying…
        </p>
      ) : null}

      {done ? (
        <Card>
          <CardContent className="space-y-3 pt-5">
            <p className="text-sm text-muted-foreground">
              {status === "succeeded"
                ? "The run finished. Findings are ready to review."
                : "The run did not complete. Check the project configuration and try again."}
            </p>
            {status === "succeeded" ? (
              <Button asChild>
                <Link to={`/runs/${runId}/findings`}>View findings</Link>
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground">
          This view updates automatically while the run is in progress.
        </p>
      )}
    </div>
  );
}
