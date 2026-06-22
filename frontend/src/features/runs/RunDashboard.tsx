import { ArrowDown, ArrowUp } from "lucide-react";
import { useState, type ReactNode } from "react";

import { EmptyState } from "@/components/EmptyState";
import { Link } from "@/components/Link";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/select";
import type { Finding } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { cn } from "@/lib/utils";

import {
  ALL,
  EMPTY_FILTERS,
  applyFilters,
  type FindingFilters,
} from "./findingFilters";
import {
  confidenceLabel,
  confidenceMix,
  historyCounts,
  severityCounts,
} from "./findingStats";
import {
  formatPercent,
  passRateDelta,
  readMetrics,
  type PassRateDelta,
} from "./runMetrics";
import { FindingDrawer } from "./FindingDrawer";
import { FindingRow } from "./FindingRow";
import { useRunDashboard } from "./useRunDashboard";

/** The at-a-glance health view for a completed run — the hero screen (T6.2). */
export function RunDashboard({
  runId,
  onSelectFinding,
}: {
  runId: string;
  onSelectFinding?: (finding: Finding) => void;
}) {
  const { summary, findings, loading, error, replaceFinding } = useRunDashboard(runId);
  const [filters, setFilters] = useState<FindingFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const metrics = readMetrics(summary);
  const delta = passRateDelta(metrics.passRate, metrics.priorPassRate);
  const visible = applyFilters(findings, filters);
  // Derive the open finding from the list so a triage update reflects in the drawer.
  const selected = findings.find((f) => f.id === selectedId) ?? null;
  // Open the detail drawer (progressive disclosure); still notify any listener.
  const select = (finding: Finding) => {
    setSelectedId(finding.id);
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
            <section className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
              <PassRateCard passRate={metrics.passRate} delta={delta} />
              <FindingsCard findings={findings} />
              <NewRegressionsCard findings={findings} />
              <ConfidenceCard findings={findings} />
            </section>

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
                  <div className="overflow-hidden rounded-xl border border-border bg-surface">
                    {visible.map((finding) => (
                      <FindingRow
                        key={finding.id}
                        finding={finding}
                        selected={finding.id === selectedId}
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
      <FindingDrawer
        finding={selected}
        runId={runId}
        onClose={() => setSelectedId(null)}
        onTriaged={replaceFinding}
      />
    </>
  );
}

// ---- stat cards -------------------------------------------------------------

function StatCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

function PassRateCard({
  passRate,
  delta,
}: {
  passRate: number | null;
  delta: PassRateDelta | null;
}) {
  const pct =
    passRate === null ? 0 : Math.round(passRate <= 1 ? passRate * 100 : passRate);
  return (
    <StatCard label="Pass rate">
      <div className="mt-2.5 flex items-baseline gap-2">
        <span className="text-[30px] font-semibold leading-none tracking-tight tabular-nums text-foreground">
          {formatPercent(passRate)}
        </span>
        {delta ? <DeltaTag delta={delta} /> : null}
      </div>
      <div className="mt-3.5 h-1.5 overflow-hidden rounded-full bg-status-neutral-bg">
        <div
          className="h-full rounded-full bg-status-pass-solid"
          style={{ width: `${pct}%` }}
        />
      </div>
    </StatCard>
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

function FindingsCard({ findings }: { findings: Finding[] }) {
  const counts = severityCounts(findings);
  return (
    <StatCard label="Findings">
      <div className="mt-2.5 flex items-baseline gap-2">
        <span className="text-[30px] font-semibold leading-none tracking-tight tabular-nums text-foreground">
          {findings.length}
        </span>
        <span className="text-xs text-muted-foreground">open</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
        <SeverityCount
          label={`${counts.critical} critical`}
          dot="bg-status-fail-solid"
          text="text-status-fail-fg"
        />
        <SeverityCount
          label={`${counts.major} major`}
          dot="bg-status-flaky-solid"
          text="text-status-flaky-fg"
        />
        <SeverityCount
          label={`${counts.minor} minor`}
          dot="bg-status-neutral-solid"
          text="text-muted-foreground"
        />
      </div>
    </StatCard>
  );
}

function SeverityCount({
  label,
  dot,
  text,
}: {
  label: string;
  dot: string;
  text: string;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1.5", text)}>
      <span className={cn("h-[7px] w-[7px] rounded-full", dot)} aria-hidden="true" />
      {label}
    </span>
  );
}

function NewRegressionsCard({ findings }: { findings: Finding[] }) {
  const counts = historyCounts(findings);
  return (
    <StatCard label="New / Regressions">
      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span className="text-[30px] font-semibold leading-none tracking-tight tabular-nums text-status-info-fg">
          {counts.new}
        </span>
        <span className="text-xs text-muted-foreground">new</span>
        <span className="mx-1 text-muted-foreground">·</span>
        <span className="text-[30px] font-semibold leading-none tracking-tight tabular-nums text-status-flaky-fg">
          {counts.regression}
        </span>
        <span className="text-xs text-muted-foreground">regr</span>
      </div>
    </StatCard>
  );
}

function ConfidenceCard({ findings }: { findings: Finding[] }) {
  const mix = confidenceMix(findings);
  const segments = [
    { key: "rule", count: mix.rule, bar: "bg-trust-rule-solid" },
    { key: "char", count: mix.characterization, bar: "bg-trust-char-solid" },
    { key: "spec", count: mix.spec, bar: "bg-trust-spec-solid" },
  ].filter((s) => s.count > 0);

  return (
    <StatCard label="Confidence">
      <div className="mt-2 text-sm font-semibold text-foreground">
        {confidenceLabel(mix)}
      </div>
      <div className="mt-3 flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-status-neutral-bg">
        {segments.map((s) => (
          <div key={s.key} className={s.bar} style={{ flexGrow: s.count }} />
        ))}
      </div>
      <div className="mt-2 flex gap-3 text-[11px] text-muted-foreground">
        <MixLegend dot="bg-trust-rule-solid" count={mix.rule} />
        <MixLegend dot="bg-trust-char-solid" count={mix.characterization} />
        <MixLegend dot="bg-trust-spec-solid" count={mix.spec} />
      </div>
    </StatCard>
  );
}

function MixLegend({ dot, count }: { dot: string; count: number }) {
  return (
    <span className="inline-flex items-center gap-1 tabular-nums">
      <span className={cn("h-1.5 w-1.5 rounded-full", dot)} aria-hidden="true" />
      {count}
    </span>
  );
}

// ---- filters ----------------------------------------------------------------

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
        label="Trust"
        value={filters.confidence}
        onChange={(v) => onChange({ ...filters, confidence: v })}
        options={[
          ["rule-derived", "Rule-derived"],
          ["characterization", "Characterization"],
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
      <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <input
          type="checkbox"
          checked={filters.hideMuted}
          onChange={(event) =>
            onChange({ ...filters, hideMuted: event.target.checked })
          }
          className="h-3.5 w-3.5 rounded border-border text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
        Hide muted
      </label>
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

function FilteredEmpty({ onClear }: { onClear: () => void }) {
  return (
    <div className="rounded-xl border border-dashed border-border bg-surface px-6 py-10 text-center">
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
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-24 rounded-xl border border-border bg-surface" />
        ))}
      </div>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-xl border border-border bg-surface px-4 py-3 text-sm"
    >
      <span className="text-status-fail-fg">Couldn&rsquo;t load this run.</span>{" "}
      <span className="text-muted-foreground">
        {message} Check the run id and try again.
      </span>
    </div>
  );
}
