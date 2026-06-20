import { Link } from "@/components/Link";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

/** The findings dashboard lands in a later sprint; this is the forward link. */
export function FindingsPlaceholder({ runId }: { runId: string }) {
  return (
    <>
      <PageHeader
        eyebrow={<Link to={`/runs/${runId}`}>Run</Link>}
        title="Findings"
        description={<span className="font-mono">{runId}</span>}
      />
      <main className="flex-1 px-6 py-8">
        <EmptyState
          title="Findings dashboard coming soon"
          description="The grouped, ranked findings view lands next. This run's findings are already produced and available from the API."
        />
      </main>
    </>
  );
}
