import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { RunTriggerForm } from "./RunTriggerForm";
import { useProject } from "./useProject";

/** Start a run for a project (#4) — the focused mode-select panel. */
export function StartRunPage({ projectId }: { projectId: string }) {
  const { project } = useProject(projectId);
  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        eyebrow={
          <Link to={`/projects/${projectId}`}>{project?.name ?? "Project"}</Link>
        }
        title="Start a run"
        description="Describe a scenario to test, or run autonomously across the model."
      />
      <main className="min-h-0 flex-1 overflow-y-auto px-6 py-8">
        {/* Wide enough for the two-column run form — config on the left, the module
            picker / run preview on the right (ADR-0061) — so the space isn't wasted. */}
        <div className="max-w-6xl">
          <RunTriggerForm projectId={projectId} />
        </div>
      </main>
    </div>
  );
}
