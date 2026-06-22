import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";

import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { Finding, Project, RunListItem } from "@/lib/api/types";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

import { severityCounts } from "../runs/findingStats";
import { modeLabel } from "../runs/modeLabel";
import { runRowStatusDescriptor, runStatusDescriptor } from "../runs/runStatus";
import { useIngest } from "./useIngest";
import { useProjectOverview } from "./useProjectOverview";

/** The project landing page (#3a): config, a health summary, and recent runs. */
export function ProjectPage({ projectId }: { projectId: string }) {
  const { project, runs, openFindings, openTotal, loading, error } =
    useProjectOverview(projectId);

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/projects">Projects</Link>}
        title={project?.name ?? "Project"}
        description={
          project ? (
            <span className="font-mono text-xs">{project.slug}</span>
          ) : undefined
        }
        action={
          project ? (
            <div className="flex items-center gap-2">
              <Button variant="outline" asChild>
                <Link to={`/projects/${projectId}/edit`}>Edit</Link>
              </Button>
              <Button asChild>
                <Link to={`/projects/${projectId}/run`}>Start run</Link>
              </Button>
            </div>
          ) : undefined
        }
      />
      <main className="flex-1 space-y-6 px-6 py-8">
        {loading ? (
          <OverviewSkeleton />
        ) : error || !project ? (
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load this project"
            description="The project may have been removed, or the service is briefly unavailable."
            code={error ?? undefined}
            actions={
              <Button asChild>
                <Link to="/projects">Back to projects</Link>
              </Button>
            }
          />
        ) : (
          <>
            <HealthSummary
              runs={runs}
              openFindings={openFindings}
              openTotal={openTotal}
            />
            <div className="grid gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <RecentRuns runs={runs} />
              </div>
              <div className="space-y-6">
                <ConfigCard project={project} />
                <ModelCard projectId={projectId} />
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}

// ---- health summary ---------------------------------------------------------

function HealthSummary({
  runs,
  openFindings,
  openTotal,
}: {
  runs: RunListItem[];
  openFindings: Finding[];
  openTotal: number;
}) {
  const latest = runs[0] ?? null;
  const prior = runs[1] ?? null;
  const severity = severityCounts(openFindings);

  return (
    <section className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
      <StatCard label="Pass rate">
        {latest && latest.pass_rate !== null ? (
          <div className="flex items-baseline gap-2">
            <span className="text-[28px] font-semibold leading-none tabular-nums text-foreground">
              {Math.round(latest.pass_rate * 100)}%
            </span>
            <PassRateTrend latest={latest.pass_rate} prior={prior?.pass_rate ?? null} />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No runs yet</p>
        )}
      </StatCard>

      <StatCard label="Open findings">
        <div className="flex items-baseline gap-2">
          <span className="text-[28px] font-semibold leading-none tabular-nums text-foreground">
            {openTotal}
          </span>
          <span className="text-xs text-muted-foreground">open</span>
        </div>
        {openTotal > 0 ? (
          <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
            <SeverityCount
              n={severity.critical}
              label="critical"
              dot="bg-status-fail-solid"
              text="text-status-fail-fg"
            />
            <SeverityCount
              n={severity.major}
              label="major"
              dot="bg-status-flaky-solid"
              text="text-status-flaky-fg"
            />
            <SeverityCount
              n={severity.minor}
              label="minor"
              dot="bg-status-neutral-solid"
              text="text-muted-foreground"
            />
          </div>
        ) : null}
      </StatCard>

      <StatCard label="Last run">
        {latest ? (
          <div className="space-y-2">
            <span className="text-sm font-medium text-foreground">
              {relativeTime(latest.created_at)}
            </span>
            <div>
              <StatusBadge status={runRowStatusDescriptor(latest.status)} />
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No runs yet</p>
        )}
      </StatCard>
    </section>
  );
}

function StatCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2.5 text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function PassRateTrend({ latest, prior }: { latest: number; prior: number | null }) {
  if (prior === null) return null;
  const delta = Math.round((latest - prior) * 100);
  if (delta === 0)
    return <span className="text-xs text-muted-foreground">no change</span>;
  const up = delta > 0;
  return (
    <span className={cn("text-xs", up ? "text-status-pass-fg" : "text-status-fail-fg")}>
      {up ? "▲" : "▼"} {Math.abs(delta)}%
    </span>
  );
}

function SeverityCount({
  n,
  label,
  dot,
  text,
}: {
  n: number;
  label: string;
  dot: string;
  text: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", text)}>
      <span className={cn("h-[7px] w-[7px] rounded-full", dot)} aria-hidden="true" />
      {n} {label}
    </span>
  );
}

// ---- recent runs ------------------------------------------------------------

function RecentRuns({ runs }: { runs: RunListItem[] }) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
        <CardTitle>Recent runs</CardTitle>
        <Link to="/runs" className="text-xs font-medium text-accent hover:underline">
          All runs
        </Link>
      </CardHeader>
      <CardContent>
        {runs.length === 0 ? (
          <p className="py-4 text-sm text-muted-foreground">
            No runs yet — build the model, then start a run to see results here.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {runs.map((run) => (
              <li key={run.id}>
                <Link
                  to={`/runs/${run.id}/findings`}
                  className="flex items-center justify-between gap-4 py-3 hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
                >
                  <span className="flex items-center gap-3">
                    <StatusBadge status={runRowStatusDescriptor(run.status)} />
                    <span className="text-sm text-muted-foreground">
                      {modeLabel(run.mode)}
                    </span>
                  </span>
                  <span className="flex items-center gap-4">
                    <span className="font-mono text-[13px] tabular-nums text-muted-foreground">
                      {run.pass_rate === null
                        ? "—"
                        : `${Math.round(run.pass_rate * 100)}%`}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {relativeTime(run.created_at)}
                    </span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

// ---- configuration + model --------------------------------------------------

function ConfigCard({ project }: { project: Project }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Configuration</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <DetailRow label="Stack">
          {project.stack ? (
            <Badge level="neutral">{project.stack}</Badge>
          ) : (
            <span className="text-muted-foreground">Auto-detected</span>
          )}
        </DetailRow>
        <DetailRow label="App URL">
          {project.app_url ? (
            <a
              href={project.app_url}
              target="_blank"
              rel="noreferrer"
              className="break-all font-mono text-[13px] text-accent hover:underline"
            >
              {project.app_url}
            </a>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
        </DetailRow>
        <DetailRow label="Repository">
          <span className="break-all font-mono text-[13px] text-foreground">
            {project.repo_url}
          </span>
        </DetailRow>
        <DetailRow label="Auth config">
          <span className="break-all font-mono text-[13px] text-foreground">
            {project.auth_config_ref ?? "—"}
          </span>
        </DetailRow>
      </CardContent>
    </Card>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_1fr] items-start gap-3 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}

function ModelCard({ projectId }: { projectId: string }) {
  const ingest = useIngest(projectId);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Model</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
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
      </CardContent>
    </Card>
  );
}

// ---- loading ----------------------------------------------------------------

function OverviewSkeleton() {
  return (
    <>
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </>
  );
}
