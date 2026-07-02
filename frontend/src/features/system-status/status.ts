import type { ApiResult } from "@/lib/api/client";
import type { HealthzResponse, ReadyzResponse } from "@/lib/api/types";

/** A status level maps to exactly one badge colour + icon (see StatusBadge).
 *  `error` is a test/run that COULDN'T run (infra) — distinct from `fail` (a real
 *  failure) so a user never conflates "the app is broken" with "we couldn't test it". */
export type StatusLevel = "pass" | "fail" | "error" | "flaky" | "info" | "neutral";

export interface StatusDescriptor {
  level: StatusLevel;
  /** Human-readable label — the meaning, never conveyed by colour alone. */
  label: string;
}

export const CHECKING: StatusDescriptor = { level: "info", label: "Checking…" };

/** Backend liveness from GET /healthz. */
export function deriveBackendStatus(
  result: ApiResult<HealthzResponse>,
): StatusDescriptor {
  if (result.status === 0) return { level: "fail", label: "Unreachable" };
  if (result.ok && result.data?.status === "ok") {
    return { level: "pass", label: "Operational" };
  }
  return { level: "fail", label: "Error" };
}

/** Database health from GET /readyz (`checks.database`). */
export function deriveDatabaseStatus(
  result: ApiResult<ReadyzResponse>,
): StatusDescriptor {
  if (result.status === 0) return { level: "neutral", label: "Unknown" };

  const database = result.data?.checks?.database;
  if (database === "up") return { level: "pass", label: "Connected" };
  if (database === "down") return { level: "fail", label: "Down" };

  if (result.data?.status === "not-ready") {
    const draining = result.data.reason === "draining";
    return { level: "info", label: draining ? "Draining…" : "Starting…" };
  }
  return { level: "neutral", label: "Unknown" };
}

/** Roll the individual services up into one overall descriptor. */
export function deriveOverallStatus(
  backend: StatusDescriptor,
  database: StatusDescriptor,
): StatusDescriptor {
  if (backend.level === "pass" && database.level === "pass") {
    return { level: "pass", label: "All systems operational" };
  }
  if (backend.level === "fail" || database.level === "fail") {
    return { level: "fail", label: "Degraded" };
  }
  return { level: "info", label: "Initializing" };
}
