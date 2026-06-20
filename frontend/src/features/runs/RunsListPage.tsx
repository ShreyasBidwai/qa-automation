import { Link } from "@/components/Link";
import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { useRuns } from "@/lib/useRegistry";

import { runStatusDescriptor } from "./runStatus";

const MODE_LABEL: Record<string, string> = {
  mode_b: "Autonomous",
  mode_c: "From a prompt",
};

export function RunsListPage() {
  const runs = useRuns();

  return (
    <>
      <PageHeader title="Runs" />
      <main className="flex-1 px-6 py-8">
        {runs.length === 0 ? (
          <EmptyState
            title="No runs yet"
            description="Register a project and run tests to see runs here."
            action={
              <Button asChild>
                <Link to="/projects">Go to projects</Link>
              </Button>
            }
          />
        ) : (
          <Table>
            <THead>
              <TR className="hover:bg-transparent">
                <TH>Project</TH>
                <TH>Mode</TH>
                <TH>Status</TH>
                <TH>Started</TH>
              </TR>
            </THead>
            <TBody>
              {runs.map((run) => (
                <TR key={run.runId}>
                  <TD className="font-medium">
                    <Link to={`/runs/${run.runId}`} className="hover:text-accent">
                      {run.projectName}
                    </Link>
                  </TD>
                  <TD className="text-muted-foreground">
                    {MODE_LABEL[run.mode] ?? run.mode}
                  </TD>
                  <TD>
                    <StatusBadge status={runStatusDescriptor(run.status)} />
                  </TD>
                  <TD className="text-muted-foreground">
                    {new Date(run.startedAt).toLocaleString()}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </main>
    </>
  );
}
