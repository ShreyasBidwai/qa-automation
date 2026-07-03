import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";

import { RunTriggerForm } from "./RunTriggerForm";
import { useProject } from "./useProject";

/** Start a run for a project (#4) — the focused mode-select panel. */
export function StartRunPage({ projectId }: { projectId: string }) {
  const { project } = useProject(projectId);
  return (
    <>
      <PageHeader
        eyebrow={
          <Link to={`/projects/${projectId}`}>
            {project?.name ?? "Project"}
          </Link>
        }
        title="Start a run"
        description="Describe a scenario to test, or run autonomously across the model."
      />
      <main className="flex-1 px-6 py-8">
        {/* Wider than a single column so the module picker (ADR-0061) can lay its
            searchable list across the width instead of leaving the right side empty. */}
        <div className="max-w-4xl">
          <RunTriggerForm projectId={projectId} />
        </div>
      </main>
    </>
  );
}
