import { AlertTriangle, ListChecks, RotateCcw, XCircle } from "lucide-react";
import { useCallback, useState, type ReactNode } from "react";

import { SkeletonRows } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { JobSummary, QueueStats } from "@/lib/api/types";
import { adminApi, opsApi } from "@/lib/api/client";
import { useStaff } from "@/lib/auth/useStaff";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

import { AdminScreen } from "./AdminScreen";
import { isCancellable, isRequeueable, jobStatusViz } from "./jobStatus";
import { useAdminResource } from "./useAdminResource";

const ALL = "all";
const JOB_LIMIT = 100;
// queue → status pill order matches the ops snapshot.
const STATUSES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
const COLS = "grid-cols-[1.4fr_1fr_0.9fr_0.7fr_1fr_auto]";

/** Queue & jobs (GET /ops/queue + /ops/jobs) — inspect the queue and act on jobs. */
export function AdminJobsPage() {
  return (
    <AdminScreen
      icon={ListChecks}
      title="Queue"
      subtitle="Cross-tenant job queue — inspect, cancel, and requeue"
      perm="view_ops"
    >
      <JobsBody />
    </AdminScreen>
  );
}

function JobsBody() {
  const { hasPerm } = useStaff();
  const canManage = hasPerm("manage_jobs");
  const [status, setStatus] = useState<string>(ALL);

  const queueFetch = useCallback(() => opsApi.queue(), []);
  const queue = useAdminResource(queueFetch);

  const jobsFetch = useCallback(
    () =>
      opsApi.jobs({ status: status === ALL ? undefined : status, limit: JOB_LIMIT }),
    [status],
  );
  const jobs = useAdminResource(jobsFetch);

  // After a mutation the queue depth AND the current list both change — reload both so
  // the view reflects the new reality (a requeue also mints a new queued job). The
  // reload fns are stable, so `refresh` stays stable too.
  const reloadQueue = queue.reload;
  const reloadJobs = jobs.reload;
  const refresh = useCallback(() => {
    reloadQueue();
    reloadJobs();
  }, [reloadQueue, reloadJobs]);

  return (
    <>
      <QueueStrip queue={queue.data} loading={queue.loading} />

      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          aria-label="Status"
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="h-[34px] rounded-lg border border-border bg-surface px-3 text-[13px] font-medium text-status-neutral-fg transition-colors focus-visible:border-accent"
        >
          <option value={ALL}>All statuses</option>
          {STATUSES.map((value) => (
            <option key={value} value={value}>
              {jobStatusViz(value).label}
            </option>
          ))}
        </select>
      </div>

      <JobsTable
        jobs={jobs.data?.items ?? []}
        loading={jobs.loading}
        error={jobs.error}
        canManage={canManage}
        onChanged={refresh}
      />
    </>
  );
}

function QueueStrip({
  queue,
  loading,
}: {
  queue: QueueStats | null;
  loading: boolean;
}) {
  if (loading || !queue) {
    return <div className="mb-4 h-[52px] shrink-0 rounded-xl border border-border" />;
  }
  const cells: [string, number, string][] = [
    ["Queued", queue.queued, "text-foreground"],
    ["Running", queue.running, "text-status-info-solid"],
    [
      "Failed",
      queue.failed,
      queue.failed > 0 ? "text-status-fail-solid" : "text-foreground",
    ],
    [
      "Stuck",
      queue.stuck,
      queue.stuck > 0 ? "text-status-flaky-solid" : "text-foreground",
    ],
  ];
  return (
    <div className="mb-4 flex shrink-0 flex-wrap items-center gap-x-6 gap-y-2 rounded-xl border border-border bg-surface px-5 py-3 shadow-card">
      {cells.map(([label, value, tone]) => (
        <div key={label} className="flex items-baseline gap-2">
          <span className={cn("text-lg font-semibold tabular-nums", tone)}>
            {value}
          </span>
          <span className="text-[12px] text-status-neutral-solid">{label}</span>
        </div>
      ))}
      <span
        className={cn(
          "ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium",
          queue.runner_healthy
            ? "bg-status-pass-bg text-status-pass-fg"
            : "bg-status-fail-bg text-status-fail-fg",
        )}
      >
        <span
          className={cn(
            "h-[6px] w-[6px] rounded-full",
            queue.runner_healthy ? "bg-status-pass-solid" : "bg-status-fail-solid",
          )}
          aria-hidden="true"
        />
        {queue.runner_healthy ? "Runner healthy" : "Runner degraded"}
      </span>
    </div>
  );
}

function JobsTable({
  jobs,
  loading,
  error,
  canManage,
  onChanged,
}: {
  jobs: JobSummary[];
  loading: boolean;
  error: string | null;
  canManage: boolean;
  onChanged: () => void;
}) {
  if (loading) return <SkeletonRows label="Loading jobs…" />;
  if (error) {
    return (
      <StatePanel
        icon={AlertTriangle}
        tone="danger"
        title="Couldn't load jobs"
        description="This is usually temporary — the ops service may be briefly unavailable."
        code={error}
      />
    );
  }
  if (jobs.length === 0) {
    return (
      <StatePanel
        icon={ListChecks}
        title="No jobs"
        description="No jobs match this filter. Nothing is waiting in the queue right now."
      />
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
      <div
        className={`grid shrink-0 ${COLS} border-b border-border-subtle bg-background px-5 py-2.5`}
      >
        <ColHead>Job</ColHead>
        <ColHead>Kind</ColHead>
        <ColHead>Status</ColHead>
        <ColHead>Attempts</ColHead>
        <ColHead>Created</ColHead>
        <span aria-hidden="true" />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {jobs.map((job) => (
          <JobRow key={job.id} job={job} canManage={canManage} onChanged={onChanged} />
        ))}
      </div>
    </div>
  );
}

function JobRow({
  job,
  canManage,
  onChanged,
}: {
  job: JobSummary;
  canManage: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const viz = jobStatusViz(job.status);

  async function act(kind: "cancel" | "requeue") {
    setError(null);
    setBusy(true);
    const result =
      kind === "cancel"
        ? await adminApi.cancelJob(job.id)
        : await adminApi.requeueJob(job.id);
    setBusy(false);
    if (result.ok) {
      onChanged();
      return;
    }
    setError(result.error ?? `Couldn't ${kind} this job.`);
  }

  return (
    <div className="border-b border-border-subtle last:border-b-0">
      <div className={`grid ${COLS} items-center gap-2 px-5 py-3`}>
        <span
          title={job.id}
          className="truncate font-mono text-[12.5px] font-medium text-foreground"
        >
          {job.id.slice(0, 8)}
        </span>
        <span className="truncate text-[13px] text-status-neutral-fg">
          {job.kind}
          {job.mode ? (
            <span className="ml-1.5 font-mono text-[11px] text-marker">{job.mode}</span>
          ) : null}
        </span>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-xs font-medium",
            viz.text,
          )}
        >
          <span
            className={cn("h-[6px] w-[6px] rounded-full", viz.dot)}
            aria-hidden="true"
          />
          {viz.label}
        </span>
        <span className="text-[13px] tabular-nums text-status-neutral-fg">
          {job.attempts}/{job.max_attempts}
        </span>
        <span className="text-xs text-status-neutral-solid">
          {relativeTime(job.created_at)}
        </span>
        <span className="flex justify-end gap-2">
          {canManage && isCancellable(job.status) ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => act("cancel")}
            >
              <XCircle className="h-3.5 w-3.5" aria-hidden="true" />
              Cancel
            </Button>
          ) : null}
          {canManage && isRequeueable(job.status) ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={busy}
              onClick={() => act("requeue")}
            >
              <RotateCcw className="h-3.5 w-3.5" aria-hidden="true" />
              Requeue
            </Button>
          ) : null}
        </span>
      </div>
      {error ? (
        <p role="alert" className="px-5 pb-3 text-xs text-status-fail-fg">
          {error}
        </p>
      ) : null}
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
