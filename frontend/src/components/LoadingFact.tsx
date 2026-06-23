import { useState } from "react";

import { randomQaFact } from "@/lib/qaFacts";
import { cn } from "@/lib/utils";

/**
 * A single, quietly rotating QA/testing fact shown under a loading indicator — a
 * calm professional touch while data fetches, never a distraction. Static and
 * zero-weight: one fact is picked once on mount from a hardcoded list (no fetch,
 * no dependency), so it adds no perceptible load time. It fades in softly and,
 * under prefers-reduced-motion, simply appears (the fade is disabled globally in
 * index.css). Marked decorative (aria-hidden) so it adds no noise to the loading
 * announcement, and only ever rendered on a genuine data-loading state.
 */
export function LoadingFact({ className }: { className?: string }) {
  // Chosen once, on mount — never re-rolls, never re-fetches.
  const [fact] = useState(randomQaFact);
  return (
    <p
      aria-hidden="true"
      className={cn(
        "animate-fade-in max-w-sm text-center text-xs leading-relaxed text-status-neutral-solid",
        className,
      )}
    >
      {fact}
    </p>
  );
}
