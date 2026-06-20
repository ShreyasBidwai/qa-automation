import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Project } from "@/lib/api/types";

import { runStatusDescriptor } from "../runs/runStatus";
import { RunTriggerForm } from "./RunTriggerForm";
import { useIngest } from "./useIngest";
import { useProject } from "./useProject";

export function ProjectPage({ projectId }: { projectId: string }) {
  const { project, error, loading } = useProject(projectId);

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/projects">Projects</Link>}
        title={project?.name ?? "Project"}
        description={
          project ? <span className="font-mono">{project.slug}</span> : undefined
        }
      />
      <main className="flex-1 space-y-8 px-6 py-8">
        {loading ? (
          <p className="text-sm text-muted-foreground">Loading project…</p>
        ) : error || !project ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            {error ?? "Project not found."}
          </p>
        ) : (
          <>
            <ProjectDetails project={project} />
            <ModelSection projectId={projectId} />
            <section className="max-w-2xl space-y-3">
              <h2 className="text-base font-medium text-foreground">Run tests</h2>
              <p className="text-sm text-muted-foreground">
                Run autonomously across the model, or describe a scenario to test.
              </p>
              <RunTriggerForm projectId={projectId} />
            </section>
          </>
        )}
      </main>
    </>
  );
}

function ProjectDetails({ project }: { project: Project }) {
  return (
    <Card className="max-w-2xl">
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <DetailRow label="Repository" value={project.repo_url} mono />
        <DetailRow label="App URL" value={project.app_url ?? "—"} mono />
        <DetailRow label="Auth config" value={project.auth_config_ref ?? "—"} mono />
      </CardContent>
    </Card>
  );
}

function DetailRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className={mono ? "break-all font-mono text-[13px]" : undefined}>
        {value}
      </span>
    </div>
  );
}

function ModelSection({ projectId }: { projectId: string }) {
  const ingest = useIngest(projectId);
  return (
    <section className="max-w-2xl space-y-3">
      <h2 className="text-base font-medium text-foreground">Model</h2>
      <p className="text-sm text-muted-foreground">
        Build the system model from the repository before running tests.
      </p>
      <div className="flex items-center gap-3">
        <Button variant="outline" onClick={ingest.start} disabled={ingest.busy}>
          {ingest.busy ? "Building model…" : "Build model"}
        </Button>
        {ingest.status ? (
          <StatusBadge status={runStatusDescriptor(ingest.status)} />
        ) : null}
      </div>
      {ingest.error ? (
        <p role="alert" className="text-sm text-status-fail-fg">
          {ingest.error}
        </p>
      ) : null}
    </section>
  );
}
