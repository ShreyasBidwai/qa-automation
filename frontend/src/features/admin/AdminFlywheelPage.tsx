import { AlertTriangle, Sparkles } from "lucide-react";
import { useCallback, useState } from "react";

import { Skeleton } from "@/components/Skeleton";
import { StatePanel } from "@/components/StatePanel";
import { Button } from "@/components/ui/button";
import { passTone } from "@/features/runs/runMetrics";
import { adminApi } from "@/lib/api/client";
import type { GenerationQuality } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { AdminScreen } from "./AdminScreen";
import { useAdminResource } from "./useAdminResource";

// The trailing windows the flywheel can be scoped to. Segmenting by version is the
// other lever (ADR-0070) but is a later slice; the days filter ships now.
const RANGES = [
  { label: "7D", days: 7 },
  { label: "30D", days: 30 },
  { label: "90D", days: 90 },
] as const;

// The four execution outcomes (ADR-0064/0070) in a fixed order, good → neutral. Each is
// a RESERVED status colour paired with a text label in the legend — never colour alone,
// so the mix reads for colour-vision-deficient viewers and in print.
const OUTCOMES = [
  { key: "pass", label: "Passed", solid: "bg-status-pass-solid" },
  { key: "fail", label: "Failed", solid: "bg-status-fail-solid" },
  { key: "error", label: "Errored", solid: "bg-status-error-solid" },
  { key: "skipped", label: "Skipped", solid: "bg-status-neutral-solid" },
] as const;

/**
 * The generation-quality flywheel (C6, ADR-0070). Reads the eval aggregate over the
 * append-only generation-signal log — execution + triage are the free annotators — and
 * frames it as a self-improvement loop. The headline is a COMPOSITE quality index, not
 * pass-rate: a system that games green (skips the hard endpoints, files false positives)
 * must not score well, so the index rewards clean first-try passes and penalises errors,
 * false positives, and brittle self-heals.
 */
export function AdminFlywheelPage() {
  return (
    <AdminScreen
      icon={Sparkles}
      title="Flywheel"
      subtitle="Generation quality — the loop that sharpens with every run"
      perm="view_ops"
      scroll
    >
      <FlywheelBody />
    </AdminScreen>
  );
}

function FlywheelBody() {
  const [days, setDays] = useState<number>(30);
  const fetcher = useCallback(() => adminApi.generationQuality(days), [days]);
  const { data, loading, error, reload } = useAdminResource(fetcher);

  return (
    <div className="flex flex-col gap-3.5">
      <div className="flex items-center justify-between gap-3">
        <p className="text-[13px] text-status-neutral-solid">
          Free labels from execution &amp; triage, over the last {days} days
        </p>
        <RangeFilter days={days} onChange={setDays} />
      </div>

      {loading ? (
        <FlywheelSkeleton />
      ) : error || !data ? (
        <StatePanel
          icon={AlertTriangle}
          tone="danger"
          title="Couldn't load the flywheel"
          description="This is usually temporary — the metrics service may be briefly unavailable."
          code={error ?? undefined}
          actions={<Button onClick={reload}>Retry</Button>}
        />
      ) : data.total === 0 ? (
        <StatePanel
          icon={Sparkles}
          title="No generation signals yet"
          description="The flywheel populates as runs execute — each run appends validated rows that sharpen retrieval and shift these metrics. See ADR-0070."
        />
      ) : (
        <FlywheelMetrics data={data} />
      )}
    </div>
  );
}

// ---- the metrics view -------------------------------------------------------

function FlywheelMetrics({ data }: { data: GenerationQuality }) {
  const m = computeMetrics(data);

  return (
    <>
      <QualityIndexCard index={m.qualityIndex} passRate={m.passRate} />

      <section
        aria-label="Quality signals"
        className="grid grid-cols-2 gap-3.5 min-[720px]:grid-cols-3 min-[1100px]:grid-cols-6"
      >
        <StatTile
          label="Total signals"
          value={data.total.toLocaleString()}
          hint={`${m.executed.toLocaleString()} executed`}
        />
        <StatTile
          label="Pass without repair"
          value={formatRate(m.passWithoutRepairRate)}
          hint="clean first try"
          tone="pass"
        />
        <StatTile
          label="Error rate"
          value={formatRate(m.errorRate)}
          hint="bad generation"
          tone={pctOf(m.errorRate) > 0 ? "fail" : "neutral"}
        />
        <StatTile
          label="False-positive rate"
          value={formatRate(m.falsePositiveRate)}
          hint="rejected in triage"
          tone={pctOf(m.falsePositiveRate) > 0 ? "flaky" : "neutral"}
        />
        <StatTile
          label="Repair rate"
          value={formatRate(m.repairRate)}
          hint="needed self-repair"
        />
        <StatTile
          label="Heal / flake"
          value={`${formatRate(m.healRate)} / ${formatRate(m.flakeRate)}`}
          hint="brittle over time"
        />
      </section>

      <OutcomesCard data={data} executed={m.executed} />
    </>
  );
}

/** The composite index, shown prominently with the plain pass-rate beside it so the gap
 *  between "looks green" and "is good" is visible at a glance (the ADR-0070 point). */
function QualityIndexCard({
  index,
  passRate,
}: {
  index: number | null;
  passRate: number | null;
}) {
  const tone = index === null ? null : passTone(index);
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="text-xs font-medium text-muted-foreground">
            Generation quality index
          </div>
          <div className="mt-1.5 flex items-baseline gap-2.5">
            <span
              className={cn(
                "text-[44px] font-semibold leading-none tracking-[-0.02em] tabular-nums",
                tone ? tone.text : "text-muted-foreground",
              )}
            >
              {index === null ? "—" : index}
            </span>
            {index !== null ? (
              <span className="text-lg text-muted-foreground">/ 100</span>
            ) : null}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11px] font-medium uppercase tracking-[0.05em] text-status-neutral-solid">
            Raw pass rate
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums text-foreground-secondary">
            {formatRate(passRate)}
          </div>
        </div>
      </div>
      <p className="mt-3 max-w-2xl text-[12.5px] leading-relaxed text-muted-foreground">
        A composite: it rewards clean first-try passes and penalises errors, triage
        false-positives, and healed (brittle) tests. Pass-rate alone is never the target
        — a system that games green by skipping hard endpoints or filing false alarms
        must not score well (ADR-0070).
      </p>
    </section>
  );
}

/** The outcome mix as a single 100%-share bar (part-to-whole), with a 2px surface gap
 *  between segments and a labelled legend carrying the counts. */
function OutcomesCard({
  data,
  executed,
}: {
  data: GenerationQuality;
  executed: number;
}) {
  const segments = OUTCOMES.map((o) => ({
    ...o,
    value: data.by_outcome[o.key] ?? 0,
  }));

  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-foreground">Outcome mix</h2>
        <span className="text-xs text-status-neutral-solid">
          {executed.toLocaleString()} executed
        </span>
      </div>

      {executed > 0 ? (
        <>
          <div
            role="img"
            aria-label="Outcome breakdown"
            className="mt-4 flex h-3 gap-0.5 overflow-hidden rounded-full bg-border-subtle"
          >
            {segments
              .filter((s) => s.value > 0)
              .map((s) => (
                <div
                  key={s.key}
                  className={cn(
                    "h-full first:rounded-l-full last:rounded-r-full",
                    s.solid,
                  )}
                  style={{ width: `${(s.value / executed) * 100}%` }}
                  title={`${s.label}: ${s.value.toLocaleString()} (${Math.round(
                    (s.value / executed) * 100,
                  )}%)`}
                />
              ))}
          </div>
          <div className="mt-3.5 flex flex-wrap gap-x-5 gap-y-2">
            {segments.map((s) => (
              <span key={s.key} className="inline-flex items-center gap-1.5 text-xs">
                <span
                  className={cn("h-2 w-2 rounded-full", s.solid)}
                  aria-hidden="true"
                />
                <span className="font-medium text-foreground">{s.label}</span>
                <span className="tabular-nums text-muted-foreground">
                  {s.value.toLocaleString()} ({Math.round((s.value / executed) * 100)}%)
                </span>
              </span>
            ))}
          </div>
        </>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">
          Signals are captured, but none have executed yet — outcomes populate once the
          generated tests run.
        </p>
      )}
    </section>
  );
}

// ---- tiles ------------------------------------------------------------------

const TILE_TONE: Record<string, string> = {
  neutral: "text-foreground",
  pass: "text-status-pass-solid",
  fail: "text-status-fail-solid",
  flaky: "text-status-flaky-solid",
};

function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: keyof typeof TILE_TONE;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3.5 shadow-card">
      <div className="text-[11px] font-medium text-muted-foreground">{label}</div>
      <div
        className={cn(
          "mt-1.5 text-xl font-semibold leading-none tabular-nums",
          TILE_TONE[tone],
        )}
      >
        {value}
      </div>
      {hint ? <p className="mt-1.5 text-[11px] text-marker">{hint}</p> : null}
    </div>
  );
}

function FlywheelSkeleton() {
  return (
    <div className="flex flex-col gap-3.5">
      <Skeleton className="h-[140px] rounded-xl" />
      <div className="grid grid-cols-2 gap-3.5 min-[720px]:grid-cols-3 min-[1100px]:grid-cols-6">
        {[0, 1, 2, 3, 4, 5].map((i) => (
          <Skeleton key={i} className="h-[86px] rounded-xl" />
        ))}
      </div>
      <Skeleton className="h-[120px] rounded-xl" />
    </div>
  );
}

function RangeFilter({
  days,
  onChange,
}: {
  days: number;
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
          aria-checked={days === r.days}
          onClick={() => onChange(r.days)}
          className={cn(
            "rounded-[7px] px-3 py-1 text-[13px] font-medium transition-colors",
            days === r.days
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

// ---- pure metric maths ------------------------------------------------------

interface FlywheelMetricsResult {
  executed: number;
  passRate: number | null;
  passWithoutRepairRate: number | null;
  errorRate: number | null;
  repairRate: number | null;
  healRate: number | null;
  flakeRate: number | null;
  falsePositiveRate: number | null;
  qualityIndex: number | null;
}

/**
 * Derive the flywheel rates + composite index from the raw aggregate. Outcome-based
 * rates use `executed` (signals that actually ran and earned a label) as the denominator
 * — unexecuted signals have no outcome (ADR-0070), so diluting by them would understate
 * quality. `pass - repaired` (clamped ≥ 0) approximates "passed WITHOUT a self-repair":
 * a repair that ends in a pass is a pass that needed help, so it's subtracted out.
 */
function computeMetrics(data: GenerationQuality): FlywheelMetricsResult {
  const pass = data.by_outcome.pass ?? 0;
  const fail = data.by_outcome.fail ?? 0;
  const error = data.by_outcome.error ?? 0;
  const skipped = data.by_outcome.skipped ?? 0;
  const executed = pass + fail + error + skipped;

  const rate = (n: number): number | null => (executed > 0 ? n / executed : null);
  const passWithoutRepairRate = rate(Math.max(0, pass - data.repaired));
  const errorRate = rate(error);
  const repairRate = rate(data.repaired);
  const healRate = rate(data.healed);
  const flakeRate = rate(data.flaky);
  const falsePositiveRate =
    data.triaged > 0 ? data.triage_rejected / data.triaged : null;

  // Reward clean passes; subtract the share that errored, cried wolf, or needed healing.
  // Clamp to 0..1 → a 0..100 index. A treat-nulls-as-0 penalty keeps it defined once any
  // outcome exists; before that (executed === 0) quality is unknowable, so it's null.
  const raw =
    (passWithoutRepairRate ?? 0) -
    (errorRate ?? 0) -
    (falsePositiveRate ?? 0) -
    (healRate ?? 0);
  const qualityIndex =
    executed > 0 ? Math.round(100 * Math.max(0, Math.min(1, raw))) : null;

  return {
    executed,
    passRate: rate(pass),
    passWithoutRepairRate,
    errorRate,
    repairRate,
    healRate,
    flakeRate,
    falsePositiveRate,
    qualityIndex,
  };
}

/** A rate 0..1 as a whole-number percent; null (no basis) reads as an honest dash. */
function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

/** The percent value of a rate for tone thresholds; a null basis counts as 0. */
function pctOf(rate: number | null): number {
  return rate === null ? 0 : Math.round(rate * 100);
}
