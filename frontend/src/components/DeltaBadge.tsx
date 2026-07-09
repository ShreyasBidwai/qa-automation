import { ArrowDown, ArrowUp } from "lucide-react";

import type { PassRateDelta } from "@/features/runs/runMetrics";
import { cn } from "@/lib/utils";

/** A signed pass-rate change — up is good (emerald), down is bad (red), flat is
 *  quiet. Shared by the run dashboard's stat card and the account dashboard's
 *  trend card so the two read as one visual language. */
export function DeltaBadge({ delta, label }: { delta: PassRateDelta; label: string }) {
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
      {Math.abs(delta.points)}% {label}
    </span>
  );
}
