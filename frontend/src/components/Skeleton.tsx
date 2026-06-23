import { cn } from "@/lib/utils";

import { LoadingFact } from "./LoadingFact";

/**
 * A loading placeholder block. Calm, not a spinner (design brief: "calm skeletons
 * or a quiet indicator, never a jarring spinner"). The shimmer is disabled under
 * prefers-reduced-motion (index.css).
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("animate-shimmer rounded-md bg-status-neutral-bg", className)}
    />
  );
}

/** A skeleton table/list — N rows of shimmering placeholders inside a card. */
export function SkeletonRows({ rows = 6, label }: { rows?: number; label?: string }) {
  return (
    <div role="status" aria-label={label ?? "Loading"}>
      <div className="overflow-hidden rounded-xl border border-border bg-surface">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="flex items-center gap-4 border-b border-border px-4 py-4 last:border-b-0"
          >
            <div className="min-w-0 flex-[2] space-y-2">
              <Skeleton className="h-3 w-1/2" />
              <Skeleton className="h-2.5 w-1/3" />
            </div>
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-16" />
          </div>
        ))}
      </div>
      <div className="mt-4 flex flex-col items-center gap-1.5">
        {label ? <p className="text-xs text-muted-foreground">{label}</p> : null}
        <LoadingFact />
      </div>
    </div>
  );
}
