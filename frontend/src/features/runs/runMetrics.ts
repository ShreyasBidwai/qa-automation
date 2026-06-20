/**
 * Read the headline metrics from a run's summary (GET /runs/{id}). The summary
 * is a loose `Record<string, unknown>` server-side, so every field is read
 * defensively — a missing metric renders as "—", never a crash.
 */

export interface RunMetrics {
  passRate: number | null;
  failed: number | null;
  errors: number | null;
  coverage: number | null;
  priorPassRate: number | null;
  target: string | null;
  finishedAt: string | null;
  projectId: string | null;
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function readMetrics(summary: Record<string, unknown> | null): RunMetrics {
  const s = summary ?? {};
  return {
    passRate: num(s.pass_rate),
    failed: num(s.failed),
    errors: num(s.errors),
    coverage: num(s.coverage),
    priorPassRate: num(s.prior_pass_rate),
    target: str(s.target) ?? str(s.project),
    finishedAt: str(s.finished_at),
    projectId: str(s.project_id),
  };
}

/** Format a rate as a whole-number percent. Accepts a 0–1 fraction or a percent. */
export function formatPercent(value: number | null): string {
  if (value === null) return "—";
  const percent = value <= 1 ? value * 100 : value;
  return `${Math.round(percent)}%`;
}

export function formatCount(value: number | null): string {
  return value === null ? "—" : String(value);
}

export interface PassRateDelta {
  points: number; // whole percentage points vs the prior run
  direction: "up" | "down" | "flat";
}

export function passRateDelta(
  current: number | null,
  prior: number | null,
): PassRateDelta | null {
  if (current === null || prior === null) return null;
  const toPercent = (v: number) => (v <= 1 ? v * 100 : v);
  const points = Math.round(toPercent(current) - toPercent(prior));
  return {
    points,
    direction: points > 0 ? "up" : points < 0 ? "down" : "flat",
  };
}
