import { Radio } from "lucide-react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
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
 */
export function OngoingRunPage() {
  const { runId, loading, error } = useActiveRun();

  return (
    <>
      <PageHeader
        title="Ongoing run"
        description="The run currently in progress — watched live, one phase at a time."
      />
      <main className="flex-1 px-4 py-8 lg:px-6">
        <div className="mx-auto max-w-[1760px]">
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
      </main>
    </>
  );
}
