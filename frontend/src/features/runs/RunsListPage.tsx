import { Activity, AlertTriangle } from "lucide-react";
import { useCallback, useMemo, useState } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import { TBody, TD, TH, THead, TR, Table } from "@/components/ui/table";
import { projectApi, runApi } from "@/lib/api/client";
import type { RunListItem } from "@/lib/api/types";
import { relativeTime } from "@/lib/time";
import { usePagedList, type PagedList } from "@/lib/usePagedList";

import { modeLabel } from "./modeLabel";
import { runRowStatusDescriptor } from "./runStatus";

const PAGE_SIZE = 20;
const ALL = "all";

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

  const [modeFilter, setModeFilter] = useState(ALL);
  const [statusFilter, setStatusFilter] = useState(ALL);
  const visible = useMemo(
    () =>
      runs.items.filter(
        (run) =>
          (modeFilter === ALL || run.mode === modeFilter) &&
          (statusFilter === ALL || run.status === statusFilter),
      ),
    [runs.items, modeFilter, statusFilter],
  );

  return (
    <>
      <PageHeader title="Runs" />
      <main className="flex-1 space-y-4 px-6 py-8">
        {projects.loading ? (
          <SkeletonRows label="Loading…" />
        ) : projects.error ? (
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load projects"
            description="Polaris couldn't reach the project service. This is usually temporary."
            code={projects.error}
            actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
          />
        ) : projects.items.length === 0 ? (
          <StatePanel
            icon={Activity}
            title="No runs yet"
            description="Register a project and run tests to see runs here."
            actions={
              <Button asChild>
                <Link to="/projects">Go to projects</Link>
              </Button>
            }
          />
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <FilterSelect
                label="Project"
                value={activeId ?? ""}
                onChange={setSelectedId}
                options={projects.items.map((p) => [p.id, p.name])}
              />
              <FilterSelect
                label="Mode"
                value={modeFilter}
                onChange={setModeFilter}
                includeAll
                options={[
                  ["B", "Autonomous"],
                  ["C", "Natural language"],
                ]}
              />
              <FilterSelect
                label="Status"
                value={statusFilter}
                onChange={setStatusFilter}
                includeAll
                options={[
                  ["passed", "Passed"],
                  ["failed", "Failed"],
                  ["errored", "Errored"],
                  ["running", "Running"],
                  ["pending", "Queued"],
                ]}
              />
            </div>
            <RunsTable activeId={activeId} runs={runs} visible={visible} />
          </>
        )}
      </main>
    </>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
  includeAll,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
  includeAll?: boolean;
}) {
  const id = `runs-filter-${label.toLowerCase()}`;
  return (
    <div className="flex items-center gap-1.5">
      <label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </label>
      <Select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-8 w-auto"
      >
        {includeAll ? <option value={ALL}>All</option> : null}
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </Select>
    </div>
  );
}

function RunsTable({
  activeId,
  runs,
  visible,
}: {
  activeId: string | null;
  runs: PagedList<RunListItem>;
  visible: RunListItem[];
}) {
  if (runs.loading) {
    return <SkeletonRows label="Loading runs…" />;
  }
  if (runs.error) {
    return (
      <StatePanel
        icon={AlertTriangle}
        tone="danger"
        title="Couldn't load runs"
        description="Polaris couldn't reach the run service. This is usually temporary."
        code={runs.error}
        actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
      />
    );
  }
  if (runs.items.length === 0) {
    return (
      <StatePanel
        icon={Activity}
        title="No runs for this project"
        description="Run tests on this project to see runs here."
        actions={
          activeId ? (
            <Button asChild>
              <Link to={`/projects/${activeId}/run`}>Start a run</Link>
            </Button>
          ) : undefined
        }
      />
    );
  }
  if (visible.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border bg-surface px-6 py-10 text-center text-sm text-muted-foreground">
        No runs match these filters.
      </p>
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
          {visible.map((run) => (
            <TR key={run.id}>
              <TD className="text-muted-foreground">
                <Link to={`/runs/${run.id}/findings`} className="hover:text-accent">
                  {relativeTime(run.created_at)}
                </Link>
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
