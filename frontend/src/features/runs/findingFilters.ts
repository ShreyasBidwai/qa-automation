import type { Finding } from "@/lib/api/types";

export const ALL = "all";

export interface FindingFilters {
  severity: string;
  layer: string;
  confidence: string;
  status: string;
}

export const EMPTY_FILTERS: FindingFilters = {
  severity: ALL,
  layer: ALL,
  confidence: ALL,
  status: ALL,
};

/** Client-side narrowing — each non-"all" filter must match (design-direction.md). */
export function applyFilters(findings: Finding[], f: FindingFilters): Finding[] {
  return findings.filter(
    (finding) =>
      (f.severity === ALL || finding.severity === f.severity) &&
      (f.layer === ALL || finding.layer === f.layer) &&
      (f.confidence === ALL || finding.oracle_source === f.confidence) &&
      (f.status === ALL || finding.status === f.status),
  );
}
