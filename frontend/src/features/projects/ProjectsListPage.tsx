import { AlertTriangle, FolderGit2 } from "lucide-react";
import { useCallback, type ReactNode } from "react";

import { Link } from "@/components/Link";
import { Pagination } from "@/components/Pagination";
import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { ProjectListItem } from "@/lib/api/types";
import { projectApi } from "@/lib/api/client";
import { usePagedList } from "@/lib/usePagedList";

const PAGE_SIZE = 20;

// The file's table is 5 columns. The list endpoint (ProjectListItem) only carries
// the project identity today — stack / last-run / open-findings / status are a
// separate in-flight enrichment, so those columns render an honest "—" and slot
// in cleanly once the enriched payload lands (never fabricated, never N+1).
const COLS = "grid-cols-[2.4fr_1fr_1.3fr_1.5fr_1fr]";

/** Projects list (#2): every codebase under test, newest first (GET /projects). */
export function ProjectsListPage() {
  const fetchPage = useCallback(
    (offset: number) => projectApi.list({ limit: PAGE_SIZE, offset }),
    [],
  );
  const list = usePagedList(fetchPage, { pageSize: PAGE_SIZE, resetKey: "projects" });

  return (
    <div className="mx-auto max-w-[1080px] px-7 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
            <FolderGit2
              className="h-4 w-4 text-status-neutral-solid"
              aria-hidden="true"
            />
          </span>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
              Projects
            </h1>
            {!list.loading && !list.error ? (
              <p className="mt-0.5 text-[13px] text-status-neutral-solid">
                {list.total} {list.total === 1 ? "codebase" : "codebases"} under test
              </p>
            ) : null}
          </div>
        </div>
        <Button asChild>
          <Link to="/projects/new">New project</Link>
        </Button>
      </div>

      {list.loading ? (
        <SkeletonRows label="Loading projects…" />
      ) : list.error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load projects"
          description="Polaris couldn't reach the project service. This is usually temporary."
          code={list.error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : list.items.length === 0 ? (
        <StatePanel
          icon={FolderGit2}
          title="No projects yet"
          description="Connect a codebase to start. Polaris reads the repo, maps the app, and finds problems before your users do."
          actions={
            <Button asChild>
              <Link to="/projects/new">Connect a codebase</Link>
            </Button>
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-surface">
          <div
            className={`grid ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
          >
            <ColHead>Project</ColHead>
            <ColHead>Stack</ColHead>
            <ColHead>Last run</ColHead>
            <ColHead>Open findings</ColHead>
            <ColHead>Status</ColHead>
          </div>

          {list.items.map((project) => (
            <ProjectRow key={project.id} project={project} />
          ))}

          <div className="px-5 pb-3">
            <Pagination
              offset={list.offset}
              pageSize={list.pageSize}
              total={list.total}
              hasPrev={list.hasPrev}
              hasNext={list.hasNext}
              onPrev={list.prev}
              onNext={list.next}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function ColHead({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
      {children}
    </span>
  );
}

function ProjectRow({ project }: { project: ProjectListItem }) {
  return (
    <Link
      to={`/projects/${project.id}`}
      aria-label={project.name}
      className={`grid ${COLS} items-center border-b border-border-subtle px-5 py-4 transition-colors last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent`}
    >
      <div className="min-w-0 pr-3">
        <div className="text-sm font-medium text-foreground">{project.name}</div>
        <div className="truncate font-mono text-[11px] text-status-neutral-solid">
          {project.repo_url}
        </div>
      </div>
      {/* Pending the list-enrichment endpoint (stack / last-run / findings / status). */}
      <PendingCell />
      <PendingCell />
      <PendingCell />
      <PendingCell />
    </Link>
  );
}

function PendingCell() {
  return <span className="text-sm text-marker">—</span>;
}
