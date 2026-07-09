import type { Finding } from "@/lib/api/types";

const CSV_COLUMNS = [
  "id",
  "title",
  "layer",
  "severity",
  "status",
  "oracle_source",
  "explains_count",
  "history_classification",
  "triage_status",
] as const;

/** Quote a field iff it contains a comma/quote/newline (RFC 4180), doubling any
 *  internal quotes — the one escaping rule CSV actually needs. */
function csvEscape(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

function findingRow(finding: Finding): string[] {
  return [
    finding.id,
    finding.title,
    finding.layer,
    finding.severity,
    finding.status,
    finding.oracle_source,
    String(finding.explains_count),
    finding.history?.classification ?? "",
    finding.triage?.status ?? "",
  ];
}

/** The run's findings as CSV (RunDashboard's Export button) — a client-side export
 *  from data already on screen, not a new backend endpoint. Header row always
 *  present, even for zero findings (an honest, valid "nothing to report" file). */
export function findingsToCsv(findings: Finding[]): string {
  const lines = [CSV_COLUMNS.join(",")];
  for (const finding of findings) {
    lines.push(findingRow(finding).map(csvEscape).join(","));
  }
  return lines.join("\n");
}

/** Trigger a browser download of the run's findings as CSV. */
export function downloadFindingsCsv(runId: string, findings: Finding[]): void {
  const blob = new Blob([findingsToCsv(findings)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `run-${runId}-findings.csv`;
  link.click();
  URL.revokeObjectURL(url);
}
