import { ArrowRight, Check } from "lucide-react";

import { Link } from "@/components/Link";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { isTerminal, runStatusDescriptor } from "./runStatus";
import { useRunStatus } from "./useRunStatus";

// The honest pipeline Polaris works through (design brief #5). The backend status
// is coarse (pending/running/succeeded/failed), so we show the pipeline as the
// plan and let the run status drive done/failed — we never fake which step is live.
const PHASES = [
  { key: "understand", label: "Understanding the app" },
  { key: "generate", label: "Generating tests" },
  { key: "run", label: "Running" },
  { key: "assemble", label: "Assembling findings" },
];

/** Live run progress: a phase pipeline, polling until terminal. */
export function RunStatusView({ runId }: { runId: string }) {
  const run = useRunStatus(runId);

  if (run.loading && run.status === null) {
    return <p className="text-sm text-muted-foreground">Loading run…</p>;
  }

  const status = run.status ?? "queued";
  const descriptor = runStatusDescriptor(status);
  const done = isTerminal(status);
  const succeeded = status === "succeeded";
  const running = status === "running";

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center gap-3">
        <StatusBadge status={descriptor} />
        <span className="font-mono text-xs text-muted-foreground">{runId}</span>
      </div>

      {/* The live, step-by-step journey (live for an in-progress run, replay for a
       *  finished one) — the run status here is intentionally coarse. */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <Link
          to={`/runs/${runId}/live`}
          className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
        >
          {done ? "Replay the run journey" : "Watch the live run"}
          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
        </Link>
        {run.projectId ? (
          <Link
            to={`/projects/${run.projectId}/tests?run=${runId}`}
            className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
          >
            View this run's tests
            <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        ) : null}
      </div>

      <ol className="space-y-2.5" aria-label="Run progress">
        {PHASES.map((phase) => (
          <li key={phase.key} className="flex items-center gap-3">
            <PhaseDot
              succeeded={succeeded}
              running={running}
              failed={status === "failed"}
            />
            <span
              className={cn(
                "text-sm",
                succeeded ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {phase.label}
            </span>
          </li>
        ))}
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
              {succeeded
                ? "The run finished. Findings are ready to review."
                : "The run did not complete. Check the project configuration and try again."}
            </p>
            {succeeded ? (
              <Button asChild>
                <Link to={`/runs/${runId}/findings`}>View findings</Link>
              </Button>
            ) : null}
          </CardContent>
        </Card>
      ) : (
        <p className="text-sm text-muted-foreground">
          Polaris is working through the pipeline. This view updates automatically.
        </p>
      )}
    </div>
  );
}

function PhaseDot({
  succeeded,
  running,
  failed,
}: {
  succeeded: boolean;
  running: boolean;
  failed: boolean;
}) {
  if (succeeded) {
    return (
      <span
        className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-status-pass-solid text-white"
        aria-hidden="true"
      >
        <Check className="h-2.5 w-2.5" />
      </span>
    );
  }
  return (
    <span
      aria-hidden="true"
      className={cn(
        "h-4 w-4 shrink-0 rounded-full border-2",
        failed
          ? "border-status-fail-solid"
          : running
            ? "animate-shimmer border-accent"
            : "border-status-neutral-solid",
      )}
    />
  );
}
