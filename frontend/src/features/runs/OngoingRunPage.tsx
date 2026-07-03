import { Radio } from "lucide-react";

import { Link } from "@/components/Link";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";

import { RunJourney } from "./RunJourney";
import { useActiveRun } from "./useActiveRun";

/**
 * `/runs/ongoing` — the Ongoing-run view: the single run currently in progress,
 * shown in the focused, one-phase-at-a-time {@link RunJourney}. Resolves the active
 * run via `GET /runs/active` (polling until one appears), then pins it so the view
 * follows that run to its end. When nothing is running, an honest empty state.
 *
 * Renders as a plain container inside the app shell's single scroll column — no
 * nested scroll region.
 */
export function OngoingRunPage() {
  const { runId, loading, error } = useActiveRun();

  return (
    <div className="mx-auto max-w-[1760px] px-4 py-8 lg:px-6">
      <header className="mb-5">
        <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-foreground">
          Ongoing run
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          The run currently in progress — watched live, one phase at a time.
        </p>
      </header>

      {loading ? (
        <SkeletonRows label="Looking for a run in progress…" />
      ) : error ? (
        <StatePanel
          icon={Radio}
          tone="danger"
          title="Couldn't check for a running run"
          description={error}
        />
      ) : runId ? (
        <RunJourney runId={runId} />
      ) : (
        <StatePanel
          icon={Radio}
          tone="neutral"
          title="No run in progress"
          description="Start a run and it’ll appear here, streaming step-by-step as it happens."
          actions={
            <div className="flex flex-wrap gap-2">
              <Button asChild>
                <Link to="/projects">Start a run</Link>
              </Button>
              <Button asChild variant="outline">
                <Link to="/runs">Past runs</Link>
              </Button>
            </div>
          }
        />
      )}
    </div>
  );
}
