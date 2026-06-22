import { ArrowRight } from "lucide-react";
import { Fragment } from "react";

import type { Finding } from "@/lib/api/types";
import { cn } from "@/lib/utils";

import { buildRibbon, type RibbonHop, type Tier } from "./findingDetail";

/**
 * The cross-layer blast-path ribbon — the signature visual second to the trust
 * mark (design brief screen 8). It shows how far a problem reaches across the
 * stack as a chain page → endpoint → table, with the failing node marked. It is
 * structural, not decorative: it answers "where did it break, and what does it
 * touch". Built from the real finding `location` (degrading to the failing node
 * alone when the full path isn't resolved) — never invented.
 */

const CAPTION: Record<Tier, string> = {
  UI: "page",
  API: "endpoint",
  DB: "table",
};

export function BlastPathRibbon({ finding }: { finding: Finding }) {
  const ribbon = buildRibbon(finding);

  if (!ribbon.available) {
    return (
      <p className="text-sm text-muted-foreground">
        The cross-layer location couldn&rsquo;t be resolved for this finding.
      </p>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-start gap-x-2.5 gap-y-3">
        {ribbon.hops.map((hop, index) => (
          <Fragment key={`${hop.tier}-${hop.label}-${index}`}>
            <Node hop={hop} />
            {index < ribbon.hops.length - 1 ? (
              <ArrowRight
                className="mt-1.5 h-4 w-4 shrink-0 text-marker"
                aria-hidden="true"
              />
            ) : null}
          </Fragment>
        ))}
      </div>
      {ribbon.partial ? (
        <p className="text-xs text-muted-foreground">
          The full page → endpoint → table path couldn&rsquo;t be resolved — showing the
          failing node.
        </p>
      ) : null}
    </div>
  );
}

function Node({ hop }: { hop: RibbonHop }) {
  return (
    <div className="flex flex-col items-center gap-1.5">
      <span
        className={cn(
          "whitespace-nowrap rounded-[7px] border px-[11px] py-1.5 font-mono text-xs",
          hop.failing
            ? "border-status-fail-border bg-status-fail-bg font-semibold text-status-fail-solid"
            : "border-border bg-surface font-medium text-foreground-secondary",
        )}
      >
        {hop.label}
      </span>
      <span className="font-mono text-[9.5px] uppercase tracking-[0.04em] text-marker">
        {CAPTION[hop.tier]}
      </span>
      {hop.failing ? (
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-status-fail-solid">
          <span
            aria-hidden="true"
            className="h-0 w-0 border-x-[4px] border-b-[6px] border-x-transparent border-b-status-fail-solid"
          />
          failing here
        </span>
      ) : null}
    </div>
  );
}
