import type { Finding } from "@/lib/api/types";

import { isMutedTriage } from "./findingBadges";

export const ALL = "all";

export interface FindingFilters {
  /** A project id, or ALL. Only surfaced in the cross-project inbox; on a single
   *  run every finding shares one project, so the run dashboard leaves it at ALL. */
  project: string;
  severity: string;
  layer: string;
  confidence: string;
  status: string;
  hideMuted: boolean;
}

export const EMPTY_FILTERS: FindingFilters = {
  project: ALL,
  severity: ALL,
  layer: ALL,
  confidence: ALL,
  status: ALL,
  hideMuted: false,
};

/** Client-side narrowing — each non-"all" filter must match (design-direction.md).
 *  ``hideMuted`` drops issues triaged wont_fix / false_positive (ADR-0027). */
export function applyFilters(findings: Finding[], f: FindingFilters): Finding[] {
  return findings.filter(
    (finding) =>
      (f.project === ALL || finding.project_id === f.project) &&
      (f.severity === ALL || finding.severity === f.severity) &&
      (f.layer === ALL || finding.layer === f.layer) &&
      (f.confidence === ALL || finding.oracle_source === f.confidence) &&
      (f.status === ALL || finding.status === f.status) &&
      (!f.hideMuted || !isMutedTriage(finding.triage?.status)),
  );
}
