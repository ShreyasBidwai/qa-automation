import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ClipboardList,
  GitBranch,
  RotateCcw,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { Link } from "@/components/Link";
import { PageShell } from "@/components/PageShell";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { runApi } from "@/lib/api/client";
import type { Finding, RunListItem } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

import { severityCounts } from "../runs/findingStats";
import { modeLabel } from "../runs/modeLabel";
import { runPreferencesLabel } from "../runs/runPreferences";
import { passTone } from "../runs/runMetrics";
import { runRowStatusDescriptor, runStatusDescriptor } from "../runs/runStatus";
import { useIngest } from "./useIngest";
import { useProjectModel } from "./useProjectModel";
import { useProjectOverview } from "./useProjectOverview";

/** The project landing page (#3a): config, a health summary, and recent runs. */
export function ProjectPage({ projectId }: { projectId: string }) {
  const { project, runs, openFindings, openTotal, loading, error } =
    useProjectOverview(projectId);

  return (
    <PageShell
      header={
        <>
          <Link
            to="/projects"
            className="inline-flex items-center gap-1.5 text-[13px] text-muted-foreground transition-colors hover:text-foreground"
          >
            ← Projects
          </Link>
          {!loading && !error && project ? (
            <header className="mt-3 flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-3">
                  <h1 className="text-[22px] font-semibold tracking-[-0.015em] text-foreground">
                    {project.name}
                  </h1>
                  {project.stack ? (
                    <span className="rounded-[5px] border border-border bg-status-neutral-bg px-2 py-0.5 font-mono text-[11px] font-medium text-status-neutral-fg">
                      {project.stack}
                    </span>
                  ) : null}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3.5 gap-y-1 font-mono text-xs text-muted-foreground">
                  <span className="break-all">{project.repo_url}</span>
                  {project.app_url ? (
                    <>
                      <span className="text-marker" aria-hidden="true">
                        ·
                      </span>
                      <a
                        href={project.app_url}
                        target="_blank"
                        rel="noreferrer"
                        className="break-all text-accent hover:underline"
                      >
                        {project.app_url}
                      </a>
                    </>
                  ) : null}
                </div>
              </div>
              <div className="flex flex-none gap-2">
                <Button variant="outline" asChild>
                  <Link to={`/projects/${projectId}/edit`}>Edit</Link>
                </Button>
                <Button variant="outline" asChild>
                  <Link to={`/projects/${projectId}/tests`}>View all tests</Link>
                </Button>
                <Button asChild>
                  <Link to={`/projects/${projectId}/run`}>Start run</Link>
                </Button>
              </div>
            </header>
          ) : null}
        </>
      }
    >
      {loading ? (
        <OverviewSkeleton />
      ) : error || !project ? (
        <div className="mt-6">
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
        </div>
      ) : (
        <>
          <HealthSummary
            runs={runs}
            openFindings={openFindings}
            openTotal={openTotal}
          />

          <RecentRuns runs={runs} />

          <div className="grid gap-3.5 lg:grid-cols-2">
            <ModelCard projectId={projectId} />
            <ConnectorsCard />
          </div>
        </>
      )}
    </PageShell>
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
  const pct =
    latest && latest.pass_rate !== null ? Math.round(latest.pass_rate * 100) : null;
  const tone = pct === null ? null : passTone(pct);

  return (
    <section className="mb-7 grid grid-cols-1 gap-3.5 sm:grid-cols-3">
      <HealthCard label="Pass rate">
        {pct !== null ? (
          <>
            <div className="flex items-baseline gap-2.5">
              <span className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
                {pct}%
              </span>
              <PassTrend latest={latest!.pass_rate!} prior={prior?.pass_rate ?? null} />
            </div>
            <div className="mt-3 h-[5px] overflow-hidden rounded-full bg-border-subtle">
              <div
                className={cn("h-full rounded-full", tone!.fill)}
                style={{ width: `${pct}%` }}
              />
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No runs yet</p>
        )}
      </HealthCard>

      <HealthCard label="Open findings">
        <div className="flex items-baseline gap-2">
          <span className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
            {openTotal}
          </span>
          <span className="text-xs text-muted-foreground">open</span>
        </div>
        {openTotal > 0 ? (
          <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
            <SevCount
              n={severity.critical}
              label="critical"
              dot="bg-severity-critical-dot"
              text="text-severity-critical-fg"
            />
            <SevCount
              n={severity.major}
              label="major"
              dot="bg-severity-major-dot"
              text="text-severity-major-fg"
            />
            <SevCount
              n={severity.minor}
              label="minor"
              dot="bg-severity-minor-dot"
              text="text-severity-minor-fg"
            />
          </div>
        ) : null}
      </HealthCard>

      <HealthCard label="Last run">
        {latest ? (
          <>
            <div className="text-[18px] font-semibold tracking-[-0.01em] text-foreground">
              {relativeTime(latest.created_at)}
            </div>
            <div className="mt-1.5 text-xs text-muted-foreground">
              {modeLabel(latest.mode)}
            </div>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No runs yet</p>
        )}
      </HealthCard>
    </section>
  );
}

function HealthCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-5 py-[18px] shadow-card">
      <div className="mb-2.5 text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function PassTrend({ latest, prior }: { latest: number; prior: number | null }) {
  if (prior === null) return null;
  const delta = Math.round((latest - prior) * 100);
  if (delta === 0)
    return <span className="text-xs text-muted-foreground">no change</span>;
  const up = delta > 0;
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs font-semibold",
        up ? "text-status-pass-fg" : "text-status-flaky-fg",
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {Math.abs(delta)}%
    </span>
  );
}

function SevCount({
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

const RUN_COLS = "grid-cols-[1.6fr_0.8fr_0.6fr_1.2fr_0.9fr_auto]";

function RecentRuns({ runs }: { runs: RunListItem[] }) {
  return (
    <section className="mb-7">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Recent runs</h2>
        <Link
          to="/runs"
          className="text-[13px] font-medium text-accent hover:underline"
        >
          View all
        </Link>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
        {runs.length === 0 ? (
          <p className="px-5 py-8 text-sm text-muted-foreground">
            No runs yet — build the model, then start a run to see results here.
          </p>
        ) : (
          <>
            <div
              className={`grid ${RUN_COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
            >
              <ColHead>Run</ColHead>
              <ColHead>Mode</ColHead>
              <ColHead>Pass</ColHead>
              <ColHead>Status</ColHead>
              <ColHead>When</ColHead>
              <span aria-hidden="true" />
            </div>
            {runs.map((run) => (
              <RunRow key={run.id} run={run} />
            ))}
          </>
        )}
      </div>
    </section>
  );
}

function RunRow({ run }: { run: RunListItem }) {
  const pct = run.pass_rate === null ? null : Math.round(run.pass_rate * 100);
  const preferences = runPreferencesLabel(run.preferences);
  return (
    // A div (not a whole-row Link) so the Re-run button can live inside it without
    // nesting interactives; the run id is the link to its findings.
    <div
      className={`grid ${RUN_COLS} items-center gap-2 border-b border-border-subtle px-5 py-3 last:border-b-0`}
    >
      <span className="min-w-0">
        <Link
          to={`/runs/${run.id}/findings`}
          title={run.id}
          className="block truncate font-mono text-[13px] font-medium text-foreground hover:text-accent hover:underline"
        >
          {run.id.slice(0, 8)}
        </Link>
        {preferences ? (
          <span className="mt-0.5 block truncate text-[11px] text-status-neutral-solid">
            {preferences}
          </span>
        ) : null}
      </span>
      <span className="min-w-0">
        <span className="rounded-[5px] bg-status-neutral-bg px-[7px] py-0.5 font-mono text-[10.5px] text-status-neutral-fg">
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
      <span>
        <StatusBadge status={runRowStatusDescriptor(run.status)} />
      </span>
      <span className="text-xs text-status-neutral-solid">
        {relativeTime(run.created_at)}
      </span>
      <span className="justify-self-end">
        <RerunButton runId={run.id} />
      </span>
    </div>
  );
}

/** Start a fresh run with the SAME preferences as this one (ADR-0062) — no
 *  reconfiguring — then jump to the new live run. */
function RerunButton({ runId }: { runId: string }) {
  const [busy, setBusy] = useState(false);
  async function rerun() {
    setBusy(true);
    const result = await runApi.rerun(runId);
    if (result.ok && result.data) {
      navigate(`/runs/${result.data.run_id}/live`);
      return;
    }
    setBusy(false);
  }
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      disabled={busy}
      onClick={rerun}
      title="Re-run with the same preferences"
    >
      <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
      {busy ? "Starting…" : "Re-run"}
    </Button>
  );
}

function ColHead({ children }: { children: ReactNode }) {
  return (
    <span className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid">
      {children}
    </span>
  );
}

// ---- model ------------------------------------------------------------------

// Human-readable, pluralised labels for the Brain node kinds (in a stable display
// order); anything the backend adds later still shows under its raw kind.
const NODE_KIND_LABELS: Record<string, string> = {
  endpoint: "Endpoints",
  page: "Pages",
  table: "Tables",
  model: "Models",
  role: "Roles",
};

function ModelCard({ projectId }: { projectId: string }) {
  const ingest = useIngest(projectId);
  // Refetch the model summary when a build finishes (ingest.status → succeeded).
  const { model } = useProjectModel(projectId, ingest.status);
  const built = model?.built ?? false;

  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">Model</h2>
          {built && model ? (
            <p className="mt-1 text-sm text-muted-foreground">
              <span className="font-medium text-foreground">Model built</span> —{" "}
              {model.node_count} {model.node_count === 1 ? "node" : "nodes"} ·{" "}
              {model.edge_count} {model.edge_count === 1 ? "edge" : "edges"}
              {model.last_built_at ? (
                <span className="text-status-neutral-solid">
                  {" · built "}
                  {relativeTime(model.last_built_at)}
                </span>
              ) : null}
            </p>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">
              Build the system model from the repository before running tests.
            </p>
          )}
        </div>
        {/* See the tests Polaris generated from the model (empty until a run). */}
        <Link
          to={`/projects/${projectId}/tests`}
          className="shrink-0 text-[13px] font-medium text-accent hover:underline"
        >
          View generated tests →
        </Link>
      </div>

      {built && model && model.nodes_by_kind.length > 0 ? (
        <div className="mt-3 flex flex-wrap gap-1.5">
          {model.nodes_by_kind.map((entry) => (
            <span
              key={entry.kind}
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-2 py-1 text-[12px] text-foreground-secondary"
            >
              {NODE_KIND_LABELS[entry.kind] ?? entry.kind}
              <span className="tabular-nums font-semibold text-foreground">
                {entry.count}
              </span>
            </span>
          ))}
        </div>
      ) : null}

      <div className="mt-3 flex items-center gap-3">
        <Button variant="outline" onClick={ingest.start} disabled={ingest.busy}>
          {ingest.busy ? "Building model…" : built ? "Rebuild model" : "Build model"}
        </Button>
        {ingest.status ? (
          <StatusBadge status={runStatusDescriptor(ingest.status)} />
        ) : null}
      </div>
      {ingest.error ? (
        <p role="alert" className="mt-2 text-sm text-status-fail-fg">
          {ingest.error}
        </p>
      ) : null}
    </section>
  );
}

// ---- connectors -------------------------------------------------------------

// Integrations on the roadmap — surfaced now (disabled) so operators know they're
// coming. Static/frontend-only; no backend until each connector actually ships.
const CONNECTORS: {
  name: string;
  description: string;
  icon: LucideIcon;
  to: string;
}[] = [
  {
    name: "Gitea",
    description: "Ingest repos and open PRs against your self-hosted Gitea.",
    icon: GitBranch,
    to: "/connectors/gitea",
  },
  {
    name: "Project management",
    description: "Push findings to your tracker (Jira, Linear, …).",
    icon: ClipboardList,
    to: "/connectors/pm",
  },
];

function ConnectorsCard() {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <h2 className="text-sm font-semibold text-foreground">Connectors</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Link Polaris to your git host and project tools.
      </p>
      <ul className="mt-3 space-y-2.5">
        {CONNECTORS.map((connector) => (
          <li key={connector.name}>
            <Link
              to={connector.to}
              className="flex items-center gap-3 rounded-lg border border-dashed border-border bg-background px-3.5 py-2.5 transition-colors hover:border-border hover:bg-surface"
            >
              <connector.icon
                className="h-4 w-4 shrink-0 text-status-neutral-solid"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-foreground">
                  {connector.name}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {connector.description}
                </p>
              </div>
              <span className="shrink-0 rounded-full bg-status-neutral-bg px-2 py-0.5 text-[11px] font-medium text-status-neutral-fg">
                Coming soon
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ---- loading ----------------------------------------------------------------

function OverviewSkeleton() {
  return (
    <div className="mt-3 space-y-7">
      <Skeleton className="h-9 w-64 rounded-lg" />
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-28 rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}
