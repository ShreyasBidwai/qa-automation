import { useCallback, useState } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { projectApi, runApi } from "@/lib/api/client";
import type { RunListItem } from "@/lib/api/types";
import { usePagedList, type PagedList } from "@/lib/usePagedList";

import { modeLabel } from "./modeLabel";
import { runRowStatusDescriptor } from "./runStatus";

const PAGE_SIZE = 20;

export function RunsListPage() {
  // Runs are project-scoped (the only runs endpoint), so pick a project first.
  const projectsFetch = useCallback(
    (offset: number) => projectApi.list({ limit: 100, offset }),
    [],
  );
  const projects = usePagedList(projectsFetch, {
    pageSize: 100,
    resetKey: "projects",
  });

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const activeId = selectedId ?? projects.items[0]?.id ?? null;

  const runsFetch = useCallback(
    (offset: number) => runApi.list(activeId ?? "", { limit: PAGE_SIZE, offset }),
    [activeId],
  );
  const runs = usePagedList(runsFetch, {
    pageSize: PAGE_SIZE,
    enabled: activeId !== null,
    resetKey: activeId ?? "",
  });

  return (
    <>
      <PageHeader title="Runs" />
      <main className="flex-1 space-y-4 px-6 py-8">
        {projects.loading ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : projects.error ? (
          <p role="alert" className="text-sm text-status-fail-fg">
            Could not load projects. {projects.error}
          </p>
        ) : projects.items.length === 0 ? (
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
          <>
            <div className="flex items-center gap-2">
              <label htmlFor="run-project" className="text-xs text-muted-foreground">
                Project
              </label>
              <Select
                id="run-project"
                value={activeId ?? ""}
                onChange={(event) => setSelectedId(event.target.value)}
                className="h-8 w-auto"
              >
                {projects.items.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </div>
            <RunsTable activeId={activeId} runs={runs} />
          </>
        )}
      </main>
    </>
  );
}

function RunsTable({
  activeId,
  runs,
}: {
  activeId: string | null;
  runs: PagedList<RunListItem>;
}) {
  if (runs.loading) {
    return <p className="text-sm text-muted-foreground">Loading runs…</p>;
  }
  if (runs.error) {
    return (
      <p role="alert" className="text-sm text-status-fail-fg">
        Could not load runs. {runs.error}
      </p>
    );
  }
  if (runs.items.length === 0) {
    return (
      <EmptyState
        title="No runs for this project"
        description="Run tests on this project to see runs here."
        action={
          activeId ? (
            <Button asChild>
              <Link to={`/projects/${activeId}`}>Run tests</Link>
            </Button>
          ) : undefined
        }
      />
    );
  }
  return (
    <>
      <Table>
        <THead>
          <TR className="hover:bg-transparent">
            <TH>Started</TH>
            <TH>Mode</TH>
            <TH>Status</TH>
            <TH>Pass rate</TH>
          </TR>
        </THead>
        <TBody>
          {runs.items.map((run) => (
            <TR key={run.id}>
              <TD className="text-muted-foreground">
                {new Date(run.created_at).toLocaleString()}
              </TD>
              <TD>{modeLabel(run.mode)}</TD>
              <TD>
                <StatusBadge status={runRowStatusDescriptor(run.status)} />
              </TD>
              <TD className="font-mono text-[13px] text-muted-foreground">
                {run.pass_rate === null ? "—" : `${Math.round(run.pass_rate * 100)}%`}
              </TD>
            </TR>
          ))}
        </TBody>
      </Table>
      <Pagination
        offset={runs.offset}
        pageSize={runs.pageSize}
        total={runs.total}
        hasPrev={runs.hasPrev}
        hasNext={runs.hasNext}
        onPrev={runs.prev}
        onNext={runs.next}
      />
    </>
  );
}
