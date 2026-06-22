import { Badge } from "@/components/ui/badge";
import { TrustMark } from "@/components/ui/TrustMark";
import type { Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { isMutedTriage, triageSpec } from "./findingBadges";
import { historyViz, severityViz } from "./findingViz";

/**
 * One ranked-finding row: severity dot + title + severity pill, then layer, the
 * oracle-trust mark, the history tag, and any triage disposition. The shared
 * treatment for the run dashboard AND the findings inbox — colour always paired
 * with a word, muted dispositions de-emphasised.
 */
export function FindingRow({
  finding,
  selected,
  onSelect,
}: {
  finding: Finding;
  selected: boolean;
  onSelect: (finding: Finding) => void;
}) {
  const severity = severityViz(finding.severity);
  const history = historyViz(finding.status);
  const triageStatus = finding.triage?.status ?? "open";
  const triage = triageSpec(triageStatus);
  // Muted dispositions (wont_fix / false_positive) are intentionally silenced.
  const muted = isMutedTriage(triageStatus);
  return (
    <button
      type="button"
      onClick={() => onSelect(finding)}
      aria-pressed={selected}
      className={cn(
        "flex w-full gap-3 border-b border-l-[3px] border-border px-4 py-3.5 text-left last:border-b-0 hover:bg-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
        selected ? "border-l-accent bg-accent-subtle" : "border-l-transparent",
        muted && "opacity-60",
      )}
    >
      <span
        className={cn("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", severity.dot)}
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-3">
          <span className="text-sm font-medium text-foreground">{finding.title}</span>
          <span
            className={cn(
              "shrink-0 rounded px-1.5 py-0.5 text-[10.5px] font-semibold tracking-[0.02em]",
              severity.pill,
            )}
          >
            {severity.label}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <span className="rounded bg-status-neutral-bg px-1.5 py-px font-mono text-[10.5px] text-status-neutral-fg">
            {finding.layer}
          </span>
          <TrustMark source={finding.oracle_source} label />
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-[11px] font-medium",
              history.text,
            )}
          >
            <span
              className={cn("h-[5px] w-[5px] rounded-full", history.dot)}
              aria-hidden="true"
            />
            {history.label}
          </span>
          {triageStatus !== "open" ? (
            <Badge level={triage.level}>{triage.label}</Badge>
          ) : null}
        </div>
      </div>
    </button>
  );
}
