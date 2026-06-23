import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  CheckCircle2,
  MousePointerClick,
} from "lucide-react";
import { useState, type ReactNode } from "react";

import { LoadingFact } from "@/components/LoadingFact";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import type { Finding } from "@/lib/api/types";
import { navigate } from "@/lib/router";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

import { FindingDetail } from "./FindingDetail";
import { FindingFilterBar } from "./FindingFilterBar";
import { FindingRow } from "./FindingRow";
import { EMPTY_FILTERS, applyFilters, type FindingFilters } from "./findingFilters";
import {
  confidenceLabel,
  confidenceMix,
  historyCounts,
  severityCounts,
} from "./findingStats";
import { modeLabel } from "./modeLabel";
import {
  formatPercent,
  passRateDelta,
  readMetrics,
  type PassRateDelta,
  type RunMetrics,
} from "./runMetrics";
import { useRunDashboard } from "./useRunDashboard";

/** The run dashboard — the hero master-detail (Polaris Run Dashboard.dc.html). */
export function RunDashboard({
  runId,
  onSelectFinding,
}: {
  runId: string;
  onSelectFinding?: (finding: Finding) => void;
}) {
  const { mode, summary, findings, loading, error, replaceFinding } =
    useRunDashboard(runId);
  const [filters, setFilters] = useState<FindingFilters>(EMPTY_FILTERS);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const metrics = readMetrics(summary);
  const delta = passRateDelta(metrics.passRate, metrics.priorPassRate);
  const visible = applyFilters(findings, filters);
  // Default to the first finding (the file shows one selected on load); a click
  // pins another. Fall back across filtering so the panel is never blank.
  const selected =
    findings.find((f) => f.id === selectedId) ?? visible[0] ?? findings[0] ?? null;
  const select = (finding: Finding) => {
    setSelectedId(finding.id);
    onSelectFinding?.(finding);
  };

  return (
    <div className="flex flex-col min-[1024px]:h-full">
      <RunHeaderBand runId={runId} mode={mode} metrics={metrics} loading={loading} />

      {loading ? (
        <LoadingState />
      ) : error ? (
        <div className="flex items-center justify-center px-6 py-8 min-[1024px]:min-h-0 min-[1024px]:flex-1">
          <StatePanel
            icon={AlertTriangle}
            tone="danger"
            title="Couldn't load this run"
            description="The run may have been removed, or the service is briefly unavailable."
            code={error}
          />
        </div>
      ) : (
        <div className="flex flex-col px-6 pt-5 min-[1024px]:min-h-0 min-[1024px]:flex-1">
          <StatCards metrics={metrics} delta={delta} findings={findings} />

          {findings.length === 0 ? (
            <div className="flex items-center justify-center min-[1024px]:min-h-0 min-[1024px]:flex-1">
              <StatePanel
                icon={CheckCircle2}
                tone="success"
                title="This run came back clean"
                description="No findings across the run — every assertion held. Polaris keeps watching as the code changes."
              />
            </div>
          ) : (
            <div className="flex flex-col gap-4 pb-6 min-[1024px]:min-h-0 min-[1024px]:flex-1 min-[1024px]:flex-row">
              <FindingsList
                visible={visible}
                selectedId={selected?.id ?? null}
                onSelect={select}
                filters={filters}
                onFilters={setFilters}
              />
              <section
                aria-label="Finding detail"
                className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-card min-[1024px]:min-h-0 min-[1024px]:flex-1"
              >
                <div className="min-h-0 flex-1 overflow-y-auto">
                  {selected ? (
                    <FindingDetail
                      finding={selected}
                      runId={runId}
                      onTriaged={replaceFinding}
                    />
                  ) : (
                    <SelectAFinding />
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---- run header band --------------------------------------------------------

function RunHeaderBand({
  runId,
  mode,
  metrics,
  loading,
}: {
  runId: string;
  mode: string;
  metrics: RunMetrics;
  loading: boolean;
}) {
  return (
    <div className="flex flex-none flex-wrap items-center justify-between gap-3 border-b border-border bg-surface px-6 py-[18px]">
      <div className="flex flex-wrap items-center gap-3">
        <span className="font-mono text-[15px] font-medium text-foreground">
          Run {runId}
        </span>
        {!loading && mode ? (
          <>
            <BandDot />
            <span className="rounded-[5px] bg-accent-subtle px-[7px] py-0.5 font-mono text-[11px] font-medium text-accent">
              {modeLabel(mode)}
            </span>
          </>
        ) : null}
        {!loading && metrics.finishedAt ? (
          <>
            <BandDot />
            <span className="text-[13px] text-status-neutral-solid">
              {relativeTime(metrics.finishedAt)}
            </span>
          </>
        ) : null}
      </div>
      <div className="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          className="h-[34px]"
          onClick={() => navigate(`/runs/${runId}/live`)}
        >
          Replay journey
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-[34px]"
          onClick={() =>
            navigate(
              metrics.projectId ? `/projects/${metrics.projectId}/run` : "/projects",
            )
          }
        >
          Re-run
        </Button>
        <Button
          variant="outline"
          size="sm"
          className="h-[34px]"
          disabled
          title="Export is coming in a later slice"
        >
          Export
        </Button>
      </div>
    </div>
  );
}

function BandDot() {
  return <span className="h-[3px] w-[3px] rounded-full bg-marker" aria-hidden="true" />;
}

// ---- stat cards -------------------------------------------------------------

function StatCards({
  metrics,
  delta,
  findings,
}: {
  metrics: RunMetrics;
  delta: PassRateDelta | null;
  findings: Finding[];
}) {
  return (
    <section
      aria-label="Run stats"
      className="mb-[18px] grid flex-none grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4"
    >
      <PassRateCard passRate={metrics.passRate} delta={delta} />
      <FindingsCard findings={findings} />
      <NewRegressionsCard findings={findings} />
      <ConfidenceCard findings={findings} />
    </section>
  );
}

function StatCard({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-[18px] py-4 shadow-card">
      <div className="text-xs font-medium text-muted-foreground">{label}</div>
      {children}
    </div>
  );
}

const BIG_NUMBER =
  "text-[30px] font-semibold leading-none tracking-[-0.02em] tabular-nums";

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
        <span className={cn(BIG_NUMBER, "text-foreground")}>
          {formatPercent(passRate)}
        </span>
        {delta ? <DeltaTag delta={delta} /> : null}
      </div>
      <div className="mt-3 h-[5px] overflow-hidden rounded-full bg-border-subtle">
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
        <span className={cn(BIG_NUMBER, "text-foreground")}>{findings.length}</span>
        <span className="text-xs text-status-neutral-solid">open</span>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-medium">
        <SeverityCount
          n={counts.critical}
          label="critical"
          dot="bg-severity-critical-dot"
          text="text-severity-critical-fg"
        />
        <SeverityCount
          n={counts.major}
          label="major"
          dot="bg-severity-major-dot"
          text="text-severity-major-fg"
        />
        <SeverityCount
          n={counts.minor}
          label="minor"
          dot="bg-severity-minor-dot"
          text="text-severity-minor-fg"
        />
      </div>
    </StatCard>
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

function NewRegressionsCard({ findings }: { findings: Finding[] }) {
  const counts = historyCounts(findings);
  return (
    <StatCard label="New / Regressions">
      <div className="mt-2.5 flex items-baseline gap-1.5">
        <span className={cn(BIG_NUMBER, "text-status-info-solid")}>{counts.new}</span>
        <span className="text-[13px] text-status-neutral-solid">new</span>
        <span className="mx-0.5 text-lg text-marker">·</span>
        <span className={cn(BIG_NUMBER, "text-severity-major-fg")}>
          {counts.regression}
        </span>
        <span className="text-[13px] text-status-neutral-solid">regr</span>
      </div>
      <div className="mt-2.5 text-xs text-muted-foreground">
        compared with the previous run
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
      <div className="mb-3 mt-2.5 text-[15px] font-semibold text-foreground">
        {confidenceLabel(mix)}
      </div>
      <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-border-subtle">
        {segments.map((s) => (
          <div key={s.key} className={s.bar} style={{ flexGrow: s.count }} />
        ))}
      </div>
      <div className="mt-2.5 flex gap-3 text-[11px] text-muted-foreground">
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

// ---- findings list (master) -------------------------------------------------

function FindingsList({
  visible,
  selectedId,
  onSelect,
  filters,
  onFilters,
}: {
  visible: Finding[];
  selectedId: string | null;
  onSelect: (finding: Finding) => void;
  filters: FindingFilters;
  onFilters: (next: FindingFilters) => void;
}) {
  return (
    <section
      aria-label="Findings"
      className="flex flex-col overflow-hidden rounded-xl border border-border bg-surface shadow-card min-[1024px]:min-h-0 min-[1024px]:w-[42%] min-[1024px]:min-w-[380px]"
    >
      <div className="flex-none border-b border-border-subtle px-4 py-3.5">
        <div className="mb-3 flex items-center justify-between">
          <span className="text-[13px] font-semibold text-foreground">
            Findings{" "}
            <span className="font-normal text-status-neutral-solid">· ranked</span>
          </span>
          <span className="font-mono text-[11px] text-status-neutral-solid">
            {visible.length} shown
          </span>
        </div>
        <FindingFilterBar filters={filters} onChange={onFilters} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {visible.length === 0 ? (
          <div className="px-6 py-10 text-center">
            <p className="text-sm text-muted-foreground">
              No findings match these filters.
            </p>
            <Button
              variant="ghost"
              size="sm"
              className="mt-3"
              onClick={() => onFilters(EMPTY_FILTERS)}
            >
              Clear filters
            </Button>
          </div>
        ) : (
          visible.map((finding) => (
            <FindingRow
              key={finding.id}
              finding={finding}
              selected={finding.id === selectedId}
              onSelect={onSelect}
            />
          ))
        )}
      </div>
    </section>
  );
}

// ---- states -----------------------------------------------------------------

function SelectAFinding() {
  return (
    <div className="flex h-full items-center justify-center">
      <StatePanel
        size="sm"
        icon={MousePointerClick}
        title="Select a finding"
        description="Pick a finding on the left to see its blast path, evidence, and history."
      />
    </div>
  );
}

function LoadingState() {
  return (
    <div className="flex flex-col gap-4 px-6 pt-5">
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 min-[1024px]:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-[104px] rounded-xl border border-border bg-surface shadow-card"
          />
        ))}
      </div>
      <div className="flex flex-col items-center gap-1.5 pt-1">
        <p className="text-sm text-muted-foreground">Loading run…</p>
        <LoadingFact />
      </div>
    </div>
  );
}
