import {
  AlertTriangle,
  Building2,
  CheckCircle2,
  ListChecks,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  Users,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useCallback } from "react";

import { Link } from "@/components/Link";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { QueueStats } from "@/lib/api/types";
import { opsApi } from "@/lib/api/client";
import { cn } from "@/lib/utils";

import { AdminScreen } from "./AdminScreen";
import { useAdminResource } from "./useAdminResource";

/** Operator overview (ADR-0065 dashboard style) — the queue at a glance + jumps into
 *  the console's sub-pages. */
export function AdminOverviewPage() {
  return (
    <AdminScreen
      icon={ShieldCheck}
      title="Operator console"
      subtitle="Cross-tenant health and controls for Polaris staff"
      perm="view_ops"
      scroll
    >
      <OverviewBody />
    </AdminScreen>
  );
}

function OverviewBody() {
  const fetcher = useCallback(() => opsApi.queue(), []);
  const { data, loading, error, reload } = useAdminResource(fetcher);

  if (loading) {
    return (
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[104px] rounded-xl" />
        ))}
      </div>
    );
  }
  if (error || !data) {
    return (
      <StatePanel
        icon={AlertTriangle}
        tone="danger"
        title="Couldn't load the queue"
        description="This is usually temporary — the ops service may be briefly unavailable."
        code={error ?? undefined}
        actions={<Button onClick={reload}>Retry</Button>}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3.5">
      <RunnerHealthBanner data={data} onRefresh={reload} />

      <section
        aria-label="Queue"
        className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4"
      >
        <StatCard label="Queued" value={data.queued} tone="neutral" />
        <StatCard label="Running" value={data.running} tone="info" />
        <StatCard
          label="Failed"
          value={data.failed}
          tone={data.failed > 0 ? "fail" : "neutral"}
        />
        <StatCard
          label="Stuck"
          value={data.stuck}
          tone={data.stuck > 0 ? "flaky" : "neutral"}
          hint="running past the threshold"
        />
      </section>

      <section className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        <StatCard label="Succeeded" value={data.succeeded} tone="pass" />
        <StatCard label="Cancelled" value={data.cancelled} tone="neutral" />
        <StatCard label="Total jobs" value={data.total} tone="neutral" />
      </section>

      <QuickLinks />
    </div>
  );
}

function RunnerHealthBanner({
  data,
  onRefresh,
}: {
  data: QueueStats;
  onRefresh: () => void;
}) {
  const healthy = data.runner_healthy;
  const Icon = healthy ? CheckCircle2 : XCircle;
  return (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-xl border px-4 py-3",
        healthy
          ? "border-status-pass-border bg-status-pass-bg"
          : "border-status-fail-border bg-status-fail-bg",
      )}
    >
      <div className="flex items-center gap-2.5">
        <Icon
          className={cn(
            "h-[18px] w-[18px]",
            healthy ? "text-status-pass-solid" : "text-status-fail-solid",
          )}
          aria-hidden="true"
        />
        <div>
          <p
            className={cn(
              "text-sm font-semibold",
              healthy ? "text-status-pass-fg" : "text-status-fail-fg",
            )}
          >
            {healthy ? "Runner healthy" : "Runner needs attention"}
          </p>
          <p className="text-[12.5px] text-status-neutral-solid">
            {healthy
              ? "No stuck jobs — the queue is draining."
              : `${data.stuck} job${data.stuck === 1 ? "" : "s"} stuck past the threshold.`}
          </p>
        </div>
      </div>
      <Button variant="outline" size="sm" onClick={onRefresh}>
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Refresh
      </Button>
    </div>
  );
}

const TONE: Record<string, string> = {
  neutral: "text-foreground",
  info: "text-status-info-solid",
  pass: "text-status-pass-solid",
  fail: "text-status-fail-solid",
  flaky: "text-status-flaky-solid",
};

function StatCard({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: number;
  tone: keyof typeof TONE | string;
  hint?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface px-[18px] py-4 shadow-card">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-2 text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums",
          TONE[tone] ?? "text-foreground",
        )}
      >
        {value}
      </div>
      {hint ? <p className="mt-2 text-[11.5px] text-marker">{hint}</p> : null}
    </div>
  );
}

const QUICK: { to: string; label: string; description: string; icon: LucideIcon }[] = [
  {
    to: "/admin/tenants",
    label: "Tenants",
    description: "Organizations, members, suspensions",
    icon: Building2,
  },
  {
    to: "/admin/users",
    label: "Users",
    description: "Accounts, staff roles, activation",
    icon: Users,
  },
  {
    to: "/admin/jobs",
    label: "Queue",
    description: "Inspect, cancel, and requeue jobs",
    icon: ListChecks,
  },
  {
    to: "/admin/incidents",
    label: "Incidents",
    description: "Captured internal failures",
    icon: AlertTriangle,
  },
  {
    to: "/admin/audit",
    label: "Audit",
    description: "The staff-action trail",
    icon: ScrollText,
  },
];

function QuickLinks() {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <h2 className="mb-3 text-sm font-semibold text-foreground">Jump to</h2>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 min-[1024px]:grid-cols-3">
        {QUICK.map((item) => (
          <Link
            key={item.to}
            to={item.to}
            className="flex items-start gap-3 rounded-lg border border-border-subtle px-3.5 py-3 transition-colors hover:bg-background"
          >
            <item.icon
              className="mt-0.5 h-4 w-4 flex-none text-status-neutral-solid"
              aria-hidden="true"
            />
            <div>
              <div className="text-[13px] font-medium text-foreground">
                {item.label}
              </div>
              <div className="mt-0.5 text-[12px] text-status-neutral-solid">
                {item.description}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
