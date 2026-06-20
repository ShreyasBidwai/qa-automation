import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { RunStatusView } from "./RunStatusView";

export function RunStatusPage({ runId }: { runId: string }) {
  return (
    <>
      <PageHeader
        eyebrow={<Link to="/runs">Runs</Link>}
        title="Run"
        description={<span className="font-mono">{runId}</span>}
      />
      <main className="flex-1 px-6 py-8">
        <RunStatusView runId={runId} />
      </main>
    </>
  );
}
