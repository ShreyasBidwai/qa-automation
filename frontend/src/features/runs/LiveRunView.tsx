import { ArrowLeft } from "lucide-react";

import { Link } from "@/components/Link";

import { RunJourney } from "./RunJourney";

/**
 * `/runs/{id}/live` — replay (or watch live) one run's journey. A thin page shell
 * around {@link RunJourney}, the single-phase tabbed view shared with the Ongoing-run
 * page. "Replay journey" from a finished run lands here and shows THAT run only; the
 * same component streams a live run from the first step (ADR-0050 / ADR-0060).
 *
 * Full-height (ADR-0066): fills the app content region and scrolls its own body so the
 * window never scrolls — no nested page scroll, no second header.
 */
export function LiveRunView({ runId }: { runId: string }) {
  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-[1760px] px-4 py-8 lg:px-6">
        <Link
          to={`/runs/${runId}`}
          className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <ArrowLeft className="h-3.5 w-3.5" aria-hidden="true" />
          Run overview
        </Link>
        <div className="mt-4">
          <RunJourney runId={runId} />
        </div>
      </div>
    </div>
  );
}
