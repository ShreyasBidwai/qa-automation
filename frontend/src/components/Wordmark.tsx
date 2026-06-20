/**
 * The Polaris wordmark — a clean text mark, NOT a visual theme. No star /
 * constellation / sci-fi motif (brand guardrail): just the product name set in
 * Inter with a small descriptor, sitting quietly in the top-left.
 */
export function Wordmark() {
  return (
    <div className="flex flex-col leading-none">
      <span className="text-[15px] font-medium tracking-tight text-foreground">
        Polaris
      </span>
      <span className="mt-0.5 text-[11px] text-muted-foreground">
        QA automation platform
      </span>
    </div>
  );
}
