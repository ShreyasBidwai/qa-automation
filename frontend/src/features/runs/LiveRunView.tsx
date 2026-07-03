import { ArrowLeft } from "lucide-react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { RunJourney } from "./RunJourney";

/**
 * `/runs/{id}/live` — replay (or watch live) one run's journey. A thin page shell
 * around {@link RunJourney}, the single-phase tabbed view shared with the Ongoing-run
 * page. "Replay journey" from a finished run lands here and shows THAT run only; the
 * same component streams a live run from the first step (ADR-0050 / ADR-0060).
 */
export function LiveRunView({ runId }: { runId: string }) {
  return (
    <>
      <PageHeader
        eyebrow={<Link to={`/runs/${runId}`}>Run</Link>}
        title="Run journey"
        description={<span className="font-mono">{runId}</span>}
      />
      <main className="flex-1 px-4 py-8 lg:px-6">
        <div className="mx-auto max-w-[1760px]">
          <div className="mb-6">
            <Link
              to={`/runs/${runId}`}
              className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
            >
              <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
              Run overview
            </Link>
          </div>
          <RunJourney runId={runId} />
        </div>
      </main>
    </>
  );
}
