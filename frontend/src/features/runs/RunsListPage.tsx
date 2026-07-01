import { Activity, AlertTriangle, ListChecks } from "lucide-react";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { Link } from "@/components/Link";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { ProjectListItem, RunListItem } from "@/lib/api/types";
import { projectApi, runApi } from "@/lib/api/client";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { usePagedList, type PagedList } from "@/lib/usePagedList";

import { modeLabel } from "./modeLabel";
import { passTone } from "./runMetrics";
import { runRowStatusDescriptor } from "./runStatus";

const PAGE_SIZE = 20;
const ALL = "all";

// The file's runs table is 6 columns. RunListItem carries run / mode / pass_rate /
// status / created_at — but NOT a per-run findings-by-severity breakdown, so the
// "Findings" cell is an honest "—" (the linked run dashboard shows the breakdown).
const RUN_COLS = "grid-cols-[0.7fr_2.2fr_0.9fr_1.4fr_1fr_1fr]";

/** Project-scoped runs list (Polaris Runs.dc.html, screen 6). */
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
    <div className="mx-auto max-w-[1760px] px-6 py-8 lg:px-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
            <ListChecks
              className="h-4 w-4 text-status-neutral-solid"
              aria-hidden="true"
            />
          </span>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
              Runs
            </h1>
            <p className="mt-0.5 text-[13px] text-status-neutral-solid">
              Test runs for this project
            </p>
          </div>
        </div>
        {activeId ? (
          <Button asChild>
            <Link to={`/projects/${activeId}/run`}>Start run</Link>
          </Button>
        ) : null}
      </div>

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
          <FilterRow
            projects={projects.items}
            activeId={activeId}
            onProject={setSelectedId}
            mode={modeFilter}
            onMode={setModeFilter}
            status={statusFilter}
            onStatus={setStatusFilter}
          />
          <RunsTable activeId={activeId} runs={runs} visible={visible} />
        </>
      )}
    </div>
  );
}

// ---- filter row (project selector + mode/status pills) ----------------------

function FilterRow({
  projects,
  activeId,
  onProject,
  mode,
  onMode,
  status,
  onStatus,
}: {
  projects: ProjectListItem[];
  activeId: string | null;
  onProject: (id: string) => void;
  mode: string;
  onMode: (value: string) => void;
  status: string;
  onStatus: (value: string) => void;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-2.5">
      <div className="inline-flex h-[34px] items-center gap-2 rounded-lg border border-border bg-surface pl-3 pr-1.5">
        <span className="h-[7px] w-[7px] rounded-sm bg-accent" aria-hidden="true" />
        <select
          aria-label="Project"
          value={activeId ?? ""}
          onChange={(event) => onProject(event.target.value)}
          className="bg-transparent py-1 text-[13px] font-medium text-foreground focus-visible:outline-none"
        >
          {projects.map((project) => (
            <option key={project.id} value={project.id}>
              {project.name}
            </option>
          ))}
        </select>
      </div>

      <span className="mx-0.5 h-5 w-px bg-border" aria-hidden="true" />

      <RunFilterPill
        name="Mode"
        value={mode}
        onChange={onMode}
        options={[
          ["B", "Autonomous"],
          ["C", "Natural language"],
        ]}
      />
      <RunFilterPill
        name="Status"
        value={status}
        onChange={onStatus}
        options={[
          ["passed", "Passed"],
          ["failed", "Failed"],
          ["errored", "Errored"],
          ["running", "Running"],
          ["pending", "Queued"],
        ]}
      />
    </div>
  );
}

function RunFilterPill({
  name,
  value,
  onChange,
  options,
}: {
  name: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <select
      aria-label={name}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-[34px] rounded-lg border border-border bg-surface px-3 text-[13px] font-medium text-status-neutral-fg transition-colors focus-visible:border-accent"
    >
      <option value={ALL}>{name}</option>
      {options.map(([optionValue, optionLabel]) => (
        <option key={optionValue} value={optionValue}>
          {optionLabel}
        </option>
      ))}
    </select>
  );
}

// ---- runs table -------------------------------------------------------------

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
      <div className="rounded-xl border border-border bg-surface px-6 py-10 text-center">
        <p className="text-sm text-muted-foreground">No runs match these filters.</p>
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div
        className={`grid ${RUN_COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
      >
        <ColHead>Run</ColHead>
        <ColHead>Mode</ColHead>
        <ColHead>Pass</ColHead>
        <ColHead>Findings</ColHead>
        <ColHead>Status</ColHead>
        <ColHead>When</ColHead>
      </div>

      {visible.map((run) => (
        <RunRow key={run.id} run={run} />
      ))}

      <div className="px-5 pb-3">
        <Pagination
          offset={runs.offset}
          pageSize={runs.pageSize}
          total={runs.total}
          hasPrev={runs.hasPrev}
          hasNext={runs.hasNext}
          onPrev={runs.prev}
          onNext={runs.next}
        />
      </div>
    </div>
  );
}

// B = Autonomous → neutral; C = Natural language ("Describe") → blue (the file).
function modePill(mode: string): string {
  return mode === "C"
    ? "bg-status-info-bg text-status-info-fg"
    : "bg-status-neutral-bg text-status-neutral-fg";
}

const STATUS_TONE: Record<string, { dot: string; text: string }> = {
  pass: { dot: "bg-status-pass-solid", text: "text-status-pass-fg" },
  fail: { dot: "bg-status-fail-solid", text: "text-status-fail-fg" },
  info: { dot: "bg-status-info-solid", text: "text-status-info-fg" },
  flaky: { dot: "bg-status-flaky-solid", text: "text-status-flaky-fg" },
  neutral: { dot: "bg-status-neutral-solid", text: "text-status-neutral-fg" },
};

function RunRow({ run }: { run: RunListItem }) {
  const pct = run.pass_rate === null ? null : Math.round(run.pass_rate * 100);
  const descriptor = runRowStatusDescriptor(run.status);
  const tone = STATUS_TONE[descriptor.level];
  return (
    <Link
      to={`/runs/${run.id}/findings`}
      className={`grid ${RUN_COLS} items-center border-b border-border-subtle px-5 py-3.5 transition-colors last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent`}
    >
      <span
        className="truncate font-mono text-[13px] font-medium text-foreground"
        title={run.id}
      >
        {run.id.slice(0, 8)}
      </span>
      <span className="min-w-0">
        <span
          className={cn(
            "rounded-[5px] px-[7px] py-0.5 font-mono text-[10.5px] font-medium",
            modePill(run.mode),
          )}
        >
          {modeLabel(run.mode)}
        </span>
      </span>
      <span
        className={cn(
          "text-[13px] font-semibold tabular-nums",
          pct === null ? "text-muted-foreground" : passTone(pct).text,
        )}
      >
        {pct === null ? "—" : `${pct}%`}
      </span>
      {/* Per-run findings-by-severity isn't on RunListItem — honest placeholder. */}
      <span className="text-sm text-marker">—</span>
      <span
        className={cn(
          "inline-flex items-center gap-1.5 text-xs font-medium",
          tone.text,
        )}
      >
        <span
          className={cn("h-[6px] w-[6px] rounded-full", tone.dot)}
          aria-hidden="true"
        />
        {descriptor.label}
      </span>
      <span className="text-xs text-status-neutral-solid">
        {relativeTime(run.created_at)}
      </span>
    </Link>
  );
}

function ColHead({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
      {children}
    </span>
  );
}
