import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { RunStatusView } from "./RunStatusView";

export function RunStatusPage({ runId }: { runId: string }) {
  // Full-height (ADR-0066): the header stays put; only the body scrolls — the window
  // never does.
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        eyebrow={<Link to="/runs">Runs</Link>}
        title="Run"
        description={<span className="font-mono">{runId}</span>}
      />
      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-8">
        <RunStatusView runId={runId} />
      </main>
    </div>
  );
}
