import { ArrowRight } from "lucide-react";
import { Fragment } from "react";

import type { Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { buildRibbon, failureLine, type RibbonHop } from "./findingDetail";

/**
 * The cross-layer ribbon (the signature element): the UI → API → DB path
 * (page → endpoint → table) with the failing hop highlighted. Structural, not
 * decorative — it answers "where did it break, and what called it".
 */
export function CrossLayerRibbon({ finding }: { finding: Finding }) {
  const ribbon = buildRibbon(finding);
  const line = failureLine(finding);

  if (!ribbon.available) {
    return (
      <p className="text-sm text-muted-foreground">
        The cross-layer location couldn&rsquo;t be resolved for this finding.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
        {ribbon.hops.map((hop, index) => (
          <Fragment key={`${hop.tier}-${hop.label}-${index}`}>
            <Hop hop={hop} />
            {index < ribbon.hops.length - 1 ? (
              <ArrowRight
                className="h-4 w-4 shrink-0 self-center text-muted-foreground"
                aria-hidden="true"
              />
            ) : null}
          </Fragment>
        ))}
      </div>
      {line ? (
        <p className="text-xs text-muted-foreground">
          Failing hop: <span className="font-mono text-foreground">{line}</span>
        </p>
      ) : null}
      {ribbon.partial ? (
        <p className="text-xs text-muted-foreground">
          The full UI → API → DB path couldn&rsquo;t be resolved — showing the failing
          node.
        </p>
      ) : null}
    </div>
  );
}

function Hop({ hop }: { hop: RibbonHop }) {
  return (
    <div
      className={cn(
        "min-w-[112px] rounded-md border px-3 py-2",
        hop.failing
          ? "border-status-fail-solid bg-status-fail-bg"
          : "border-border bg-surface",
      )}
    >
      <div className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {hop.tier}
      </div>
      <div
        className={cn(
          "mt-0.5 break-all font-mono text-[13px]",
          hop.failing ? "text-status-fail-fg" : "text-foreground",
        )}
      >
        {hop.label}
      </div>
      {hop.failing ? (
        <div className="mt-1 text-[11px] font-medium text-status-fail-fg">failing</div>
      ) : null}
    </div>
  );
}
