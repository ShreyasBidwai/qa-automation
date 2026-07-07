import { AlertTriangle, LayoutDashboard } from "lucide-react";
import { useEffect, useState } from "react";

import { Link } from "@/components/Link";
import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type {
  AccountDashboard,
  ProjectHealthItem,
  RecentRunItem,
} from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

import { modeLabel } from "../runs/modeLabel";
import { formatPercent } from "../runs/runMetrics";
import { passTone } from "../runs/runMetrics";
import { DonutChart, LegendDot, TrendArea } from "./charts";
import { useAccountDashboard } from "./useAccountDashboard";

// The time windows the account trend + range cards can be scoped to.
const RANGES = [
  { label: "7D", days: 7 },
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
  { label: "1Y", days: 365 },
] as const;

// Outcome tokens, shared across the cards/charts so the colour language is consistent.
const OUTCOME_STYLE = {
  passed: { dot: "bg-status-pass-solid", text: "text-status-pass-solid" },
  failed: { dot: "bg-status-fail-solid", text: "text-status-fail-solid" },
  errored: { dot: "bg-status-flaky-solid", text: "text-status-flaky-solid" },
  unverified: { dot: "bg-status-neutral-solid", text: "text-status-neutral-solid" },
} as const;

/**
 * The account dashboard (ADR-0065) — the post-login landing when the user has projects.
 * Account-wide health + a pass-rate trend + per-project health, with a time filter. If
 * the account has NO projects, it hands off to Projects (where the first one is made).
 */
export function DashboardPage() {
  const [rangeDays, setRangeDays] = useState<number>(30);
  const { data, loading, error } = useAccountDashboard(rangeDays);

  // Zero projects → the account has nothing to summarise yet; send the user to Projects
  // to register their first one (the Projects screen owns the empty/onboarding state).
  useEffect(() => {
    if (!loading && !error && data && data.projects_total === 0) {
      navigate("/projects");
    }
  }, [loading, error, data]);

  return (
    <div className="mx-auto max-w-[1760px] px-6 py-8 lg:px-8">
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-lg border-[1.5px] border-marker">
            <LayoutDashboard
              className="h-4 w-4 text-status-neutral-solid"
              aria-hidden="true"
            />
          </span>
          <div>
            <h1 className="text-[20px] font-semibold tracking-[-0.01em] text-foreground">
              Dashboard
            </h1>
            <p className="mt-0.5 text-[13px] text-status-neutral-solid">
              Health across every project in your account
            </p>
          </div>
        </div>
        <RangeFilter rangeDays={rangeDays} onChange={setRangeDays} />
      </header>

      {loading ? (
        <DashboardSkeleton />
      ) : error ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load your dashboard"
          description="This is usually temporary — the summary service may be briefly unavailable."
          code={error}
          actions={<Button onClick={() => window.location.reload()}>Retry</Button>}
        />
      ) : data && data.projects_total > 0 ? (
        <DashboardBody data={data} />
      ) : null}
    </div>
  );
}

function RangeFilter({
  rangeDays,
  onChange,
}: {
  rangeDays: number;
  onChange: (days: number) => void;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Time range"
      className="inline-flex rounded-lg border border-border bg-surface p-0.5"
    >
      {RANGES.map((r) => (
        <button
          key={r.days}
          type="button"
          role="radio"
          aria-checked={rangeDays === r.days}
          onClick={() => onChange(r.days)}
          className={cn(
            "rounded-[7px] px-3 py-1 text-[13px] font-medium transition-colors",
            rangeDays === r.days
              ? "bg-accent-subtle text-accent"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

function DashboardBody({ data }: { data: AccountDashboard }) {
  return (
    <div className="space-y-3.5">
      <HeadlineCards data={data} />
      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <TrendCard data={data} />
        <OutcomesCard data={data} />
      </div>
      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <ProjectHealthCard rows={data.project_health} />
        <RecentRunsCard runs={data.recent_runs} />
      </div>
    </div>
  );
}

// ---- headline cards ---------------------------------------------------------

function HeadlineCards({ data }: { data: AccountDashboard }) {
  const pct = data.pass_rate === null ? null : Math.round(data.pass_rate * 100);
  const tone = pct === null ? null : passTone(pct);
  return (
    <section
      aria-label="Account headline"
      className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4"
    >
      <Card label="Pass rate">
        <div className="flex items-baseline gap-2">
          <span
            className={cn(
              "text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums",
              tone ? tone.text : "text-muted-foreground",
            )}
          >
            {formatPercent(data.pass_rate)}
          </span>
        </div>
        <p className="mt-2.5 text-xs text-muted-foreground">
          {data.tests_total} {data.tests_total === 1 ? "test" : "tests"} ·{" "}
          {data.runs_total} {data.runs_total === 1 ? "run" : "runs"}
        </p>
      </Card>

      <Card label="Open findings">
        <div className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
          {data.open_findings.total ?? 0}
        </div>
        <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1">
          <LegendDot
            colorClass="bg-severity-critical-dot"
            count={data.open_findings.critical ?? 0}
            label="critical"
          />
          <LegendDot
            colorClass="bg-severity-major-dot"
            count={data.open_findings.major ?? 0}
            label="major"
          />
          <LegendDot
            colorClass="bg-severity-minor-dot"
            count={data.open_findings.minor ?? 0}
            label="minor"
          />
        </div>
      </Card>

      <Card label="Projects">
        <div className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
          {data.projects_total}
        </div>
        <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1">
          <LegendDot
            colorClass="bg-status-pass-solid"
            count={data.projects_by_status.passing ?? 0}
            label="passing"
          />
          <LegendDot
            colorClass="bg-status-fail-solid"
            count={data.projects_by_status.action_needed ?? 0}
            label="need action"
          />
          <LegendDot
            colorClass="bg-status-neutral-solid"
            count={data.projects_by_status.never_run ?? 0}
            label="never run"
          />
        </div>
      </Card>

      <Card label="Runs">
        <div className="text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums text-foreground">
          {data.runs_total}
        </div>
        <div className="mt-2.5 flex flex-wrap gap-x-3 gap-y-1">
          <LegendDot
            colorClass={OUTCOME_STYLE.passed.dot}
            count={data.outcomes.pass ?? 0}
            label="passed"
          />
          <LegendDot
            colorClass={OUTCOME_STYLE.failed.dot}
            count={data.outcomes.fail ?? 0}
            label="failed"
          />
          <LegendDot
            colorClass={OUTCOME_STYLE.unverified.dot}
            count={data.outcomes.skipped ?? 0}
            label="unverified"
          />
        </div>
      </Card>
    </section>
  );
}

function Card({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-[18px] py-4 shadow-card">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

// ---- trend + outcomes -------------------------------------------------------

function TrendCard({ data }: { data: AccountDashboard }) {
  const points = data.trend.map((p) => ({ label: p.date, value: p.pass_rate }));
  const hasData = points.some((p) => p.value !== null);
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Pass-rate trend</h2>
        <span className="text-xs text-status-neutral-solid">
          last {data.range_days} days
        </span>
      </div>
      {hasData ? (
        <div className="mt-4">
          <TrendArea points={points} />
          <div className="mt-1 flex justify-between font-mono text-[10.5px] text-marker">
            <span>{points[0]?.label}</span>
            <span>{points[points.length - 1]?.label}</span>
          </div>
        </div>
      ) : (
        <EmptyChart message="No runs in this window yet." />
      )}
    </section>
  );
}

function OutcomesCard({ data }: { data: AccountDashboard }) {
  const segments = [
    {
      key: "passed",
      label: "passed",
      value: data.outcomes.pass ?? 0,
      colorClass: OUTCOME_STYLE.passed.text,
    },
    {
      key: "failed",
      label: "failed",
      value: data.outcomes.fail ?? 0,
      colorClass: OUTCOME_STYLE.failed.text,
    },
    {
      key: "errored",
      label: "errored",
      value: data.outcomes.error ?? 0,
      colorClass: OUTCOME_STYLE.errored.text,
    },
    {
      key: "unverified",
      label: "unverified",
      value: data.outcomes.skipped ?? 0,
      colorClass: OUTCOME_STYLE.unverified.text,
    },
  ];
  const total = segments.reduce((s, x) => s + x.value, 0);
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <h2 className="text-sm font-semibold text-foreground">Test outcomes</h2>
      {total > 0 ? (
        <div className="mt-3 flex items-center gap-5">
          <DonutChart
            segments={segments}
            center={
              <>
                <span className="text-[22px] font-semibold leading-none tabular-nums text-foreground">
                  {total}
                </span>
                <span className="text-[10.5px] text-muted-foreground">tests</span>
              </>
            }
          />
          <div className="flex flex-col gap-1.5">
            {segments.map((s) => (
              <LegendDot
                key={s.key}
                colorClass={OUTCOME_STYLE[s.key as keyof typeof OUTCOME_STYLE].dot}
                count={s.value}
                label={s.label}
              />
            ))}
          </div>
        </div>
      ) : (
        <EmptyChart message="No tests run in this window yet." />
      )}
    </section>
  );
}

function EmptyChart({ message }: { message: string }) {
  return (
    <div className="flex h-[148px] items-center justify-center text-sm text-muted-foreground">
      {message}
    </div>
  );
}

// ---- project health ---------------------------------------------------------

const STATUS_PILL: Record<string, { label: string; cls: string }> = {
  passing: {
    label: "Passing",
    cls: "bg-status-pass-bg text-status-pass-fg",
  },
  action_needed: {
    label: "Action needed",
    cls: "bg-status-fail-bg text-status-fail-fg",
  },
  errored: {
    label: "Errored",
    cls: "bg-status-flaky-bg text-status-flaky-fg",
  },
  never_run: {
    label: "Never run",
    cls: "bg-status-neutral-bg text-status-neutral-fg",
  },
};

function ProjectHealthCard({ rows }: { rows: ProjectHealthItem[] }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="flex items-center justify-between px-5 py-3.5">
        <h2 className="text-sm font-semibold text-foreground">Project health</h2>
        <Link
          to="/projects"
          className="text-[13px] font-medium text-accent hover:underline"
        >
          All projects →
        </Link>
      </div>
      <div className="grid grid-cols-[minmax(0,2fr)_1fr_1.2fr_0.8fr_0.9fr] border-b border-border-subtle bg-background px-5 py-2">
        {["Project", "Status", "Pass rate", "Findings", "Last run"].map((h) => (
          <span
            key={h}
            className="text-[11px] font-semibold uppercase tracking-[0.05em] text-status-neutral-solid"
          >
            {h}
          </span>
        ))}
      </div>
      {rows.length === 0 ? (
        <p className="px-5 py-6 text-sm text-muted-foreground">No projects yet.</p>
      ) : (
        rows.map((row) => <ProjectHealthRow key={row.project_id} row={row} />)
      )}
    </section>
  );
}

function ProjectHealthRow({ row }: { row: ProjectHealthItem }) {
  const pill = STATUS_PILL[row.status] ?? STATUS_PILL.never_run;
  const pct = row.pass_rate === null ? null : Math.round(row.pass_rate * 100);
  return (
    <Link
      to={`/projects/${row.project_id}`}
      className="grid grid-cols-[minmax(0,2fr)_1fr_1.2fr_0.8fr_0.9fr] items-center border-b border-border-subtle px-5 py-3 transition-colors last:border-b-0 hover:bg-background"
    >
      <span className="truncate text-[13px] font-medium text-foreground">
        {row.name}
      </span>
      <span>
        <span
          className={cn("rounded-full px-2 py-0.5 text-[11px] font-medium", pill.cls)}
        >
          {pill.label}
        </span>
      </span>
      <span className="flex items-center gap-2 pr-3">
        <span className="h-[5px] flex-1 overflow-hidden rounded-full bg-border-subtle">
          <span
            className={cn(
              "block h-full rounded-full",
              pct === null ? "" : passTone(pct).fill,
            )}
            style={{ width: `${pct ?? 0}%` }}
          />
        </span>
        <span className="w-9 text-right text-xs tabular-nums text-status-neutral-fg">
          {formatPercent(row.pass_rate)}
        </span>
      </span>
      <span
        className={cn(
          "text-[13px] font-semibold tabular-nums",
          row.open_findings > 0 ? "text-status-fail-fg" : "text-muted-foreground",
        )}
      >
        {row.open_findings}
      </span>
      <span className="text-xs text-status-neutral-solid">
        {row.last_run_at ? relativeTime(row.last_run_at) : "—"}
      </span>
    </Link>
  );
}

// ---- recent runs ------------------------------------------------------------

function RecentRunsCard({ runs }: { runs: RecentRunItem[] }) {
  return (
    <section className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
      <div className="px-5 py-3.5">
        <h2 className="text-sm font-semibold text-foreground">Recent runs</h2>
      </div>
      {runs.length === 0 ? (
        <p className="px-5 pb-5 text-sm text-muted-foreground">
          No runs yet — start one from a project.
        </p>
      ) : (
        <ul>
          {runs.map((run) => (
            <li key={run.run_id}>
              <Link
                to={`/runs/${run.run_id}/findings`}
                className="flex items-center gap-3 border-t border-border-subtle px-5 py-2.5 transition-colors hover:bg-background"
              >
                <span className="min-w-0 flex-1 truncate text-[13px] text-foreground">
                  {run.project_name}
                </span>
                <span className="rounded-[5px] bg-status-neutral-bg px-[7px] py-0.5 font-mono text-[10px] text-status-neutral-fg">
                  {modeLabel(run.mode)}
                </span>
                <span className="w-10 text-right text-xs tabular-nums text-status-neutral-fg">
                  {formatPercent(run.pass_rate)}
                </span>
                <span className="w-16 text-right text-[11px] text-status-neutral-solid">
                  {relativeTime(run.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// ---- loading ----------------------------------------------------------------

function DashboardSkeleton() {
  return (
    <div className="space-y-3.5">
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-[104px] rounded-xl" />
        ))}
      </div>
      <div className="grid gap-3.5 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Skeleton className="h-[236px] rounded-xl" />
        <Skeleton className="h-[236px] rounded-xl" />
      </div>
      <Skeleton className="h-64 rounded-xl" />
    </div>
  );
}
