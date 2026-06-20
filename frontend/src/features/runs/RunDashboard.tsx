import { ArrowDown, ArrowUp, ChevronRight } from "lucide-react";
import { useState, type ReactNode } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import type { Finding } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

import {
  confidenceSpec,
  layerSpec,
  severitySpec,
  statusSpec,
  type BadgeLevel,
} from "./findingBadges";
import {
  ALL,
  EMPTY_FILTERS,
  applyFilters,
  type FindingFilters,
} from "./findingFilters";
import {
  formatCount,
  formatPercent,
  passRateDelta,
  readMetrics,
  type PassRateDelta,
} from "./runMetrics";
import { FindingDrawer } from "./FindingDrawer";
import { useRunDashboard } from "./useRunDashboard";

/** The at-a-glance health view for a completed run (T6.2). */
export function RunDashboard({
  runId,
  onSelectFinding,
}: {
  runId: string;
  onSelectFinding?: (finding: Finding) => void;
}) {
  const { summary, findings, loading, error } = useRunDashboard(runId);
  const [filters, setFilters] = useState<FindingFilters>(EMPTY_FILTERS);
  const [selected, setSelected] = useState<Finding | null>(null);

  const metrics = readMetrics(summary);
  const delta = passRateDelta(metrics.passRate, metrics.priorPassRate);
  const visible = applyFilters(findings, filters);
  // Open the detail drawer (progressive disclosure); still notify any listener.
  const select = (finding: Finding) => {
    setSelected(finding);
    onSelectFinding?.(finding);
  };

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/runs">Runs</Link>}
        title={metrics.target ?? "Run results"}
        description={
          <span className="font-mono text-xs">
            {runId}
            {metrics.finishedAt
              ? ` · ${new Date(metrics.finishedAt).toLocaleString()}`
              : ""}
          </span>
        }
        action={
          <Button
            onClick={() =>
              navigate(
                metrics.projectId ? `/projects/${metrics.projectId}` : "/projects",
              )
            }
          >
            Re-run
          </Button>
        }
      />
      <main className="flex-1 space-y-6 px-6 py-8">
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBlock message={error} />
        ) : (
          <>
            <section className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard
                label="Pass rate"
                value={formatPercent(metrics.passRate)}
                delta={delta ? <DeltaTag delta={delta} /> : null}
              />
              <StatCard label="Failed" value={formatCount(metrics.failed)} />
              <StatCard label="Errors" value={formatCount(metrics.errors)} />
              <StatCard label="Coverage" value={formatPercent(metrics.coverage)} />
            </section>

            <ConfidenceStrip findings={findings} />

            {findings.length === 0 ? (
              <EmptyState
                title="No findings"
                description="Every test passed in this run — nothing to triage."
              />
            ) : (
              <section className="space-y-3">
                <Filters filters={filters} onChange={setFilters} />
                {visible.length === 0 ? (
                  <FilteredEmpty onClear={() => setFilters(EMPTY_FILTERS)} />
                ) : (
                  <div className="overflow-hidden rounded-lg border border-border bg-surface">
                    {visible.map((finding) => (
                      <FindingRow
                        key={finding.id}
                        finding={finding}
                        onSelect={select}
                      />
                    ))}
                  </div>
                )}
              </section>
            )}
          </>
        )}
      </main>
      <FindingDrawer finding={selected} onClose={() => setSelected(null)} />
    </>
  );
}

function StatCard({
  label,
  value,
  delta,
}: {
  label: string;
  value: string;
  delta?: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-[22px] font-medium tabular-nums text-foreground">
          {value}
        </span>
        {delta}
      </div>
    </div>
  );
}

function DeltaTag({ delta }: { delta: PassRateDelta }) {
  if (delta.direction === "flat") {
    return <span className="text-xs text-muted-foreground">no change</span>;
  }
  const up = delta.direction === "up";
  const Icon = up ? ArrowUp : ArrowDown;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 text-xs",
        up ? "text-status-pass-fg" : "text-status-fail-fg",
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {Math.abs(delta.points)}% vs prior
    </span>
  );
}

const DOT: Record<BadgeLevel, string> = {
  pass: "bg-status-pass-solid",
  fail: "bg-status-fail-solid",
  flaky: "bg-status-flaky-solid",
  info: "bg-status-info-solid",
  neutral: "bg-status-neutral-solid",
};

function ConfidenceStrip({ findings }: { findings: Finding[] }) {
  const high = findings.filter(
    (f) => f.oracle_source === "rule-derived" || f.oracle_source === "spec-grounded",
  ).length;
  const behaviour = findings.filter(
    (f) => f.oracle_source === "characterization",
  ).length;
  const flaky = findings.filter((f) => f.status === "flaky").length;

  return (
    <div className="flex flex-wrap gap-2">
      <Chip dot="pass" label="High confidence" count={high} />
      <Chip dot="flaky" label="Behaviour-changed" count={behaviour} />
      <Chip dot="info" label="Flaky" count={flaky} />
    </div>
  );
}

function Chip({
  dot,
  label,
  count,
}: {
  dot: BadgeLevel;
  label: string;
  count: number;
}) {
  return (
    <div className="inline-flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm">
      <span className={cn("h-2 w-2 rounded-full", DOT[dot])} aria-hidden="true" />
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium tabular-nums text-foreground">{count}</span>
    </div>
  );
}

function Filters({
  filters,
  onChange,
}: {
  filters: FindingFilters;
  onChange: (next: FindingFilters) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <FilterSelect
        label="Severity"
        value={filters.severity}
        onChange={(v) => onChange({ ...filters, severity: v })}
        options={[
          ["critical", "Critical"],
          ["major", "Major"],
          ["minor", "Minor"],
        ]}
      />
      <FilterSelect
        label="Layer"
        value={filters.layer}
        onChange={(v) => onChange({ ...filters, layer: v })}
        options={[
          ["ui", "ui"],
          ["api", "api"],
          ["db", "db"],
        ]}
      />
      <FilterSelect
        label="Confidence"
        value={filters.confidence}
        onChange={(v) => onChange({ ...filters, confidence: v })}
        options={[
          ["rule-derived", "Rule-derived"],
          ["characterization", "Behaviour-changed"],
          ["spec-grounded", "Spec-grounded"],
        ]}
      />
      <FilterSelect
        label="Status"
        value={filters.status}
        onChange={(v) => onChange({ ...filters, status: v })}
        options={[
          ["new", "New"],
          ["regression", "Regression"],
          ["flaky", "Flaky"],
          ["known", "Known"],
        ]}
      />
    </div>
  );
}

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  const id = `filter-${label.toLowerCase()}`;
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
        <option value={ALL}>All</option>
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </Select>
    </div>
  );
}

function FindingRow({
  finding,
  onSelect,
}: {
  finding: Finding;
  onSelect: (finding: Finding) => void;
}) {
  const severity = severitySpec(finding.severity);
  const layer = layerSpec(finding.layer);
  const confidence = confidenceSpec(finding.oracle_source);
  const status = statusSpec(finding.status);
  return (
    <button
      type="button"
      onClick={() => onSelect(finding)}
      className="flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left last:border-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    >
      <Badge level={severity.level}>{severity.label}</Badge>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium text-foreground">
          {finding.title}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <Badge level={layer.level}>{layer.label}</Badge>
          <Badge level={confidence.level}>{confidence.label}</Badge>
          <span className="text-xs text-muted-foreground">
            explains {finding.explains_count}{" "}
            {finding.explains_count === 1 ? "test" : "tests"}
          </span>
        </div>
      </div>
      <Badge level={status.level}>{status.label}</Badge>
      <ChevronRight
        className="h-4 w-4 shrink-0 text-muted-foreground"
        aria-hidden="true"
      />
    </button>
  );
}

function FilteredEmpty({ onClear }: { onClear: () => void }) {
  return (
    <div className="rounded-lg border border-dashed border-border bg-surface px-6 py-10 text-center">
      <p className="text-sm text-muted-foreground">No findings match these filters.</p>
      <Button variant="ghost" size="sm" className="mt-3" onClick={onClear}>
        Clear filters
      </Button>
    </div>
  );
}

function Loading() {
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">Loading run…</p>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-20 rounded-lg border border-border bg-surface" />
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-border bg-surface px-4 py-3 text-sm"
    >
      <span className="text-status-fail-fg">Couldn&rsquo;t load this run.</span>{" "}
      <span className="text-muted-foreground">
        {message} Check the run id and try again.
      </span>
    </div>
  );
}
